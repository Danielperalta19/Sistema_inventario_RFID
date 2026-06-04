from typing import List
from typing import Optional
from typing import Tuple

import serial

from .constants import CMD_ACQUIRE_TRANSMIT_POWER
from .constants import CMD_GET_MODULE_INFO
from .constants import CMD_GET_RECEIVER_DEMODULATOR_PARAMETERS
from .constants import CMD_MULTIPLE_POLL_INSTRUCTION
from .constants import CMD_SINGLE_POLL_INSTRUCTION
from .constants import CMD_SET_SELECT_PARAMETER
from .constants import CMD_SET_SEND_SELECT_INSTRUCTION
from .constants import CMD_WRITE_LABEL
from .constants import CMD_SET_RECEIVER_DEMODULATOR_PARAMETERS
from .constants import CMD_STOP_MULTIPLE_POLL
from .constants import CMD_SET_TRANSMIT_POWER
from .utils import R200ErrorResponse
from .utils import R200Interface
from .utils import R200PoolResponse
from .utils import R200Response


class R200(R200Interface):
    """Python implementation of R200 RFID module library"""

    def __init__(
        self, port: str, speed: int = 115200, debug: bool = False, timeout: float = 1.0
    ):
        """
        Initialize R200 RFID module

        Args:
            port: Serial port name (e.g., '/dev/ttyUSB0', 'COM3')
            speed: Baud rate (default: 115200)
            debug: Enable debug output (default: False)
        """
        self.debug = debug
        self.port_name = port
        self.speed = speed
        self.timeout = timeout
        self.port = None

        try:
            self.port = serial.Serial(
                port=port,
                baudrate=speed,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=timeout,
                write_timeout=timeout,
            )
        except OSError as e:
            raise OSError(f"Failed to open serial port: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to open serial port: {e}") from e

    def close(self) -> None:
        """Close the serial port connection"""
        if self.port and self.port.is_open:
            self.port.close()
        else:
            raise RuntimeError("Serial port not opened")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False

    def send_command(self, command: int, parameters: List[int] = None) -> None:
        """
        Send command to R200 module

        Args:
            command: Command code
            parameters: List of parameter bytes (optional)
        """
        out = self._send_command(command, parameters)

        self.port.write(bytes(out))

    def _read_all_available(self) -> bytes:
        """Read until no more bytes arrive within the configured timeout."""
        buf = bytearray()
        while True:
            chunk = self.port.read(512)
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def receive(self) -> List[R200Response]:
        """
        Receive responses from R200 module

        Returns:
            List of R200Response objects
        """
        buffer = bytearray(self._read_all_available())

        responses = self._parse_buffer(buffer)

        return responses

    def read_tags(self) -> Tuple[List[R200PoolResponse], Optional[Exception]]:
        """
        Read RFID tags using multiple poll instruction

        Returns:
            List of R200PoolResponse objects containing tag data
            Optional exception if an error occurs
        """
        self.send_command(CMD_MULTIPLE_POLL_INSTRUCTION, [0x22, 0x00, 0x0A])

        responses = self.receive()

        return self._read_tags(responses)

    def read_tags_single(self) -> Tuple[List[R200PoolResponse], Optional[Exception]]:
        """Read RFID tags using single poll instruction (0x22)."""
        self.send_command(CMD_SINGLE_POLL_INSTRUCTION, [])
        responses = self.receive()
        return self._read_tags(responses)

    def set_select_epc96(self, epc_hex: str) -> bool:
        """Select a single tag by EPC (96-bit) using protocol V2.3.3.

        Uses:
        - MemBank = EPC (0x01)
        - Ptr = 0x00000020 bits (skip CRC+PC)
        - MaskLen = 0x60 bits (96-bit EPC)
        - Truncate = 0x00
        """
        epc_hex = (epc_hex or "").strip().lower()
        if len(epc_hex) < 24:
            raise ValueError("EPC hex inválido (se esperan 24 hex / 96-bit).")
        mask = bytes.fromhex(epc_hex[:24])
        sel_param = 0x01  # Target=0, Action=0, MemBank=EPC(01)
        ptr = 0x00000020
        mask_len = 0x60
        truncate = 0x00
        params = [sel_param] + list(ptr.to_bytes(4, "big")) + [mask_len, truncate] + list(mask)
        self.send_command(CMD_SET_SELECT_PARAMETER, params)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_SET_SELECT_PARAMETER:
                # En práctica, algunos firmwares devuelven bien el payload aunque checksum_ok
                # no siempre se marque (buffer parcial). Nos interesa el código 0x00.
                return resp.params == [0x00]
            if resp.command == 0xFF:
                code = resp.params[0] if resp.params else None
                raise RuntimeError(f"Select EPC falló (0xFF). Código error: {code}")
        raise RuntimeError(
            "No hubo respuesta al comando Select (0x0C). "
            "Si estás usando el emulador Arduino, probablemente no soporta Select/Write."
        )

    def set_select_mode(self, mode: int = 0x02) -> bool:
        """Set Send-Select mode (CMD 0x12).

        mode:
        - 0x00: send Select before all operations on the tag
        - 0x01: do not send Select before tag operation
        - 0x02: send Select before tag operations other than inventory polling
        """
        m = int(mode) & 0xFF
        self.send_command(CMD_SET_SEND_SELECT_INSTRUCTION, [m])
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_SET_SEND_SELECT_INSTRUCTION:
                if resp.params == [0x00]:
                    return True
            if resp.command == 0xFF:
                return False
        return False

    def detener_poll_multiple(self) -> None:
        """Detiene inventario continuo antes de Select/Write."""
        try:
            self.send_command(CMD_STOP_MULTIPLE_POLL, [])
            self.receive()
        except Exception:
            pass

    def limpiar_filtro_select(self) -> None:
        """Quita el filtro por EPC tras escritura; el inventario vuelve a ver todas las etiquetas.

        Tras ``set_select_mode(0x00)`` (escritura), el lector solo respondía a la etiqueta
        seleccionada. Restauramos modo 0x02 y máscara de 0 bits.
        """
        try:
            self.detener_poll_multiple()
        except Exception:
            pass
        try:
            # Select sin máscara (0 bits) = sin filtro activo
            params = [0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            self.send_command(CMD_SET_SELECT_PARAMETER, params)
            self.receive()
        except Exception:
            pass
        try:
            # 0x02: Select solo en operaciones distintas al inventario (poll múltiple/simple)
            self.set_select_mode(0x02)
        except Exception:
            pass

    def write_label(self, access_password: int, membank: int, sa_word: int, data: bytes) -> bool:
        """Write data to tag memory bank (CMD 0x49) as per protocol V2.3.3.

        - access_password: 32-bit (0 if unset)
        - membank: 0x00 RFU, 0x01 EPC, 0x02 TID, 0x03 USER
        - sa_word: start address (word units)
        - data: bytes (must be multiple of 2 bytes). Max 64 bytes (32 words).
        """
        if data is None:
            data = b""
        if len(data) == 0 or (len(data) % 2) != 0:
            raise ValueError("data debe ser múltiplo de 2 bytes (word).")
        if len(data) > 64:
            raise ValueError("data demasiado larga (máx 64 bytes / 32 words).")
        ap = int(access_password) & 0xFFFFFFFF
        mb = int(membank) & 0xFF
        sa = int(sa_word) & 0xFFFF
        dl = (len(data) // 2) & 0xFFFF
        params = list(ap.to_bytes(4, "big")) + [mb] + list(sa.to_bytes(2, "big")) + list(dl.to_bytes(2, "big")) + list(data)
        self.send_command(CMD_WRITE_LABEL, params)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_WRITE_LABEL:
                if resp.params and resp.params[-1] == 0x00:
                    return True
            if resp.command == 0xFF:
                err = R200ErrorResponse(resp.params or [])
                raise RuntimeError(err.parse())
        return False

    def hw_info(self) -> List[R200PoolResponse]:
        self.send_command(
            CMD_GET_MODULE_INFO,
            [
                0x00,
            ],
        )
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_GET_MODULE_INFO:
                return bytearray(resp.params).decode()
        return Exception("Error reading RFID")

    def get_power(self) -> float:
        """Get reader power"""
        """ Returns a float with the dBm value """
        self.send_command(CMD_ACQUIRE_TRANSMIT_POWER)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_ACQUIRE_TRANSMIT_POWER:
                return int.from_bytes(bytes(resp.params), "big") / 100.0
        raise Exception("Error reading RFID")

    def set_power(self, power: float) -> bool:
        """Set reader power"""
        """ power is a float with the dBm value """
        # Beware: tested modules only support values from 15 to 26 dBm
        value = int(power * 100)
        params = list(value.to_bytes(2, "big"))
        self.send_command(CMD_SET_TRANSMIT_POWER, params)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_SET_TRANSMIT_POWER:
                return resp.params == [0]
        raise Exception("Error setting power")

    def get_demodulator_params(self) -> dict[str, int]:
        """Get demodulator parameters"""
        """ Returns a dict with the parameters """
        """
        Sent: aa00f10000f1dd
        [RX] aa01f10004020600b0aedd
        Buffer: aa01f10004020600b0aedd
        Demodulator parameters: {'Mixer_ G': 2, 'IF_ G': 6, 'Signal demodulation threshold Thrd:': 176}
        """
        self.send_command(CMD_GET_RECEIVER_DEMODULATOR_PARAMETERS)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_GET_RECEIVER_DEMODULATOR_PARAMETERS:
                return {
                    "Mixer_ G": resp.params[0],
                    "IF_ G": resp.params[1],
                    "Thrd:": int.from_bytes(bytes(resp.params[2:]), "big"),
                }
        raise Exception("Error reading RFID")

    def set_demodulator_params(self, mixer_g: int, if_g: int, thrd: int) -> bool:
        """Set demodulator parameters"""
        """ params is a dict with the parameters """
        """ Returns a bool """
        """
        Sent: aa00f004020600b0aedd
        [RX] aa01f004020600b0aedd
        Buffer: aa01f004020600b0aedd
        """
        params = [mixer_g, if_g] + list(thrd.to_bytes(2, "big"))
        self.send_command(CMD_SET_RECEIVER_DEMODULATOR_PARAMETERS, params)
        responses = self.receive()
        for resp in responses:
            if resp.command == CMD_SET_RECEIVER_DEMODULATOR_PARAMETERS:
                return resp.params == [0]
        raise Exception("Error setting demodulator parameters")
