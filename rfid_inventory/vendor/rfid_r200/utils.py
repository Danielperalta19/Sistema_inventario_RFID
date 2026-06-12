import binascii
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Tuple

from .constants import CMD_EXECUTION_FAILURE
from .constants import CMD_SINGLE_POLL_INSTRUCTION
from .constants import ERR_ACCESS_FAIL
from .constants import ERR_COMMAND_ERROR
from .constants import ERR_INVENTORY_FAIL
from .constants import ERR_READ_FAIL
from .constants import ERR_WRITE_FAIL
from .constants import FRAME_TYPE_COMMAND
from .constants import FRAME_TYPE_NOTIFICATION
from .constants import FRAME_TYPE_RESPONSE
from .constants import R200_COMMAND_POS
from .constants import R200_FRAME_END
from .constants import R200_FRAME_HEADER
from .constants import R200_HEADER_POS
from .constants import R200_PARAM_LENGTH_LSB_POS
from .constants import R200_PARAM_LENGTH_MSB_POS
from .constants import R200_PARAM_POS
from .constants import R200_TYPE_POS


@dataclass
class R200Response:
    type: int
    command: int
    checksum: int
    checksum_ok: bool
    params: List[int]


def rssi_raw_a_dbm(raw: int) -> int:
    """Convierte el byte RSSI del protocolo R200 a dBm (como el demo del fabricante)."""
    valor = int(raw) & 0xFF
    return valor - 256 if valor > 127 else valor


def crc16_gen2_epc(pc: int, epc: List[int]) -> int:
    """CRC-16 Gen2 sobre PC + EPC (ISO 18000-6C)."""
    payload = bytes([(pc >> 8) & 0xFF, pc & 0xFF]) + bytes(epc)
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass
class R200PoolResponse:
    rssi: int = 0
    pc: int = 0
    epc: List[int] = None
    crc: int = 0

    def __post_init__(self):
        if self.epc is None:
            self.epc = []

    def parse(self, params: List[int]) -> None:
        if len(params) < 5:
            raise ValueError("Not enough data")
        self.rssi = rssi_raw_a_dbm(params[0])
        self.pc = (params[1] << 8) + params[2]
        epc_words = (self.pc >> 11) & 0x1F
        epc_len = int(epc_words) * 2
        if 2 <= epc_len <= 62 and len(params) >= 3 + epc_len + 2:
            self.epc = params[3 : 3 + epc_len]
            crc_off = 3 + epc_len
            self.crc = (params[crc_off] << 8) + params[crc_off + 1]
            return
        # Respaldo: trama fija 96-bit (12 bytes EPC).
        if len(params) >= 17:
            self.epc = params[3:15]
            self.crc = (params[15] << 8) + params[16]
            return
        raise ValueError("Not enough data")


class R200ErrorResponse:
    def __init__(self, error: List[int]):
        self.error = error
        self.message = ""

    def parse(self) -> str:
        if not self.error:
            self.message = "Unknown error"
        elif self.error[0] == ERR_INVENTORY_FAIL:
            self.message = "No tags detected"
        elif self.error[0] == ERR_COMMAND_ERROR:
            self.message = "Can't execute command"
        elif self.error[0] == ERR_READ_FAIL:
            self.message = "Read failed"
        elif self.error[0] == ERR_WRITE_FAIL:
            self.message = "escritura rechazada (EPC bloqueado o etiqueta no programable)"
        elif self.error[0] == ERR_ACCESS_FAIL:
            self.message = "Access failed (contraseña o permisos)"
        else:
            self.message = f"Error: 0x{self.error[0]:02x}"
        return self.message


class CommonR200Interface:
    @staticmethod
    def _checksum(payload: List[int], param_len: int) -> int:
        """Sum of bytes from Type through last parameter (uint8 wrap)."""
        checksum_region = bytes(payload[R200_TYPE_POS : R200_PARAM_POS + param_len])
        return sum(checksum_region) & 0xFF

    def _send_command(self, command: int, parameters: List[int] = None) -> List[int]:
        """
        Send command to R200 module

        Args:
            command: Command code
            parameters: List of parameter bytes (optional)
        """
        if parameters is None:
            parameters = []

        out = []

        out.append(R200_FRAME_HEADER)
        out.append(FRAME_TYPE_COMMAND)
        out.append(command)

        # Parameter length (MSB, LSB)
        param_len = len(parameters)
        out.append((param_len >> 8) & 0xFF)
        out.append(param_len & 0xFF)

        if parameters:
            out.extend(parameters)

        out.append(self._checksum(out, param_len))
        out.append(R200_FRAME_END)
        if self.debug:
            print(f"Sent: {binascii.hexlify(bytes(out)).decode()}")

        return out

    def _parse_buffer(self, buffer: bytes) -> List[R200Response]:
        """
        Receive buffer from R200 module

        Returns:
            List of R200Response objects
        """
        responses = []
        # Parse all responses in buffer
        while len(buffer) > 0:
            if self.debug:
                print(f"Buffer: {binascii.hexlify(buffer).decode()}")

            # Minimum packet size (header+type+cmd+len(2)+checksum+end) = 7
            if len(buffer) < 7:
                break

            if buffer[R200_HEADER_POS] == R200_FRAME_HEADER:
                # Check frame type
                if buffer[R200_TYPE_POS] in [
                    FRAME_TYPE_RESPONSE,
                    FRAME_TYPE_NOTIFICATION,
                ]:
                    resp = R200Response(
                        type=buffer[R200_TYPE_POS],
                        command=buffer[R200_COMMAND_POS],
                        checksum=0,
                        checksum_ok=False,
                        params=[],
                    )

                    param_len = (buffer[R200_PARAM_LENGTH_MSB_POS] << 8) + buffer[
                        R200_PARAM_LENGTH_LSB_POS
                    ]

                    # Check if we have enough data
                    if len(buffer) < R200_PARAM_POS + param_len + 2:
                        break

                    resp.params = list(
                        buffer[R200_PARAM_POS : R200_PARAM_POS + param_len]
                    )

                    checksum = self._checksum(buffer, param_len)
                    if checksum == buffer[R200_PARAM_POS + param_len]:
                        resp.checksum_ok = True
                        resp.checksum = checksum

                    responses.append(resp)

                    # Remove processed packet from buffer
                    buffer = buffer[R200_PARAM_POS + param_len + 2 :]
                else:
                    # Invalid frame type, skip this byte
                    buffer = buffer[1:]
            else:
                # Invalid header, skip this byte
                buffer = buffer[1:]

        return responses

    def _read_tags(
        self, responses: List[R200Response]
    ) -> Tuple[List[R200PoolResponse], Optional[Exception]]:
        """
        Read RFID tags using multiple poll instruction

        Returns:
            List of R200PoolResponse objects containing tag data
            Optional exception if an error occurs
        """
        pool: List[R200PoolResponse] = []
        epc_ids: set[str] = set()
        err: Optional[Exception] = None

        for resp in responses:
            if resp.command == CMD_SINGLE_POLL_INSTRUCTION:
                item = R200PoolResponse()
                try:
                    item.parse(resp.params)
                except ValueError:
                    # Trama corrupta o EPC inválido: ignorar (evita EPC fantasma en UI).
                    continue

                epc_hex = binascii.hexlify(bytes(item.epc)).decode()
                if epc_hex not in epc_ids:
                    epc_ids.add(epc_hex)
                    pool.append(item)

            elif resp.command == CMD_EXECUTION_FAILURE:
                error_data = R200ErrorResponse(resp.params)
                if error_data.error and error_data.error[0] == ERR_INVENTORY_FAIL:
                    continue
                error_msg = error_data.parse()
                err = RuntimeError(f"Error reading RFID: {error_msg}")

        return pool, err


class R200AsyncInterface(ABC, CommonR200Interface):
    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def send_command(self, command: int, parameters: List[int]) -> None:
        pass

    @abstractmethod
    async def receive(self) -> List[R200Response]:
        pass

    @abstractmethod
    async def read_tags(self) -> List[R200PoolResponse]:
        pass

    @abstractmethod
    def _read_all_available(self) -> bytes:
        pass

    @abstractmethod
    async def hw_info(self) -> List[R200PoolResponse]:
        pass

    @abstractmethod
    async def get_power(self) -> float:
        pass

    @abstractmethod
    async def get_demodulator_params(self) -> dict[str, int]:
        """Get demodulator parameters"""
        """ Returns a dict with the parameters """
        """
        Sent: aa00f10000f1dd
        [RX] aa01f10004020600b0aedd
        Buffer: aa01f10004020600b0aedd
        Demodulator parameters: {'Mixer_ G': 2, 'IF_ G': 6, 'Signal demodulation threshold Thrd:': 176}
        """
        pass

    @abstractmethod
    async def set_demodulator_params(self, mixer_g: int, if_g: int, thrd: int) -> bool:
        """Set demodulator parameters"""
        """ Returns a bool """
        """
        set_demodulator_params(mixer_g=2, if_g=7, thrd=100)
        Sent: aa00f000040207006461dd
        Buffer: aa01f0000100f2dd
        """
        pass


class R200Interface(ABC, CommonR200Interface):
    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def send_command(self, command: int, parameters: List[int]) -> None:
        pass

    @abstractmethod
    def receive(self) -> List[R200Response]:
        pass

    @abstractmethod
    def read_tags(self) -> List[R200PoolResponse]:
        pass

    @abstractmethod
    def _read_all_available(self) -> bytes:
        pass

    @abstractmethod
    def hw_info(self) -> List[R200PoolResponse]:
        pass

    @abstractmethod
    def get_power(self) -> float:
        pass

    @abstractmethod
    def get_demodulator_params(self) -> dict[str, int]:
        """Get demodulator parameters"""
        """ Returns a dict with the parameters """
        """
        Sent: aa00f10000f1dd
        [RX] aa01f10004020600b0aedd
        Buffer: aa01f10004020600b0aedd
        Demodulator parameters: {'Mixer_ G': 2, 'IF_ G': 6, 'Signal demodulation threshold Thrd:': 176}
        """
        pass

    @abstractmethod
    def set_demodulator_params(self, mixer_g: int, if_g: int, thrd: int) -> bool:
        """Set demodulator parameters"""
        """ Returns a bool """
        """
        set_demodulator_params(mixer_g=2, if_g=7, thrd=100)
        Sent: aa00f000040207006461dd
        Buffer: aa01f0000100f2dd
        """
        pass
