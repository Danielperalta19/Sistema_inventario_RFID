import time

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
