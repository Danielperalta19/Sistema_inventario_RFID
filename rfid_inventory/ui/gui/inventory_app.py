"""Inventario por ubicación: esperados vs hallados."""

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from rfid_inventory.app import Scanner
from rfid_inventory.domain import compare_expected_found
from rfid_inventory.drivers import R200Driver, TagRead


def _mock_locations():
    """EPC de prueba (12 dígitos → hex), alineados con el emulador 75010000000x."""
    out = {}
    names = ["Lab A-101", "Lab A-102", "Bodega"]
    for i, name in enumerate(names):
        out[name] = []
        for j in range(3):
            n = 750100000000 + i * 3 + j
            digits = f"{n:012d}"
            out[name].append(digits.encode("ascii").hex())
    return out


class InventoryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Inventario RFID")
        self.geometry("880x520")

        self._driver = R200Driver()
        self._scanner = Scanner(self._driver)
        self._locations = _mock_locations()

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Puerto:").pack(side="left")
        self.port_var = tk.StringVar(value="COM5")
        tk.Entry(top, textvariable=self.port_var, width=12).pack(side="left", padx=(4, 10))

        tk.Label(top, text="Baud:").pack(side="left")
        self.baud_var = tk.StringVar(value="115200")
        tk.Entry(top, textvariable=self.baud_var, width=7).pack(side="left", padx=(4, 10))

        self.btn_connect = tk.Button(top, text="Conectar", command=self.connect)
        self.btn_connect.pack(side="left")
        self.btn_start = tk.Button(top, text="Escanear", command=self.start_scan, state="disabled")
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop = tk.Button(top, text="Detener", command=self.stop_scan, state="disabled")
        self.btn_stop.pack(side="left")

        tk.Label(top, text="Ubicación:").pack(side="left", padx=(12, 0))
        self.location_var = tk.StringVar(value=list(self._locations.keys())[0])
        self.location_combo = ttk.Combobox(
            top,
            textvariable=self.location_var,
            values=list(self._locations.keys()),
            state="readonly",
            width=14,
        )
        self.location_combo.pack(side="left", padx=(4, 0))
        self.location_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_expected_summary())

        body = tk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        left = tk.Frame(body)
        right = tk.Frame(body)
        body.add(left, stretch="always")
        body.add(right, stretch="always")

        tk.Label(left, text="Esperados").pack(anchor="w")
        self.expected_list = tk.Listbox(left, height=7)
        self.expected_list.pack(fill="x", pady=4)

        row = tk.Frame(left)
        row.pack(fill="x")
        self.new_epc_var = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.new_epc_var, width=26).pack(side="left", padx=(0, 6))
        tk.Button(row, text="Agregar", command=self.add_expected).pack(side="left")
        tk.Button(row, text="Quitar", command=self.remove_expected).pack(side="left", padx=4)

        tk.Label(
            left,
            text="Vistos al escanear (en vivo; se repiten si el lector re-lee el mismo tag)",
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        self.listbox = tk.Listbox(left, height=11, font=("Consolas", 9))
        self.listbox.pack(fill="both", expand=True, pady=4)

        tk.Label(right, text="Comparación").pack(anchor="w")
        self.tree = ttk.Treeview(
            right,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=18,
        )
        self.tree.heading("status", text="Estado")
        self.tree.heading("epc", text="EPC")
        self.tree.heading("rssi", text="RSSI")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("epc", width=300, anchor="w")
        self.tree.column("rssi", width=55, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=4)

        self.summary_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.summary_var, anchor="w", justify="left").pack(fill="x")

        self.status_var = tk.StringVar(value="Conecta el puerto y elige ubicación.")
        tk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._refresh_expected_summary()

    def connect(self):
        if self._driver.connected:
            messagebox.showinfo("Info", "Ya conectado.")
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("Error", "Indica el puerto (COM5, /dev/ttyUSB0, …).")
            return
        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Baud inválido.")
            return
        try:
            self._driver.connect(port, baud, debug=False)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.status_var.set(f"Conectado {port} @ {baud}")
        self.btn_connect.config(state="disabled")
        self.btn_start.config(state="normal")

    def start_scan(self):
        if self._scanner.is_running():
            return
        self._scanner.reset()
        self.listbox.delete(0, tk.END)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status_var.set("Escaneando… presiona Detener para terminar de escanear.")
        self._scanner.start(on_tag_read=self._on_tag_read)

    def stop_scan(self):
        self._scanner.stop()
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")
        self._compare_and_show()
        self.status_var.set("Listo.")

    def _on_tag_read(self, tag, idx_in_batch):
        # idx_in_batch: separar visualmente lecturas que llegan en el mismo bloque
        line = f"{tag.epc_hex}  RSSI={tag.rssi}"
        delay_ms = idx_in_batch * 45

        def append():
            self.listbox.insert(tk.END, line)
            self.listbox.see(tk.END)

        if delay_ms <= 0:
            self.after(0, append)
        else:
            self.after(delay_ms, append)

    def _compare_and_show(self):
        loc = self.location_var.get()
        expected = set(self._locations.get(loc, []))
        snap = self._scanner.snapshot()
        found = set(snap["seen_epcs"])
        r = compare_expected_found(expected, found)

        for item in self.tree.get_children():
            self.tree.delete(item)
        for epc in r.encontrados:
            self.tree.insert("", tk.END, values=("ENCONTRADO", epc, snap["last_rssi"].get(epc, "")))
        for epc in r.faltantes:
            self.tree.insert("", tk.END, values=("NO ESCANEADO", epc, ""))
        for epc in r.nuevos:
            self.tree.insert("", tk.END, values=("ACTIVO NUEVO", epc, snap["last_rssi"].get(epc, "")))

        self.summary_var.set(
            f"{loc}: esperados {len(expected)} | ok {len(r.encontrados)} | "
            f"faltan {len(r.faltantes)} | nuevos {len(r.nuevos)}"
        )

    def _refresh_expected_summary(self):
        loc = self.location_var.get()
        exp = self._locations.get(loc, [])
        self.expected_list.delete(0, tk.END)
        for epc in exp:
            self.expected_list.insert(tk.END, epc)
        self.summary_var.set(f"{loc}: {len(exp)} esperados")

    def _normalize_epc(self, s):
        s = s.strip().lower().replace("0x", "")
        for ch in " \t\n\r,;_-":
            s = s.replace(ch, "")
        if not s:
            return None
        if len(s) == 12 and s.isdigit():
            return s.encode("ascii").hex()
        if len(s) != 24:
            return None
        if any(c not in "0123456789abcdef" for c in s):
            return None
        return s

    def add_expected(self):
        loc = self.location_var.get()
        epc = self._normalize_epc(self.new_epc_var.get())
        if epc is None:
            messagebox.showerror("EPC", "24 hex (12 bytes) o 12 dígitos.")
            return
        cur = self._locations.setdefault(loc, [])
        if epc in cur:
            messagebox.showinfo("Info", "No se pueden agregar EPC's repetidos.")
            return
        cur.append(epc)
        self.new_epc_var.set("")
        self._refresh_expected_summary()

    def remove_expected(self):
        loc = self.location_var.get()
        cur = self._locations.get(loc, [])
        sel = self.expected_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(cur):
            cur.pop(idx)
        self._refresh_expected_summary()

    def on_close(self):
        try:
            self._scanner.stop()
            self._driver.close()
        finally:
            self.destroy()


def main():
    InventoryApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
