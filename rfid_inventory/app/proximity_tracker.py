"""Proximidad por RSSI para rastreo tipo 'frío/caliente'."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProximityState:
    target_epc: str
    last_rssi: int | None = None
    ema_rssi: float | None = None
    last_seen_ms: int | None = None
    # Auto-rango observado para mapear a barra (se ajusta sobre la marcha)
    min_rssi: int = -90
    max_rssi: int = -35


class ProximityTracker:
    """Convierte RSSI en un nivel 0..100 con suavizado."""

    def __init__(self, alpha: float = 0.25):
        self._alpha = max(0.05, min(0.8, float(alpha)))
        self._state: ProximityState | None = None

    def reset(self, target_epc_hex: str):
        epc = (target_epc_hex or "").strip().lower()
        self._state = ProximityState(target_epc=epc)

    @property
    def state(self) -> ProximityState | None:
        return self._state

    def update(self, rssi: int, now_ms: int) -> ProximityState | None:
        st = self._state
        if st is None:
            return None
        r = int(rssi)
        st.last_rssi = r
        st.last_seen_ms = int(now_ms)

        if st.ema_rssi is None:
            st.ema_rssi = float(r)
        else:
            st.ema_rssi = st.ema_rssi * (1.0 - self._alpha) + float(r) * self._alpha

        # Ajuste suave de rango observado (evita que la barra se quede pegada)
        if r < st.min_rssi:
            st.min_rssi = r
        if r > st.max_rssi:
            st.max_rssi = r
        # Se mantiene un rango minimo
        if st.max_rssi - st.min_rssi < 20:
            st.min_rssi = st.max_rssi - 20
        return st

    def level_0_100(self) -> int:
        st = self._state
        if st is None or st.ema_rssi is None:
            return 0
        lo = float(st.min_rssi)
        hi = float(st.max_rssi)
        x = float(st.ema_rssi)
        if hi <= lo:
            return 0
        v = (x - lo) / (hi - lo)
        v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
        return int(round(v * 100.0))

    def label(self) -> str:
        lvl = self.level_0_100()
        if lvl <= 10:
            return "Sin señal / muy lejos"
        if lvl <= 30:
            return "Alejado"
        if lvl <= 60:
            return "Acercandose"
        if lvl <= 85:
            return "Cerca"
        return "Muy cerca"

