"""Teclado en pantalla QWERTY (superposición, no redimensiona el contenido)."""

from __future__ import annotations

import tkinter as tk


class TecladoVirtual:
    """Panel flotante sobre la ventana (~50 % inferior), sin ``pack`` en el contenedor principal."""

    _FILAS_QWERTY = (
        "1234567890",
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM",
    )
    _FRACCION_ALTURA = 0.5
    _ALTURA_MIN = 100
    _COLOR_FONDO = "#d1d5db"
    _COLOR_TECLA = "#ffffff"
    _COLOR_TECLA_ACT = "#c7ccd4"
    _COLOR_TECLA_FN = "#b8bec8"
    _COLOR_BORDE = "#a8afb9"

    def __init__(self, root: tk.Misc) -> None:
        self._root = root.winfo_toplevel()
        self._entrada: tk.Widget | None = None
        self._tarea_ocultar: str | None = None
        self._visible = False

        self._panel = tk.Frame(
            self._root,
            bg=self._COLOR_FONDO,
            highlightthickness=2,
            highlightbackground=self._COLOR_BORDE,
        )
        cuerpo = tk.Frame(self._panel, bg=self._COLOR_FONDO, padx=3, pady=2)
        cuerpo.pack(fill="both", expand=True)
        self._construir_teclas(cuerpo)

        self._root.bind("<Configure>", self._al_redimensionar, add="+")

    def _construir_teclas(self, cuerpo: tk.Frame) -> None:
        for idx, fila_texto in enumerate(self._FILAS_QWERTY):
            fila = tk.Frame(cuerpo, bg=self._COLOR_FONDO)
            fila.pack(fill="x", pady=1)
            margen = 12 if idx == 2 else (18 if idx == 3 else 0)
            if margen:
                tk.Frame(fila, width=margen, bg=self._COLOR_FONDO).pack(side="left")
            for letra in fila_texto:
                self._boton_tecla(fila, letra).pack(side="left", padx=1, expand=True, fill="x")

        fila_fn = tk.Frame(cuerpo, bg=self._COLOR_FONDO)
        fila_fn.pack(fill="x", pady=(2, 0))
        self._boton_tecla(fila_fn, "⌫", ancho=4, comando=self._borrar, fondo=self._COLOR_TECLA_FN).pack(
            side="left", padx=1, ipadx=2
        )
        self._boton_tecla(fila_fn, "/", ancho=2).pack(side="left", padx=1)
        self._boton_tecla(fila_fn, ".", ancho=2).pack(side="left", padx=1)
        self._boton_tecla(fila_fn, "-", ancho=2).pack(side="left", padx=1)
        self._boton_tecla(fila_fn, " ", texto="ESPACIO", ancho=2).pack(
            side="left", padx=1, expand=True, fill="x", ipadx=4
        )
        self._boton_tecla(
            fila_fn,
            "▼",
            ancho=3,
            comando=lambda: self.ocultar(),
            fondo=self._COLOR_TECLA_FN,
        ).pack(side="left", padx=1, ipadx=2)

    def _boton_tecla(
        self,
        parent,
        tecla: str,
        *,
        texto: str | None = None,
        ancho: int = 2,
        comando=None,
        fondo: str | None = None,
    ) -> tk.Button:
        etiqueta = texto if texto is not None else tecla
        cmd = comando if comando is not None else (lambda c=tecla: self._insertar(c))
        fondo = fondo or self._COLOR_TECLA
        return tk.Button(
            parent,
            text=etiqueta,
            width=ancho,
            height=1,
            font=("", 9),
            relief="flat",
            bd=0,
            bg=fondo,
            activebackground=self._COLOR_TECLA_ACT,
            highlightthickness=1,
            highlightbackground=self._COLOR_BORDE,
            takefocus=False,
            command=cmd,
        )

    def enlazar(self, entrada: tk.Widget) -> None:
        self._entrada = entrada

    def instalar_en(self, ventana: tk.Misc) -> None:
        for clase in ("Entry", "Text", "TEntry", "TCombobox"):
            ventana.bind_class(clase, "<FocusIn>", self._al_foco, add="+")
            ventana.bind_class(clase, "<FocusOut>", self._al_perder_foco, add="+")

    @staticmethod
    def _widget_es_campo_texto(w) -> bool:
        if w is None:
            return False
        if getattr(w, "_campo_autocompletado", None) is not None:
            return True
        try:
            return w.winfo_class() in ("Entry", "Text", "TEntry", "TCombobox")
        except tk.TclError:
            return False

    @staticmethod
    def _es_descendiente_de(widget, ancestro) -> bool:
        w = widget
        while w is not None:
            if w == ancestro:
                return True
            try:
                w = w.master
            except (tk.TclError, AttributeError):
                break
        return False

    def _al_foco(self, event) -> None:
        if self._tarea_ocultar is not None:
            try:
                self._root.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
            self._tarea_ocultar = None
        w = getattr(event, "widget", None)
        if not self._widget_es_campo_texto(w):
            return
        campo = getattr(w, "_campo_autocompletado", None)
        if campo is not None:
            w = campo.entrada
        self.enlazar(w)
        self.mostrar()

    def _al_perder_foco(self, _event=None) -> None:
        if self._tarea_ocultar is not None:
            try:
                self._root.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
        self._tarea_ocultar = self._root.after(250, self._ocultar_si_aplica)

    @staticmethod
    def _focus_seguro(ventana: tk.Misc):
        try:
            return ventana.focus_get()
        except (tk.TclError, KeyError):
            return None

    def _ocultar_si_aplica(self) -> None:
        self._tarea_ocultar = None
        w = self._focus_seguro(self._root)
        if w is None:
            return
        if self._es_descendiente_de(w, self._panel):
            return
        if self._widget_es_campo_texto(w):
            return
        self.ocultar()

    def _al_redimensionar(self, _event=None) -> None:
        if self._visible:
            self._reposicionar()

    def _altura_panel(self, alto_cliente: int) -> int:
        """Altura del teclado: ~50 % del área cliente, sin pasarse del contenido."""
        alto_cliente = max(alto_cliente, 1)
        self._panel.update_idletasks()
        natural = max(self._panel.winfo_reqheight(), self._ALTURA_MIN)
        por_fraccion = int(alto_cliente * self._FRACCION_ALTURA)
        return max(self._ALTURA_MIN, min(natural, por_fraccion, alto_cliente - 2))

    def _reposicionar(self) -> None:
        self._root.update_idletasks()
        w = max(self._root.winfo_width(), 1)
        h = max(self._root.winfo_height(), 1)
        kh = self._altura_panel(h)
        # Anclar al borde inferior del área cliente (no calcular y a mano).
        self._panel.place(relx=0.0, rely=1.0, x=0, y=0, anchor="sw", relwidth=1.0, height=kh)
        self._panel.lift()

    def mostrar(self) -> None:
        if self._visible:
            self._reposicionar()
            self._panel.lift()
            return
        self._reposicionar()
        self._panel.lift()
        self._visible = True

    def ocultar(self, rapido: bool = False) -> None:
        del rapido
        if not self._visible:
            return
        self._panel.place_forget()
        self._visible = False

    def visible(self) -> bool:
        return self._visible

    def _es_campo_texto(self) -> bool:
        if self._entrada is None:
            return False
        try:
            return self._entrada.winfo_class() in ("Entry", "Text", "TEntry")
        except tk.TclError:
            return False

    def _enfocar_entrada(self) -> None:
        if self._entrada is None:
            return
        try:
            self._entrada.focus_set()
        except tk.TclError:
            pass

    def _tiene_seleccion(self) -> bool:
        try:
            if self._entrada.winfo_class() == "Text":
                return bool(self._entrada.tag_ranges(tk.SEL))
            return bool(self._entrada.selection_present())
        except tk.TclError:
            return False

    def _insertar(self, texto: str) -> None:
        if not self._es_campo_texto():
            return
        self._enfocar_entrada()
        try:
            if self._tiene_seleccion():
                self._entrada.delete(tk.SEL_FIRST, tk.SEL_LAST)
            self._entrada.insert(tk.INSERT, texto)
            self._entrada.icursor(tk.INSERT)
        except tk.TclError:
            pass

    def _borrar(self) -> None:
        if not self._es_campo_texto():
            return
        self._enfocar_entrada()
        try:
            if self._tiene_seleccion():
                self._entrada.delete(tk.SEL_FIRST, tk.SEL_LAST)
                return
            clase = self._entrada.winfo_class()
            if clase == "Text":
                if self._entrada.compare("insert", ">", "1.0"):
                    self._entrada.delete("insert-1c", "insert")
            else:
                pos = int(self._entrada.index(tk.INSERT))
                if pos > 0:
                    self._entrada.delete(pos - 1, pos)
            self._entrada.icursor(tk.INSERT)
        except tk.TclError:
            pass


def _demo() -> None:
    root = tk.Tk()
    root.title("Teclado virtual")
    root.geometry("480x320")
    root.minsize(480, 320)
    root.maxsize(480, 320)

    marco = tk.Frame(root)
    marco.pack(fill="both", expand=True, padx=8, pady=8)
    tk.Label(marco, text="Toca el campo (el teclado se superpone):").pack(anchor="w")
    tk.Entry(marco, font=("", 10)).pack(fill="x", pady=8)

    teclado = TecladoVirtual(root)
    teclado.instalar_en(root)
    root.mainloop()


if __name__ == "__main__":
    _demo()
