import os
import sys
import time

# Librería oficial embebida (vendor) para evitar fallos de pip/piwheels en Raspberry Pi.
_vendor_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
if os.path.isdir(os.path.join(_vendor_root, "rfid_r200")):
    if _vendor_root not in sys.path:
        sys.path.insert(0, _vendor_root)

from rfid_r200 import R200


class TagRead:
    def __init__(self, epc_hex, rssi):
        self.epc_hex = epc_hex
        self.rssi = rssi


class R200Driver:
    """Conexión serial y lectura de tags vía rfid-r200."""

    def __init__(self) -> None:
        self._rfid = None

    @property
    def connected(self) -> bool:
        return self._rfid is not None

    def connect(self, port, baud, debug=False):
        if self._rfid is not None:
            return
        self._rfid = R200(port, baud, debug=debug)
        time.sleep(2.0)

    def close(self):
        if self._rfid is None:
            return
        self._rfid.close()
        self._rfid = None

    def read_tags_once(self):
        if self._rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._rfid.read_tags()
        out = []
        for t in tags:
            out.append(TagRead(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi)))
        return out

    def read_one_tag_single_poll(self):
        """Lee tags con single poll y regresa el primero (o None)."""
        if self._rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._rfid.read_tags_single()
        if not tags:
            return None
        t = tags[0]
        return TagRead(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi))

    def write_epc12_hex(self, current_epc_hex: str, new_epc12_hex: str, access_password: int = 0) -> None:
        """Escritura de EPC (12 bytes / 96-bit) en la etiqueta.

        Flujo:
        - Select por EPC actual (96-bit) para operar un solo tag
        - Set Select Mode = 0x02 (antes de operaciones no-inventory)
        - Write to MemBank EPC (0x01), SA=2 words (salta CRC+PC), DL=6 words (12 bytes)
        """
        if self._rfid is None:
            raise RuntimeError("No conectado")
        cur = (current_epc_hex or "").strip().lower()
        new = (new_epc12_hex or "").strip().lower()
        if not cur or len(cur) < 24:
            raise ValueError("EPC actual inválido (se esperan 24 hex / 96-bit).")
        if not new or len(new) < 24:
            raise ValueError("EPC inválido (se esperan 24 hex / 12 bytes).")
        # Select target tag
        # Select target tag (puede lanzar RuntimeError con detalle)
        self._rfid.set_select_epc96(cur[:24])
        ok = self._rfid.set_select_mode(0x02)
        if not ok:
            raise RuntimeError("No se pudo configurar Select Mode (0x12).")

        data = bytes.fromhex(new[:24])
        ok = self._rfid.write_label(access_password=int(access_password), membank=0x01, sa_word=2, data=data)
        if not ok:
            raise RuntimeError("Falló escritura de EPC (CMD_WRITE_LABEL).")
