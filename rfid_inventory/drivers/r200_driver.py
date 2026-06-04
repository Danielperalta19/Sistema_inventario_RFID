import os
import sys
import time

# Librería oficial embebida (vendor) para evitar fallos de pip/piwheels en Raspberry Pi.
_raiz_vendor = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
if os.path.isdir(os.path.join(_raiz_vendor, "rfid_r200")):
    if _raiz_vendor not in sys.path:
        sys.path.insert(0, _raiz_vendor)

from rfid_r200 import R200

# PC Gen2 para EPC de 96 bits (12 bytes) — palabra de control habitual en etiquetas UHF.
_PC_EPC_96_BITS = 0x3400


class LecturaEtiqueta:
    """Una lectura de etiqueta: EPC en hexadecimal, RSSI entero y PC (protocol control) si aplica."""

    def __init__(self, epc_hex, rssi, pc=None):
        self.epc_hex = epc_hex
        self.rssi = rssi
        self.pc = pc


class LectorR200:
    """Conexión serial al módulo R200: lecturas y escritura de EPC vía la librería embebida ``rfid_r200``."""

    def __init__(self) -> None:
        self._modulo_rfid = None

    @property
    def connected(self) -> bool:
        return self._modulo_rfid is not None

    def conectar(self, puerto, baudios, debug=False):
        if self._modulo_rfid is not None:
            return
        self._modulo_rfid = R200(puerto, baudios, debug=debug)
        time.sleep(2.0)
        self._configurar_modulo_tras_conexion()

    def _configurar_modulo_tras_conexion(self) -> None:
        """Región US (902–928 MHz, adecuada para México) y demodulador; ignora fallos (p. ej. emulador Arduino)."""
        if self._modulo_rfid is None:
            return
        try:
            self._modulo_rfid.send_command(0x07, [0x21])
            self._modulo_rfid.receive()
        except Exception:
            pass
        try:
            self._modulo_rfid.set_demodulator_params(mixer_g=2, if_g=7, thrd=100)
        except Exception:
            pass

    def cerrar(self):
        if self._modulo_rfid is None:
            return
        self._modulo_rfid.close()
        self._modulo_rfid = None

    def leer_etiquetas_una_ronda(self):
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._modulo_rfid.read_tags()
        salida = []
        for t in tags:
            salida.append(
                LecturaEtiqueta(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi), pc=int(t.pc))
            )
        return salida

    def leer_primera_etiqueta_una_encuesta(self):
        """Lee etiquetas con una sola encuesta (single poll) y devuelve la primera o ``None``."""
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._modulo_rfid.read_tags_single()
        if not tags:
            return None
        t = tags[0]
        return LecturaEtiqueta(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi), pc=int(t.pc))

    def programar_epc12_en_etiqueta(
        self,
        epc_actual_hex: str,
        epc_nuevo_hex: str,
        access_password: int = 0,
        pc_etiqueta: int | None = None,
    ) -> None:
        """Escribe el EPC de 12 bytes (96 bits) en la etiqueta.

        Intenta primero solo el cuerpo EPC (palabra 2); si falla, PC+EPC (desde palabra 1).
        """
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        actual = (epc_actual_hex or "").strip().lower()
        nuevo = (epc_nuevo_hex or "").strip().lower()
        if not actual or len(actual) < 24:
            raise ValueError("EPC actual inválido (se esperan 24 hex / 96-bit).")
        if not nuevo or len(nuevo) < 24:
            raise ValueError("EPC inválido (se esperan 24 hex / 12 bytes).")

        self._modulo_rfid.detener_poll_multiple()
        time.sleep(0.06)

        self._modulo_rfid.set_select_epc96(actual[:24])
        if not self._modulo_rfid.set_select_mode(0x00):
            raise RuntimeError("No se pudo configurar Select Mode (0x12).")
        time.sleep(0.08)

        datos_epc = bytes.fromhex(nuevo[:24])
        pc = int(pc_etiqueta) if pc_etiqueta is not None else _PC_EPC_96_BITS

        if self._escribir_en_banco_epc(access_password, sa_word=2, data=datos_epc):
            return
        bloque_pc_epc = pc.to_bytes(2, "big") + datos_epc
        if self._escribir_en_banco_epc(access_password, sa_word=1, data=bloque_pc_epc):
            return

        raise RuntimeError(
            "No se pudo grabar la etiqueta. Deja solo UNA etiqueta cerca, vuelve a Escanear y escribe de nuevo."
        )

    def _escribir_en_banco_epc(self, access_password: int, sa_word: int, data: bytes) -> bool:
        try:
            return bool(
                self._modulo_rfid.write_label(
                    access_password=int(access_password),
                    membank=0x01,
                    sa_word=int(sa_word),
                    data=data,
                )
            )
        except RuntimeError:
            raise
        except Exception:
            return False
