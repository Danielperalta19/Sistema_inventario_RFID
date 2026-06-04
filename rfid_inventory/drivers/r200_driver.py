import os
import sys
import time

# Librería oficial embebida (vendor) para evitar fallos de pip/piwheels en Raspberry Pi.
_raiz_vendor = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
if os.path.isdir(os.path.join(_raiz_vendor, "rfid_r200")):
    if _raiz_vendor not in sys.path:
        sys.path.insert(0, _raiz_vendor)

from rfid_r200 import R200


class LecturaEtiqueta:
    """Una lectura de etiqueta: EPC en hexadecimal y RSSI entero."""

    def __init__(self, epc_hex, rssi):
        self.epc_hex = epc_hex
        self.rssi = rssi


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
            salida.append(LecturaEtiqueta(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi)))
        return salida

    def leer_primera_etiqueta_una_encuesta(self):
        """Lee etiquetas con una sola encuesta (single poll) y devuelve la primera o ``None``."""
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._modulo_rfid.read_tags_single()
        if not tags:
            return None
        t = tags[0]
        return LecturaEtiqueta(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi))

    def programar_epc12_en_etiqueta(
        self, epc_actual_hex: str, epc_nuevo_hex: str, access_password: int = 0
    ) -> None:
        """Escribe el EPC de 12 bytes (96 bits) en la etiqueta.

        Pasos del protocolo: seleccionar por EPC actual, modo de selección 0x02 y escritura en
        el banco EPC (membank 0x01), palabra inicial 2, datos de 12 bytes.
        """
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        actual = (epc_actual_hex or "").strip().lower()
        nuevo = (epc_nuevo_hex or "").strip().lower()
        if not actual or len(actual) < 24:
            raise ValueError("EPC actual inválido (se esperan 24 hex / 96-bit).")
        if not nuevo or len(nuevo) < 24:
            raise ValueError("EPC inválido (se esperan 24 hex / 12 bytes).")
        # Selección del tag objetivo (puede lanzar ``RuntimeError`` con detalle)
        self._modulo_rfid.set_select_epc96(actual[:24])
        ok = self._modulo_rfid.set_select_mode(0x02)
        if not ok:
            raise RuntimeError("No se pudo configurar Select Mode (0x12).")

        datos = bytes.fromhex(nuevo[:24])
        ok = self._modulo_rfid.write_label(
            access_password=int(access_password), membank=0x01, sa_word=2, data=datos
        )
        if not ok:
            raise RuntimeError("Falló escritura de EPC (CMD_WRITE_LABEL).")
