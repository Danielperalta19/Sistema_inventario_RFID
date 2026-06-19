"""Indicador visual de cercanía (barras tipo señal WiFi)."""

from __future__ import annotations

import tkinter as tk


class BarrasSenal(tk.Frame):
    """Cuatro barras de altura creciente; `nivel` encendidas de 0 a 4."""

    _ALTURAS_PX = (10, 16, 22, 28)
    _ANCHO_COL = 13
    _ALTO_FILA = 32
    _COLOR_ON = "#2E7D32"
    _COLOR_OFF = "#BDBDBD"

    def __init__(self, master, numero: int = 4, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._numero = max(1, min(4, int(numero)))
        self._barras: list[tk.Frame] = []
        fila = tk.Frame(self)
        fila.pack(anchor="w")
        for i in range(self._numero):
            col = tk.Frame(fila, width=self._ANCHO_COL, height=self._ALTO_FILA)
            col.pack(side="left", padx=2)
            col.pack_propagate(False)
            bar = tk.Frame(col, bg=self._COLOR_OFF, height=self._ALTURAS_PX[i])
            bar.pack(side="bottom", fill="x")
            self._barras.append(bar)

    def establecer(self, nivel: int) -> None:
        n = max(0, min(self._numero, int(nivel)))
        for i, bar in enumerate(self._barras):
            bar.configure(bg=self._COLOR_ON if i < n else self._COLOR_OFF)
