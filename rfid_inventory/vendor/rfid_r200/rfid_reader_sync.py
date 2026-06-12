from typing import List
from typing import Optional
from typing import Tuple

import serial
import time

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

    def _receive_until_quiet(
        self, max_wait: float = 0.35, quiet: float = 0.06, chunk_timeout: float = 0.04
    ) -> bytes:
        """Lee respuestas del inventario hasta silencio (más rápido que esperar 1 s vacío)."""
        buf = bytearray()
        deadline = time.monotonic() + max_wait
        last_data = time.monotonic()
        old_timeout = self.port.timeout
        self.port.timeout = chunk_timeout
        try:
            while time.monotonic() < deadline:
                chunk = self.port.read(512)
                if chunk:
                    buf.extend(chunk)
                    last_data = time.monotonic()
                elif time.monotonic() - last_data >= quiet:
                    break
        finally:
            self.port.timeout = old_timeout
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
        # Tercer byte ≈ rondas de inventario (×~100 ms c/u). Hay que esperar a que terminen.
        poll_units = 0x06
        self.send_command(CMD_MULTIPLE_POLL_INSTRUCTION, [0x22, 0x00, poll_units])
        max_wait = poll_units * 0.12 + 0.35
        buffer = self._receive_until_quiet(max_wait=max_wait, quiet=0.07)
        responses = self._parse_buffer(bytearray(buffer))
        return self._read_tags(responses)

    def read_tags_single(self) -> Tuple[List[R200PoolResponse], Optional[Exception]]:
        """Read RFID tags using single poll instruction (0x22)."""
        self.send_command(CMD_SINGLE_POLL_INSTRUCTION, [])
        buffer = self._receive_until_quiet(max_wait=0.45, quiet=0.07)
        responses = self._parse_buffer(bytearray(buffer))
        return self._read_tags(responses)

    def set_select_epc_mask(self, mask: bytes, sel_param: int = 0x01, ptr: int = 0x00000020) -> bool:
        """Select por máscara EPC (protocolo V2.3.3 §5)."""
        if not mask or len(mask) < 2:
            raise ValueError("Máscara Select inválida.")
        sel = int(sel_param) & 0xFF
        mask_len = len(mask) * 8
        truncate = 0x00
        params = (
            [sel]
            + list(int(ptr).to_bytes(4, "big"))
            + [mask_len, truncate]
            + list(mask)
        )
        self.send_command(CMD_SET_SELECT_PARAMETER, params)
        buffer = self._receive_until_quiet(max_wait=0.45, quiet=0.06)
        responses = self._parse_buffer(bytearray(buffer))
        for resp in responses:
            if resp.command == CMD_SET_SELECT_PARAMETER:
                return bool(resp.params) and resp.params[0] == 0x00
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
        buffer = self._receive_until_quiet(max_wait=0.45, quiet=0.06)
        responses = self._parse_buffer(bytearray(buffer))
        for resp in responses:
            if resp.command == CMD_SET_SEND_SELECT_INSTRUCTION:
                if resp.params and resp.params[0] == 0x00:
                    return True
            if resp.command == 0xFF:
                return False
        return False

    def detener_poll_multiple(self) -> None:
        """Detiene inventario continuo antes de Select/Write."""
        try:
            self.send_command(CMD_STOP_MULTIPLE_POLL, [])
            buffer = self._receive_until_quiet(max_wait=0.35, quiet=0.06)
            self._parse_buffer(bytearray(buffer))
        except Exception:
            pass

    def set_select_epc96(self, epc_hex: str, sel_param: int = 0x01) -> bool:
        """Select 96-bit (12 bytes) — compatible con demo (MaskLen 0x60)."""
        epc_hex = (epc_hex or "").strip().lower()
        if len(epc_hex) % 2:
            epc_hex = "0" + epc_hex
        if len(epc_hex) < 24:
            raise ValueError("EPC hex inválido (se esperan 24 hex / 96-bit).")
        return self.set_select_epc_mask(bytes.fromhex(epc_hex[:24]), sel_param=sel_param)

    def configurar_select_epc_para_escritura(
        self, mask: bytes, select_mode: int = 0x02
    ) -> bool:
        """Protocolo R200 §5–6: primero parámetros Select (0x0C), luego modo Select (0x12)."""
        if not self.set_select_epc_mask(mask, sel_param=0x01):
            return False
        return self.set_select_mode(select_mode)

    def configurar_select_solo_parametros(
        self, mask: bytes, sel_param: int = 0x01
    ) -> bool:
        """Solo 0x0C — algunos demos envían 0x0C y luego 0x49 sin 0x12."""
        return self.set_select_epc_mask(mask, sel_param=sel_param)

    def preparar_escritura_minima(self) -> None:
        """Detiene inventario continuo antes de escribir (sin tocar Select)."""
        self.detener_poll_multiple()

    def preparar_escritura_sin_select(self) -> bool:
        """Una sola etiqueta en campo: sin filtro Select (modo 0x01, como varios demos UHF)."""
        self.preparar_escritura_minima()
        try:
            params = [0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            self.send_command(CMD_SET_SELECT_PARAMETER, params)
            buffer = self._receive_until_quiet(max_wait=0.35, quiet=0.06)
            self._parse_buffer(bytearray(buffer))
        except Exception:
            pass
        return self.set_select_mode(0x01)

    @staticmethod
    def _write_response_ok(resp: R200Response) -> bool:
        if resp.command != CMD_WRITE_LABEL:
            return False
        params = resp.params or []
        if not params:
            return False
        if len(params) == 1:
            return params[0] == 0x00
        # Respuesta típica: UL + PC(2) + EPC(12) + status(0x00)
        return params[-1] == 0x00

    def limpiar_filtro_select(self) -> None:
        """Quita el filtro por EPC; inventario abierto (Select vacío + modo 0x02)."""
        try:
            self.detener_poll_multiple()
        except Exception:
            pass
        try:
            params = [0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            self.send_command(CMD_SET_SELECT_PARAMETER, params)
            buffer = self._receive_until_quiet(max_wait=0.35, quiet=0.06)
            self._parse_buffer(bytearray(buffer))
        except Exception:
            pass
        try:
            self.set_select_mode(0x02)
        except Exception:
            pass

    def _flush_serial_input(self) -> None:
        try:
            if self.port and self.port.is_open:
                self.port.reset_input_buffer()
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
        self._flush_serial_input()
        self.send_command(CMD_WRITE_LABEL, params)
        # Escritura Gen2 puede tardar 1–3 s; leer hasta silencio prolongado.
        buffer = bytearray()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            chunk = self._receive_until_quiet(max_wait=0.4, quiet=0.1, chunk_timeout=0.05)
            if chunk:
                buffer.extend(chunk)
            responses = self._parse_buffer(bytearray(buffer))
            for resp in responses:
                if self._write_response_ok(resp):
                    return True
                if resp.command == 0xFF:
                    err = R200ErrorResponse(resp.params or [])
                    raise RuntimeError(err.parse())
            if chunk:
                continue
            if buffer:
                break
            time.sleep(0.05)
        if buffer:
            for resp in self._parse_buffer(bytearray(buffer)):
                if self._write_response_ok(resp):
                    return True
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
