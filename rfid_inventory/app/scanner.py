import threading
import time


class Escaner:
    """Escaneo en segundo plano hasta ``detener()``. Cada lectura se notifica (incluye repetidos)."""

    def __init__(self, lector):
        self._lector = lector
        self._hilo = None
        self._evento_detener = threading.Event()
        self._evento_pausa = threading.Event()
        self._candado = threading.Lock()
        self._epcs_vistos = set()
        self._ultimo_rssi_por_epc = {}

    def reiniciar(self):
        self._evento_pausa.clear()
        with self._candado:
            self._epcs_vistos.clear()
            self._ultimo_rssi_por_epc.clear()

    def iniciar(self, al_leer_etiqueta, al_error=None):
        if self.esta_en_ejecucion():
            return
        self._evento_detener.clear()
        self._evento_pausa.clear()
        self._hilo = threading.Thread(target=self._bucle, args=(al_leer_etiqueta, al_error), daemon=True)
        self._hilo.start()

    def detener(self):
        self._evento_detener.set()
        if self._hilo is not None:
            # Si detener() se llama desde el mismo hilo del escáner (p.ej. dentro de al_leer_etiqueta),
            # no podemos hacer join() de nosotros mismos.
            if threading.current_thread() is self._hilo:
                return
            self._hilo.join(timeout=4.0)
            self._hilo = None

    def esta_en_ejecucion(self):
        return self._hilo is not None and self._hilo.is_alive()

    def pausar(self):
        self._evento_pausa.set()

    def reanudar(self):
        self._evento_pausa.clear()

    def esta_pausado(self):
        return self._evento_pausa.is_set()

    def instantanea(self):
        with self._candado:
            return {"seen_epcs": set(self._epcs_vistos), "last_rssi": dict(self._ultimo_rssi_por_epc)}

    def _bucle(self, al_leer_etiqueta, al_error):
        while not self._evento_detener.is_set():
            while self._evento_pausa.is_set() and not self._evento_detener.is_set():
                time.sleep(0.05)
            try:
                tags = self._lector.leer_etiquetas_una_ronda()
            except Exception as e:
                # Error de serial / desconexión / puerto ocupado, etc.
                if callable(al_error):
                    try:
                        al_error(e)
                    except Exception:
                        pass
                self._evento_detener.set()
                break
            for indice_en_lote, tag in enumerate(tags):
                if self._evento_detener.is_set():
                    break
                with self._candado:
                    self._epcs_vistos.add(tag.epc_hex)
                    self._ultimo_rssi_por_epc[tag.epc_hex] = tag.rssi
                al_leer_etiqueta(tag, indice_en_lote)
            time.sleep(0.04)
