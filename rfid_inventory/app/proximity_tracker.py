"""Proximidad por RSSI para rastreo tipo 'frío/caliente'."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EstadoProximidad:
    epc_objetivo: str
    ultimo_rssi: int | None = None
    rssi_suavizado: float | None = None
    ultima_lectura_ms: int | None = None
    # Rango dinámico de RSSI para mapear a la barra (se ajusta con las lecturas)
    rssi_min: int = -90
    rssi_max: int = -35


class RastreadorProximidad:
    """Convierte RSSI en un nivel 0..100 con suavizado."""

    def __init__(self, alpha: float = 0.25):
        self._alpha = max(0.05, min(0.8, float(alpha)))
        self._estado: EstadoProximidad | None = None

    def reiniciar(self, epc_objetivo_hex: str):
        epc = (epc_objetivo_hex or "").strip().lower()
        self._estado = EstadoProximidad(epc_objetivo=epc)

    @property
    def estado(self) -> EstadoProximidad | None:
        return self._estado

    def actualizar(self, rssi: int, instante_ms: int) -> EstadoProximidad | None:
        st = self._estado
        if st is None:
            return None
        r = int(rssi)
        st.ultimo_rssi = r
        st.ultima_lectura_ms = int(instante_ms)

        if st.rssi_suavizado is None:
            st.rssi_suavizado = float(r)
        else:
            st.rssi_suavizado = st.rssi_suavizado * (1.0 - self._alpha) + float(r) * self._alpha

        # Ajuste suave de rango observado (evita que la barra se quede pegada)
        if r < st.rssi_min:
            st.rssi_min = r
        if r > st.rssi_max:
            st.rssi_max = r
        # Se mantiene un rango mínimo para que la barra no quede colapsada
        if st.rssi_max - st.rssi_min < 20:
            st.rssi_min = st.rssi_max - 20
        return st

    def nivel_porcentaje(self) -> int:
        st = self._estado
        if st is None or st.rssi_suavizado is None:
            return 0
        lo = float(st.rssi_min)
        hi = float(st.rssi_max)
        x = float(st.rssi_suavizado)
        if hi <= lo:
            return 0
        v = (x - lo) / (hi - lo)
        v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
        return int(round(v * 100.0))

    def texto_nivel(self) -> str:
        lvl = self.nivel_porcentaje()
        if lvl <= 10:
            return "Sin señal / muy lejos"
        if lvl <= 30:
            return "Alejado"
        if lvl <= 60:
            return "Acercándose"
        if lvl <= 85:
            return "Cerca"
        return "Muy cerca"
