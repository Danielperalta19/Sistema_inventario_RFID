import threading
import time

from rfid_inventory.drivers import TagRead


class Scanner:
    """Escaneo en segundo plano hasta sque se mande top(). Cada lectura se notifica (incluye repetidos)."""

    def __init__(self, driver):
        self._driver = driver
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._seen = set()
        self._last_rssi = {}

    def reset(self):
        with self._lock:
            self._seen.clear()
            self._last_rssi.clear()

    def start(self, on_tag_read):
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(on_tag_read,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4.0)
            self._thread = None

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self):
        with self._lock:
            return {"seen_epcs": set(self._seen), "last_rssi": dict(self._last_rssi)}

    def _loop(self, on_tag_read):
        while not self._stop.is_set():
            tags = self._driver.read_tags_once()
            for idx_in_batch, tag in enumerate(tags):
                if self._stop.is_set():
                    break
                with self._lock:
                    self._seen.add(tag.epc_hex)
                    self._last_rssi[tag.epc_hex] = tag.rssi
                on_tag_read(tag, idx_in_batch)
            time.sleep(0.04)
