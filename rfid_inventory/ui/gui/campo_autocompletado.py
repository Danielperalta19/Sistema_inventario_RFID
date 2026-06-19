"""Campo de texto con sugerencias debajo (estilo buscador / YouTube)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class CampoAutocompletado(tk.Frame):
    """Entry + lista de coincidencias que se actualiza al escribir."""

    _MAX_MOSTRADAS = 50

    def __init__(
        self,
        master,
        *,
        textvariable: tk.StringVar | None = None,
        opciones: list[str] | None = None,
        al_cambiar: Callable[[], None] | None = None,
        max_visible: int = 5,
        font=("", 10),
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._al_cambiar = al_cambiar
        self._max_visible = max(1, max_visible)
        self._var = textvariable if textvariable is not None else tk.StringVar()
        self._opciones_completas = self._normalizar_opciones(opciones or [])
        self._lista_visible = False
        self._tarea_ocultar: str | None = None
        self._menu_suprimido = False
        self._ultimo_valor_confirmado: str | None = None

        self._entrada = ttk.Entry(self, textvariable=self._var, font=font)
        self._entrada._campo_autocompletado = self  # noqa: SLF001 — para teclado virtual
        self._entrada.pack(fill="x")

        self._panel = tk.Frame(self, highlightbackground="#a8afb9", highlightthickness=1)
        self._listbox = tk.Listbox(
            self._panel,
            font=font,
            activestyle="none",
            selectbackground="#4a90d9",
            selectforeground="white",
            exportselection=False,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self._listbox._campo_autocompletado = self  # noqa: SLF001
        self._listbox.pack(fill="both", expand=True)

        self._entrada.bind("<KeyRelease>", self._al_escribir, add="+")
        self._entrada.bind("<FocusIn>", self._al_foco_entrada, add="+")
        self._entrada.bind("<FocusOut>", self._programar_ocultar, add="+")
        self._listbox.bind("<ButtonRelease-1>", self._al_elegir_lista, add="+")
        self._listbox.bind("<FocusOut>", self._programar_ocultar, add="+")

    @property
    def entrada(self) -> ttk.Entry:
        return self._entrada

    @property
    def opciones_completas(self) -> list[str]:
        return list(self._opciones_completas)

    @staticmethod
    def _normalizar_opciones(opciones: list[str]) -> list[str]:
        return sorted({str(o).strip() for o in opciones if str(o).strip()})

    def valor_valido(self) -> str | None:
        """Texto actual solo si coincide exactamente con una opción del catálogo."""
        texto = (self._var.get() or "").strip()
        if texto in self._opciones_completas:
            return texto
        return None

    def habilitar(self, activo: bool) -> None:
        if activo:
            self._entrada.state(["!disabled"])
        else:
            self._entrada.state(["disabled"])
            self._limpiar_confirmacion()
            self._var.set("")
            self._ocultar_lista()

    def actualizar_opciones(self, opciones: list[str]) -> None:
        self._opciones_completas = self._normalizar_opciones(opciones)
        confirmado = self.valor_valido()
        if confirmado is not None:
            self._ultimo_valor_confirmado = confirmado
            self._menu_suprimido = True
        elif self._ultimo_valor_confirmado not in self._opciones_completas:
            self._limpiar_confirmacion()
        if self._foco_en_campo() and not self._menu_suprimido:
            self._refrescar_sugerencias()
        else:
            self._ocultar_lista()

    def reiniciar(self) -> None:
        self._var.set("")
        self._limpiar_confirmacion()
        self._ocultar_lista()

    def _limpiar_confirmacion(self) -> None:
        self._menu_suprimido = False
        self._ultimo_valor_confirmado = None

    def _texto_actual(self) -> str:
        return (self._var.get() or "").strip()

    def _fijar_valor_confirmado(self, valor: str) -> None:
        self._var.set(valor)
        self._ultimo_valor_confirmado = valor
        self._menu_suprimido = True
        self._ocultar_lista()
        self._cursor_al_final()

    def _cursor_al_final(self) -> None:
        self.update_idletasks()
        try:
            self._entrada.icursor(tk.END)
            self._entrada.xview_moveto(1.0)
        except tk.TclError:
            pass

    def _filtrar(self) -> list[str]:
        texto = self._texto_actual().lower()
        if not texto:
            return self._opciones_completas
        return [o for o in self._opciones_completas if texto in o.lower()]

    def _menu_debe_estar_oculto(self) -> bool:
        if not self._menu_suprimido:
            return False
        return self._texto_actual() == (self._ultimo_valor_confirmado or "")

    def _al_foco_entrada(self, _event=None) -> None:
        if self._tarea_ocultar is not None:
            try:
                self.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
            self._tarea_ocultar = None
        if self._menu_debe_estar_oculto():
            return
        self._refrescar_sugerencias()

    def _al_escribir(self, event=None) -> None:
        if event is not None and event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        if not self._foco_en_campo():
            return
        if self._menu_suprimido and self._texto_actual() != (self._ultimo_valor_confirmado or ""):
            self._limpiar_confirmacion()
        self._refrescar_sugerencias()

    def _refrescar_sugerencias(self) -> None:
        if self._tarea_ocultar is not None:
            try:
                self.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
            self._tarea_ocultar = None
        if not self._foco_en_campo() or self._menu_debe_estar_oculto():
            self._ocultar_lista()
            return
        filtradas = self._filtrar()
        if not filtradas:
            self._ocultar_lista()
            return
        self._listbox.delete(0, tk.END)
        for opcion in filtradas[: self._MAX_MOSTRADAS]:
            self._listbox.insert(tk.END, opcion)
        filas = min(len(filtradas), self._max_visible)
        self._listbox.configure(height=filas)
        if not self._lista_visible:
            self._panel.pack(fill="x", pady=(2, 0))
            self._lista_visible = True

    def _ocultar_lista(self) -> None:
        if self._lista_visible:
            self._panel.pack_forget()
            self._lista_visible = False

    def _programar_ocultar(self, _event=None) -> None:
        if self._tarea_ocultar is not None:
            try:
                self.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
        self._tarea_ocultar = self.after(200, self._ocultar_si_foco_fuera)

    def _foco_en_campo(self) -> bool:
        try:
            w = self.focus_get()
        except (tk.TclError, KeyError):
            return False
        if w is None:
            return False
        return w in (self._entrada, self._listbox) or self._es_descendiente(w, self._panel)

    @staticmethod
    def _es_descendiente(widget, ancestro) -> bool:
        nodo = widget
        while nodo is not None:
            if nodo == ancestro:
                return True
            try:
                nodo = nodo.master
            except (tk.TclError, AttributeError):
                break
        return False

    def _ocultar_si_foco_fuera(self) -> None:
        self._tarea_ocultar = None
        if self._foco_en_campo():
            return
        self._ocultar_lista()

    def _al_elegir_lista(self, _event=None) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        valor = self._listbox.get(sel[0])
        self._fijar_valor_confirmado(valor)
        try:
            self._entrada.focus_set()
        except tk.TclError:
            pass
        self._cursor_al_final()
        if self._al_cambiar is not None:
            self._al_cambiar()
