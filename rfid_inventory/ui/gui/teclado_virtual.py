"""Teclado en pantalla QWERTY ."""

import tkinter as tk


class TecladoVirtual(tk.Frame):

    _FILAS_QWERTY = (
        "1234567890",
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM",
    )
    _PASOS_ANIM = 14
    _MS_ANIM = 200
    _COLOR_FONDO = "#d1d5db"
    _COLOR_TECLA = "#ffffff"
    _COLOR_TECLA_ACT = "#c7ccd4"
    _COLOR_TECLA_FN = "#b8bec8"
    _COLOR_BORDE = "#a8afb9"

    def __init__(self, master, **kwargs):
        self._clip = tk.Frame(master, height=0, bg=self._COLOR_FONDO, highlightthickness=0)
        self._clip.pack(side="bottom", fill="x")
        self._clip.pack_propagate(False)

        super().__init__(self._clip, bg=self._COLOR_FONDO, highlightthickness=0, **kwargs)
        self.pack(side="bottom", fill="x")

        self._entrada = None
        self._ventana: tk.Misc | None = None
        self._tarea_ocultar = None
        self._altura_objetivo = 0
        self._paso_anim = 0
        self._tarea_anim = None
        self._ocultando = False

        self._construir_teclas()

    def _construir_teclas(self) -> None:
        cuerpo = tk.Frame(self, bg=self._COLOR_FONDO, padx=3, pady=3)
        cuerpo.pack(fill="x")

        for idx, fila_texto in enumerate(self._FILAS_QWERTY):
            fila = tk.Frame(cuerpo, bg=self._COLOR_FONDO)
            fila.pack(fill="x", pady=1)
            margen = 14 if idx == 2 else (22 if idx == 3 else 0)
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
        """Muestra/oculta el teclado al entrar o salir de Entry/Text en ``ventana``."""
        self._ventana = ventana
        for clase in ("Entry", "Text", "TEntry"):
            ventana.bind_class(clase, "<FocusIn>", self._al_foco, add="+")
            ventana.bind_class(clase, "<FocusOut>", self._al_perder_foco, add="+")

    @staticmethod
    def _widget_es_campo_texto(w) -> bool:
        if w is None:
            return False
        try:
            return w.winfo_class() in ("Entry", "Text", "TEntry")
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
                self.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
            self._tarea_ocultar = None
        w = getattr(event, "widget", None)
        if not self._widget_es_campo_texto(w):
            return
        self.enlazar(w)
        self.mostrar()

    def _al_perder_foco(self, _event=None) -> None:
        if self._tarea_ocultar is not None:
            try:
                self.after_cancel(self._tarea_ocultar)
            except Exception:
                pass
        self._tarea_ocultar = self.after(250, self._ocultar_si_aplica)

    def _ocultar_si_aplica(self) -> None:
        self._tarea_ocultar = None
        ventana = self._ventana or self.winfo_toplevel()
        w = ventana.focus_get()
        if self._es_descendiente_de(w, self) or self._es_descendiente_de(w, self._clip):
            return
        if self._widget_es_campo_texto(w):
            return
        self.ocultar()

    def mostrar(self) -> None:
        if self._tarea_anim is not None:
            try:
                self.after_cancel(self._tarea_anim)
            except Exception:
                pass
            self._tarea_anim = None
        if self._clip.winfo_ismapped() and not self._ocultando:
            self.update_idletasks()
            if self._clip.winfo_height() >= max(self._altura_objetivo, 100):
                return
        self._ocultando = False
        if not self._clip.winfo_ismapped():
            self._clip.pack(side="bottom", fill="x")
        self.update_idletasks()
        self._altura_objetivo = max(self.winfo_reqheight(), 118)
        self._paso_anim = 0
        self._animar_altura(0, self._altura_objetivo, mostrando=True)

    def ocultar(self, rapido: bool = False) -> None:
        if not self._clip.winfo_ismapped():
            return
        if self._tarea_anim is not None:
            try:
                self.after_cancel(self._tarea_anim)
            except Exception:
                pass
            self._tarea_anim = None
        if rapido:
            self._finalizar_ocultar()
            return
        self._ocultando = True
        actual = self._clip.winfo_height()
        if actual <= 0:
            self._finalizar_ocultar()
            return
        self._altura_objetivo = actual
        self._paso_anim = 0
        self._animar_altura(actual, 0, mostrando=False)

    def visible(self) -> bool:
        return self._clip.winfo_ismapped() and self._clip.winfo_height() > 4

    def _ease_out_cubic(self, t: float) -> float:
        return 1.0 - (1.0 - t) ** 3

    def _animar_altura(self, desde: int, hasta: int, *, mostrando: bool) -> None:
        self._paso_anim += 1
        t = min(1.0, self._paso_anim / self._PASOS_ANIM)
        t = self._ease_out_cubic(t)
        altura = int(desde + (hasta - desde) * t)
        self._clip.configure(height=max(0, altura))

        if self._paso_anim < self._PASOS_ANIM:
            self._tarea_anim = self.after(
                max(1, self._MS_ANIM // self._PASOS_ANIM),
                lambda: self._animar_altura(desde, hasta, mostrando=mostrando),
            )
            return

        self._tarea_anim = None
        self._clip.configure(height=max(0, hasta))
        if not mostrando or self._ocultando:
            self._finalizar_ocultar()

    def _finalizar_ocultar(self) -> None:
        self._ocultando = False
        self._clip.configure(height=0)
        self._clip.pack_forget()

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
    """Prueba aislada: python -m rfid_inventory.ui.gui.teclado_virtual"""
    root = tk.Tk()
    root.title("Teclado virtual")
    root.geometry("480x320")
    root.minsize(480, 320)

    marco = tk.Frame(root)
    marco.pack(fill="both", expand=True, padx=12, pady=12)
    tk.Label(marco, text="Toca el campo:").pack(anchor="w")
    tk.Entry(marco, font=("", 11)).pack(fill="x", pady=8)

    teclado = TecladoVirtual(root)
    teclado.instalar_en(root)
    root.mainloop()


if __name__ == "__main__":
    _demo()
