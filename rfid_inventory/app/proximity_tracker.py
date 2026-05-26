"""Proximidad por RSSI para rastreo tipo 'frío/caliente'.

RSSI (Received Signal Strength Indicator) mide potencia recibida en dBm.
Valores más altos (más cercanos a 0) = señal más fuerte = en general más cerca del tag.
No es una regla de metros exactos: orientación del tag, metal, personas y multipath cambian la lectura.

Bandas orientativas para lector UHF tipo pistola (interior, potencia típica R200):
  >= -45 dBm   muy cerca (decenas de cm)
  -45 .. -55   cerca (~0,5–2 m)
  -55 .. -65   media (~2–5 m)
  -65 .. -75   lejos (~5–10 m)
  -75 .. -85   muy lejos o señal débil
  < -85        límite de lectura

En espacio libre ideal, ~6 dB menos ≈ el doble de distancia; en edificio la relación es mucho más irregular.
"""

from __future__ import annotations

from dataclasses import dataclass

# Umbrales absolutos (dBm) para texto orientativo en UI / informes.
_BANDAS_RSSI_DBM: tuple[tuple[float, str], ...] = (
    (-45.0, "Muy cerca (decenas de cm)"),
    (-55.0, "Cerca (~0,5–2 m)"),
    (-65.0, "Distancia media (~2–5 m)"),
    (-75.0, "Lejos (~5–10 m)"),
    (-85.0, "Muy lejos (>10 m o señal débil)"),
)


def banda_distancia_aproximada(rssi: int | float | None) -> str:
    """Clasificación cualitativa a partir del RSSI absoluto (no calibrada en metros reales)."""
    if rssi is None:
        return "Sin lectura"
    r = float(rssi)
    for umbral, etiqueta in _BANDAS_RSSI_DBM:
        if r >= umbral:
            return etiqueta
    return "Límite / casi sin señal"


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

    def texto_nivel_relativo(self) -> str:
        """Comparación con el rango RSSI visto en esta sesión (frío/caliente al moverse)."""
        lvl = self.nivel_porcentaje()
        if lvl <= 10:
            return "Señal débil en esta sesión"
        if lvl <= 30:
            return "Más lejos que antes"
        if lvl <= 60:
            return "Acercándose"
        if lvl <= 85:
            return "Cerca (vs. inicio)"
        return "Máxima señal en esta sesión"

    def texto_nivel(self) -> str:
        """Alias: prioriza banda absoluta si hay RSSI; si no, nivel relativo."""
        return self.texto_nivel_completo()

    def texto_nivel_completo(self) -> str:
        st = self._estado
        if st is None or st.rssi_suavizado is None:
            return "Sin señal"
        absol = banda_distancia_aproximada(st.rssi_suavizado)
        rel = self.texto_nivel_relativo()
        if st.ultimo_rssi is not None and absol != banda_distancia_aproximada(st.ultimo_rssi):
            return f"{absol} · {rel}"
        return absol
