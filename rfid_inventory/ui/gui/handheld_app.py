import os
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import json
import datetime
import random

from rfid_inventory.app import Scanner
from rfid_inventory.app.inventory_presenter import build_result_rows
from rfid_inventory.app.inventory_service import InventoryService
from rfid_inventory.app.proximity_tracker import ProximityTracker
from rfid_inventory.app.tag_writer_service import TagWriterService
from rfid_inventory.app.tracking_service import TrackingService
from rfid_inventory.catalog.catalog_loader import default_catalog_paths, flatten_locations, load_locations_nested_from_json
from rfid_inventory.catalog.epc12_codec import asset_code_to_epc12_hex
from rfid_inventory.catalog.epc12_codec import epc12_hex_to_asset_code
from rfid_inventory.drivers import R200Driver
from rfid_inventory.ui.ui_formatters import asset_code_or_dash, asset_display_from_epc, write_status_programmed


def _mock_locations_nested():
    """Fallback si no existen los JSON: edificio -> sala -> lista de EPC (hex)."""
    pairs = [
        ("Edificio Central", "Lab A-101"),
        ("Edificio Central", "Lab A-102"),
        ("Edificio Norte", "Cubículo 301"),
        ("Edificio Norte", "Sala B"),
    ]
    out = {}
    for idx, (edif, sala) in enumerate(pairs):
        if edif not in out:
            out[edif] = {}
        epcs = []
        for j in range(3):
            n = 750100000000 + idx * 3 + j
            digits = f"{n:012d}"
            epcs.append(digits.encode("ascii").hex())
        out[edif][sala] = epcs
    return out


def _location_label(edificio, sala):
    return "{0} · {1}".format(edificio, sala)


class HandheldApp(tk.Tk):
    _LOG_MAX_LINES = 4

    def __init__(self):
        super().__init__()
        self.title("Inventario RFID")
        self.geometry("480x320")
        self.minsize(480, 320)

        self._scan_started_ms = None
        self._scan_timer_job = None
        self._pistol_start_job = None
        self._expected_set = set()
        self._recent_log = []
        self._tree_expected_items = {}
        self._tree_new_items = {}

        self._result_location = ""
        self._result_rows = []
        self._result_iid_to_epc = {}
        self._last_snap = None
        self._filter_mode = tk.StringVar(value="todos")

        self._driver = R200Driver()
        self._scanner = Scanner(self._driver)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        cat_paths = default_catalog_paths(repo_root)
        self._nested_locations = load_locations_nested_from_json(cat_paths) or _mock_locations_nested()
        self._locations = flatten_locations(self._nested_locations)
        self._inventory = InventoryService(self._locations, self._scanner)

        self._tracking = TrackingService(self._nested_locations)
        self._prox = ProximityTracker(alpha=0.25)
        self._tag_writer = TagWriterService()
        self._prox_running = False
        self._prox_ui_job = None
        # Modo demostrativo: forzar simulación aunque haya lector conectado.
        # Cuando tengas el lector real, cambia a False para usar RSSI real del tag objetivo.
        self._prox_force_sim = True

        self._init_style()

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self._frame_menu = None
        self._frame_start = None
        self._frame_connect = None
        self._frame_setup = None
        self._frame_scan = None
        self._frame_result = None
        self._frame_detail = None
        self._frame_rastreo = None
        self._frame_escritura = None
        self._frame_hid = None

        # A dónde avanzar después de conectar (menu o setup)
        self._connect_next = "menu"

        self._build_start()
        self._build_menu()
        self._build_connect()
        self._build_setup()
        self._build_scan()
        self._build_result()
        self._build_detail()
        self._build_rastreo()
        self._build_escritura()
        self._build_hid()

        self._show_frame("start")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _hid_enable_advertising_and_open(self):
        """Activa advertising BLE (btmgmt) y abre la pantalla HID.

        Se ejecuta en background para no congelar la UI.
        Requiere sudoers NOPASSWD para el usuario (ej. `user`).
        """
        # Entra a la pantalla sí o sí (aunque estemos en Windows / sin BT).
        self._show_frame("hid")

        # Solo intentamos ejecutar btmgmt en Linux.
        if os.name != "posix":
            return

        def worker():
            btmgmt = shutil.which("btmgmt") or "/usr/bin/btmgmt"
            cmd = ["sudo", "-n", btmgmt, "-i", "hci0", "advertising", "on"]
            try:
                p = subprocess.run(cmd, text=True, capture_output=True)
            except Exception as e:
                self.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Bluetooth",
                        "No pude ejecutar btmgmt desde la app.\n\n"
                        f"Comando: {' '.join(cmd)}\n"
                        f"Error: {e}",
                    ),
                )
                return

            if p.returncode != 0:
                self.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Bluetooth",
                        "Falló activar advertising.\n\n"
                        f"Comando: {' '.join(cmd)}\n"
                        f"Exit: {p.returncode}\n\n"
                        f"STDOUT:\n{(p.stdout or '').strip()}\n\n"
                        f"STDERR:\n{(p.stderr or '').strip()}",
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _suggest_pi_serial_port(self) -> str:
        """Devuelve un puerto serial estable para Raspberry Pi (si existe).

        Preferimos `/dev/serial/by-id/*` para evitar que cambie ttyUSB0/ttyUSB1.
        """
        if os.name != "posix":
            return ""
        try:
            by_id = "/dev/serial/by-id"
            if os.path.isdir(by_id):
                entries = sorted(os.listdir(by_id))
                for name in entries:
                    p = os.path.join(by_id, name)
                    if os.path.islink(p) or os.path.exists(p):
                        return p
            # fallback: ttyUSB*, luego ttyACM*
            for i in range(0, 6):
                p = f"/dev/ttyUSB{i}"
                if os.path.exists(p):
                    return p
            for i in range(0, 6):
                p = f"/dev/ttyACM{i}"
                if os.path.exists(p):
                    return p
        except Exception:
            pass
        return ""

    def _location_key(self):
        return _location_label(self.building_var.get(), self.room_var.get())

    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        # Ajuste compacto para 480×320 (Waveshare): balance legibilidad/espacio.
        style.configure("Treeview", rowheight=18)
        style.configure("Treeview.Heading", font=("", 8, "bold"))
        style.configure("Handheld.TButton", font=("", 10))
        style.configure("HandheldBig.TButton", font=("", 12))

    def _show_frame(self, name):
        for w in self.container.winfo_children():
            w.pack_forget()
        if name == "start":
            self._frame_start.pack(fill="both", expand=True)
        elif name == "menu":
            self._frame_menu.pack(fill="both", expand=True)
        elif name == "connect":
            self._frame_connect.pack(fill="both", expand=True)
        elif name == "setup":
            self._frame_setup.pack(fill="both", expand=True)
        elif name == "scan":
            self._frame_scan.pack(fill="both", expand=True)
        elif name == "result":
            self._frame_result.pack(fill="both", expand=True)
        elif name == "detail":
            self._frame_detail.pack(fill="both", expand=True)
        elif name == "rastreo":
            self._frame_rastreo.pack(fill="both", expand=True)
        elif name == "escritura":
            self._frame_escritura.pack(fill="both", expand=True)
        elif name == "hid":
            self._frame_hid.pack(fill="both", expand=True)

    def _build_start(self):
        self._frame_start = tk.Frame(self.container)

        tk.Label(
            self._frame_start,
            text="Sistema de Inventario RFID",
            font=("", 15, "bold"),
        ).pack(pady=(28, 6))

        tk.Label(
            self._frame_start,
            text="Pantalla 480×320 · Raspberry Pi",
            font=("", 8),
            fg="#555",
        ).pack(pady=(0, 14))

        ttk.Button(
            self._frame_start,
            text="Iniciar",
            style="HandheldBig.TButton",
            command=lambda: self._enter_connect(next_frame="menu"),
        ).pack(fill="x", padx=28, ipady=6)

    def _build_menu(self):
        self._frame_menu = tk.Frame(self.container)

        tk.Label(
            self._frame_menu,
            text="Sistema de Inventario RFID",
            font=("", 14, "bold"),
        ).pack(pady=(6, 2))
        tk.Label(
            self._frame_menu,
            text="Elige una opción",
            font=("", 8),
            fg="#555",
        ).pack(pady=(0, 6))

        def big(parent, text, command):
            b = ttk.Button(
                parent,
                text=text,
                style="HandheldBig.TButton",
                command=command,
            )
            b.pack(fill="x", padx=14, pady=3, ipady=4)
            return b

        big(
            self._frame_menu,
            "Inventario en ubicación",
            self._enter_inventory,
        )
        big(
            self._frame_menu,
            "Rastrear activo",
            self._enter_rastreo,
        )
        big(
            self._frame_menu,
            "Escribir etiqueta",
            lambda: self._show_frame("escritura"),
        )
        big(
            self._frame_menu,
            "Modo Lector Bluetooth",
            self._hid_enable_advertising_and_open,
        )

    def _build_connect(self):
        """Lector serial: conectar y seguir a selección de ubicación (flujograma: inventario del lugar)."""
        self._frame_connect = tk.Frame(self.container)

        ttk.Button(
            self._frame_connect,
            text="Inicio",
            style="Handheld.TButton",
            command=lambda: self._show_frame("start"),
        ).pack(anchor="w", padx=8, pady=(4, 0))

        tk.Label(
            self._frame_connect,
            text="Inventario en ubicación",
            font=("", 13, "bold"),
        ).pack(pady=(3, 2))

        tk.Label(
            self._frame_connect,
            text="Conecta el lector RFID al puerto",
            font=("", 8),
            wraplength=440,
            justify="center",
        ).pack(pady=(0, 6))

        row = tk.Frame(self._frame_connect)
        row.pack(fill="x", padx=12, pady=3)

        tk.Label(row, text="Puerto:", font=("", 10)).pack(side="left")
        # Default: si estamos en Pi, sugiere /dev/serial/by-id; si no, COM5.
        default_port = self._suggest_pi_serial_port() if os.name == "posix" else "COM5"
        self.port_var = tk.StringVar(value=default_port or ("COM5" if os.name != "posix" else "/dev/ttyUSB0"))
        tk.Entry(row, textvariable=self.port_var, width=20, font=("", 10)).pack(side="left", padx=(4, 6))

        def set_windows_port():
            self.port_var.set("COM5")

        def set_pi_port():
            p = self._suggest_pi_serial_port()
            if p:
                self.port_var.set(p)
            else:
                self.port_var.set("/dev/ttyUSB0")

        ttk.Button(row, text="Windows", style="Handheld.TButton", command=set_windows_port).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Raspberry Pi", style="Handheld.TButton", command=set_pi_port).pack(side="left", padx=(0, 0))

        # Segunda fila: baud + conectar (evita overflow horizontal en 480×320)
        row2 = tk.Frame(self._frame_connect)
        row2.pack(fill="x", padx=12, pady=(0, 3))

        tk.Label(row2, text="Baud:", font=("", 10)).pack(side="left")
        self.baud_var = tk.StringVar(value="115200")
        tk.Entry(row2, textvariable=self.baud_var, width=8, font=("", 10)).pack(side="left", padx=(4, 8))

        self.btn_connect = ttk.Button(row2, text="Conectar", command=self.connect, style="HandheldBig.TButton")
        self.btn_connect.pack(side="left", fill="x", expand=True, padx=(0, 0), ipady=2)

        self.home_status_var = tk.StringVar(value="Lector: desconectado")
        tk.Label(
            self._frame_connect, textvariable=self.home_status_var, font=("", 8), wraplength=440, justify="center"
        ).pack(fill="x", padx=12, pady=(6, 6))

        self.btn_continue = ttk.Button(
            self._frame_connect,
            text="Continuar",
            style="HandheldBig.TButton",
            command=self._after_connect_continue,
            state="disabled",
        )
        self.btn_continue.pack(pady=4, ipadx=16, ipady=6)

    def _enter_connect(self, next_frame: str):
        """Pantalla de conexión reutilizable: al conectar, avanza a next_frame."""
        self._connect_next = next_frame or "menu"
        # Texto del botón de continuar según el flujo
        if self._connect_next == "setup":
            self.btn_continue.config(text="Continuar (ubicación)")
        else:
            self.btn_continue.config(text="Ir al menú")

        # Si ya está conectado, habilita continuar sin reconectar
        if self._driver.connected:
            self.home_status_var.set("Lector: conectado")
            self.btn_connect.config(state="disabled")
            self.btn_continue.config(state="normal")
        else:
            self.home_status_var.set("Lector: desconectado")
            self.btn_connect.config(state="normal")
            self.btn_continue.config(state="disabled")

        self._show_frame("connect")

    def _after_connect_continue(self):
        if self._connect_next == "setup":
            self._show_frame("setup")
        else:
            self._show_frame("menu")

    def _enter_inventory(self):
        """Entrar al módulo de inventario por ubicación."""
        if self._driver.connected:
            self._show_frame("setup")
        else:
            self._enter_connect(next_frame="setup")

    def _build_setup(self):
        self._frame_setup = tk.Frame(self.container)

        tk.Label(self._frame_setup, text="Ubicación del inventario", font=("", 11, "bold")).pack(
            anchor="w", padx=12, pady=(8, 6)
        )

        row_b = tk.Frame(self._frame_setup)
        row_b.pack(fill="x", padx=12, pady=4)
        tk.Label(row_b, text="Edificio:", font=("", 10)).pack(anchor="w")
        buildings = sorted(list(self._nested_locations.keys()))
        self.building_var = tk.StringVar(value=buildings[0])
        self.building_combo = ttk.Combobox(
            row_b,
            textvariable=self.building_var,
            values=buildings,
            state="readonly",
            width=32,
            font=("", 10),
        )
        self.building_combo.pack(fill="x", pady=(2, 0))

        row_r = tk.Frame(self._frame_setup)
        row_r.pack(fill="x", padx=12, pady=6)
        tk.Label(row_r, text="Cubículo / lab / sala:", font=("", 10)).pack(anchor="w")
        self.room_var = tk.StringVar()
        first_rooms = sorted(list(self._nested_locations[buildings[0]].keys()))
        self.room_var.set(first_rooms[0])
        self.room_combo = ttk.Combobox(
            row_r,
            textvariable=self.room_var,
            values=first_rooms,
            state="readonly",
            width=32,
            font=("", 10),
        )
        self.room_combo.pack(fill="x", pady=(2, 0))

        self.building_combo.bind("<<ComboboxSelected>>", self._on_building_selected)
        self.room_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_setup_hint())

        self.setup_hint_var = tk.StringVar(value="")
        tk.Label(self._frame_setup, textvariable=self.setup_hint_var, font=("", 8), fg="#444", wraplength=440).pack(
            fill="x", padx=12, pady=(3, 6)
        )
        self._refresh_setup_hint()

        row_btns = tk.Frame(self._frame_setup)
        row_btns.pack(fill="x", side="bottom", pady=8)

        ttk.Button(
            row_btns,
            text="Atrás",
            style="Handheld.TButton",
            command=lambda: self._show_frame("menu"),
        ).pack(side="left", padx=8)

        self.btn_to_scan = ttk.Button(
            row_btns,
            text="Siguiente",
            style="HandheldBig.TButton",
            command=self.go_to_scan_screen,
        )
        self.btn_to_scan.pack(side="right", padx=8, ipadx=8, ipady=4)

    def _refresh_setup_hint(self):
        self.setup_hint_var.set("Selección: {0}".format(self._location_key()))

    def _on_building_selected(self, event=None):
        ed = self.building_var.get()
        rooms = sorted(list(self._nested_locations.get(ed, {}).keys()))
        self.room_combo["values"] = rooms
        if rooms:
            self.room_var.set(rooms[0])
        self._refresh_setup_hint()

    def _build_scan(self):
        self._frame_scan = tk.Frame(self.container)

        top = tk.Frame(self._frame_scan)
        top.pack(fill="x", padx=10, pady=(4, 2))

        tk.Label(
            top,
            text="Precarga lista — inicia el pistoleo cuando quieras",
            font=("", 8, "bold"),
            fg="#2E7D32",
        ).pack(anchor="w", fill="x")

        self.scan_line_location = tk.StringVar(value="Ubicación: —")
        self.scan_line_time = tk.StringVar(value="Tiempo: 0.0 s")
        self.scan_line_counts = tk.StringVar(value="Esperados: 0 | Leídos únicos: 0")

        tk.Label(top, textvariable=self.scan_line_location, font=("", 9), anchor="w").pack(fill="x")
        tk.Label(top, textvariable=self.scan_line_time, font=("", 9), anchor="w").pack(fill="x")
        tk.Label(top, textvariable=self.scan_line_counts, font=("", 9), anchor="w").pack(fill="x")

        mid = tk.Frame(self._frame_scan)
        mid.pack(fill="both", expand=True, padx=8, pady=3)

        tk.Label(mid, text="Activos (esperados en esta ubicación)", font=("", 9), fg="#444").pack(anchor="w")

        tree_wrap = tk.Frame(mid)
        tree_wrap.pack(fill="both", expand=True, pady=(2, 4))

        self.scan_tree = ttk.Treeview(
            tree_wrap,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=4,
        )
        self.scan_tree.heading("status", text="Estado")
        self.scan_tree.heading("epc", text="Activo")
        self.scan_tree.heading("rssi", text="RSSI")
        self.scan_tree.column("status", width=88, anchor="center")
        self.scan_tree.column("epc", width=250, anchor="w")
        self.scan_tree.column("rssi", width=48, anchor="center")
        vsb_s = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=vsb_s.set)
        self.scan_tree.pack(side="left", fill="both", expand=True)
        vsb_s.pack(side="right", fill="y")

        self.scan_tree.tag_configure("found", background="#F4F4F4")
        self.scan_tree.tag_configure("missing", background="#FF7F7F")
        self.scan_tree.tag_configure("new", background="#90EE90")

        tk.Label(
            self._frame_scan,
            text="Últimas lecturas (log)",
            font=("", 8),
            fg="#444",
        ).pack(anchor="w", padx=10, pady=(0, 0))

        self.listbox = tk.Listbox(self._frame_scan, height=self._LOG_MAX_LINES, font=("Consolas", 8))
        self.listbox.pack(fill="x", padx=10, pady=3)

        row_pistol = tk.Frame(self._frame_scan)
        row_pistol.pack(fill="x", side="bottom", pady=(3, 3))

        self.btn_begin_pistol = tk.Button(
            row_pistol,
            text="Presionar Trigger",
            font=("", 11, "bold"),
            bg="#2E7D32",
            fg="white",
            activebackground="#1B5E20",
            activeforeground="white",
            relief="flat",
            command=self.begin_pistol_scan,
        )
        self.btn_begin_pistol.pack(side="left", fill="x", expand=True, padx=(10, 6), ipady=7)

        self.btn_stop = tk.Button(
            row_pistol,
            text="Detener",
            font=("", 11, "bold"),
            bg="#C62828",
            fg="white",
            activebackground="#B71C1C",
            activeforeground="white",
            relief="flat",
            command=self.stop_scan,
        )
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(6, 10), ipady=7)

        row = tk.Frame(self._frame_scan)
        row.pack(fill="x", side="bottom", pady=(0, 6))

        self.btn_pause = ttk.Button(
            row,
            text="Pausar",
            style="Handheld.TButton",
            command=self._toggle_pause,
        )
        self.btn_pause.pack(side="left", padx=(10, 4), ipadx=4, ipady=4)

        self.btn_cancel_scan = ttk.Button(
            row,
            text="Cancelar",
            style="Handheld.TButton",
            command=self.cancel_scan,
        )
        self.btn_cancel_scan.pack(side="left", padx=4, ipadx=4, ipady=4)

        self._set_scan_controls_reading(False)

    def _build_result(self):
        self._frame_result = tk.Frame(self.container)

        head = tk.Frame(self._frame_result)
        head.pack(fill="x", padx=10, pady=(8, 4))

        self.result_line_location = tk.StringVar(value="Ubicación: ")
        self.result_line_stats = tk.StringVar(value="Esperados: 0 | OK: 0 | Faltan: 0 | Nuevos: 0")

        tk.Label(head, textvariable=self.result_line_location, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(head, textvariable=self.result_line_stats, font=("", 10), anchor="w").pack(fill="x")

        filt = tk.Frame(self._frame_result)
        filt.pack(fill="x", padx=8, pady=(2, 4))

        tk.Label(filt, text="Ver:", font=("", 9)).pack(side="left", padx=(0, 6))
        for val, label in (("todos", "Todos"), ("faltantes", "Solo faltantes"), ("nuevos", "Solo nuevos")):
            ttk.Radiobutton(
                filt,
                text=label,
                value=val,
                variable=self._filter_mode,
                command=self._on_filter_change,
            ).pack(side="left", padx=2)

        tree_frame = tk.Frame(self._frame_result)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
            
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=7,
        )
        self.tree.heading("status", text="Estado")
        self.tree.heading("epc", text="Activo")
        self.tree.heading("rssi", text="RSSI")
        self.tree.column("status", width=96, anchor="center")
        self.tree.column("epc", width=270, anchor="w")
        self.tree.column("rssi", width=52, anchor="center")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        self.tree.tag_configure("found", background="#F4F4F4")
        self.tree.tag_configure("missing", background="#FF7F7F")
        self.tree.tag_configure("new", background="#90EE90")

        self.tree.bind("<Double-1>", self._on_result_double_click)

        legend = tk.Frame(self._frame_result)
        legend.pack(fill="x", padx=8)
        self._legend_chip(legend, "ENCONTRADO", "#F4F4F4").pack(side="left", padx=(0, 4))
        self._legend_chip(legend, "NO ESCANEADO", "#FF7F7F").pack(side="left", padx=(0, 4))
        self._legend_chip(legend, "ACTIVO NUEVO", "#90EE90").pack(side="left")

        row = tk.Frame(self._frame_result)
        row.pack(fill="x", pady=(6, 10))

        btns = tk.Frame(row)
        btns.pack(fill="x", padx=12)

        ttk.Button(
            btns,
            text="Nuevo escaneo",
            style="HandheldBig.TButton",
            command=self._result_new_scan,
        ).pack(side="left", fill="x", expand=True, ipadx=8, ipady=4, padx=(0, 6))

        ttk.Button(
            btns,
            text="Actualizar tipoUbicacion",
            style="HandheldBig.TButton",
            command=self._export_tipo_ubicacion_updated,
        ).pack(side="left", fill="x", expand=True, ipadx=8, ipady=4, padx=(0, 6))

        ttk.Button(
            btns,
            text="Menú",
            style="HandheldBig.TButton",
            command=self._go_menu_from_result,
        ).pack(side="right", fill="x", expand=True, ipadx=8, ipady=4, padx=(6, 0))

    def _build_detail(self):
        self._frame_detail = tk.Frame(self.container)

        tk.Label(self._frame_detail, text="Detalle de activo", font=("", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 8))

        box = tk.Frame(self._frame_detail)
        box.pack(fill="both", expand=True, padx=12)

        self.detail_epc_var = tk.StringVar(value="")
        self.detail_status_var = tk.StringVar(value="")
        self.detail_loc_var = tk.StringVar(value="")
        self.detail_rssi_var = tk.StringVar(value="")

        def line(lbl, var):
            r = tk.Frame(box)
            r.pack(fill="x", pady=4)
            tk.Label(r, text=lbl, font=("", 9), width=18, anchor="w").pack(side="left")
            tk.Label(r, textvariable=var, font=("", 9), wraplength=320, justify="left", anchor="w").pack(side="left")

        self.detail_code_var = tk.StringVar(value="")
        line("Activo:", self.detail_code_var)
        line("EPC:", self.detail_epc_var)
        line("Estado:", self.detail_status_var)
        line("Ubicación esperada:", self.detail_loc_var)
        line("Última RSSI:", self.detail_rssi_var)

        ttk.Button(
            self._frame_detail,
            text="Volver",
            style="HandheldBig.TButton",
            command=lambda: self._show_frame("result"),
        ).pack(side="bottom", pady=16, ipadx=16, ipady=6)

        ttk.Button(
            self._frame_detail,
            text="Menú",
            style="Handheld.TButton",
            command=self._go_menu_from_result,
        ).pack(side="bottom", pady=(0, 10), ipadx=10, ipady=2)

    def _go_menu_from_result(self):
        """Salir del flujo de inventario a menú principal."""
        self._cancel_pending_pistol_start()
        self._scanner.resume()
        self._scanner.stop()
        self._stop_scan_timer()
        self._set_scan_controls_reading(False)
        self._show_frame("menu")

    def _build_rastreo(self):
        self._frame_rastreo = tk.Frame(self.container)
        ttk.Button(
            self._frame_rastreo,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._show_frame("menu"),
        ).pack(anchor="w", padx=8, pady=6)
        tk.Label(
            self._frame_rastreo,
            text="Rastrear activo",
            font=("", 14, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 8))

        tk.Label(
            self._frame_rastreo,
            text="Busca por código de activo.",
            font=("", 8),
            wraplength=440,
            justify="left",
            fg="#444",
        ).pack(anchor="w", padx=12, pady=(0, 6))

        row = tk.Frame(self._frame_rastreo)
        row.pack(fill="x", padx=12, pady=4)

        self.rastreo_in_var = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.rastreo_in_var, font=("", 10)).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row, text="Buscar", style="Handheld.TButton", command=self._rastreo_buscar).pack(side="left")

        row2 = tk.Frame(self._frame_rastreo)
        row2.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(row2, text="Limpiar", style="Handheld.TButton", command=lambda: self.rastreo_in_var.set("")).pack(
            side="right"
        )

        box = tk.Frame(self._frame_rastreo)
        box.pack(fill="both", expand=True, padx=12, pady=(6, 6))

        self.rastreo_code_var = tk.StringVar(value="Activo: —")
        self.rastreo_epc_var = tk.StringVar(value="EPC: —")
        self.rastreo_loc_var = tk.StringVar(value="Ubicación esperada: —")

        tk.Label(box, textvariable=self.rastreo_code_var, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(box, textvariable=self.rastreo_epc_var, font=("", 8), fg="#444", anchor="w").pack(fill="x", pady=(2, 6))
        tk.Label(box, textvariable=self.rastreo_loc_var, font=("", 9), wraplength=440, justify="left", anchor="w").pack(
            fill="x"
        )

        # Proximidad (frío/caliente)
        prox = tk.Frame(self._frame_rastreo)
        prox.pack(fill="x", padx=12, pady=(0, 8))

        self.prox_state_var = tk.StringVar(value="Proximidad: —")
        self.prox_rssi_var = tk.StringVar(value="RSSI: —")
        tk.Label(prox, textvariable=self.prox_state_var, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(prox, textvariable=self.prox_rssi_var, font=("", 8), fg="#444", anchor="w").pack(fill="x", pady=(1, 4))

        self.prox_bar = ttk.Progressbar(prox, orient="horizontal", mode="determinate", maximum=100)
        self.prox_bar.pack(fill="x")

        row3 = tk.Frame(self._frame_rastreo)
        row3.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_prox_start = ttk.Button(row3, text="Iniciar rastreo", style="HandheldBig.TButton", command=self._prox_start)
        self.btn_prox_start.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)
        self.btn_prox_stop = ttk.Button(row3, text="Detener", style="HandheldBig.TButton", command=self._prox_stop, state="disabled")
        self.btn_prox_stop.pack(side="right", fill="x", expand=True, padx=(6, 0), ipady=2)

    def _enter_rastreo(self):
        # Evita que el scanner quede leyendo en background.
        self._cancel_pending_pistol_start()
        self._scanner.resume()
        self._scanner.stop()
        self._stop_scan_timer()
        self._set_scan_controls_reading(False)
        self._show_frame("rastreo")
        self._prox_stop()

    def _rastreo_normalize_input(self, s: str) -> tuple[str, str]:
        return self._tracking.normalize_input(s)

    def _rastreo_buscar(self):
        res = self._tracking.track(self.rastreo_in_var.get())
        if not res:
            messagebox.showinfo("Rastreo", "Escribe un EPC (hex) o un código de activo.")
            return
        self.rastreo_code_var.set("Activo: {0}".format(res.asset_code or "(desconocido)"))
        self.rastreo_epc_var.set("EPC: {0}".format(res.epc_hex))
        if not res.locations:
            self.rastreo_loc_var.set("Ubicación esperada: (no encontrado en catálogo)")
        elif len(res.locations) == 1:
            self.rastreo_loc_var.set("Ubicación esperada: {0}".format(res.locations[0]))
        else:
            locs = res.locations
            self.rastreo_loc_var.set("Ubicación esperada: " + " | ".join(locs[:4]) + (" ..." if len(locs) > 4 else ""))
        # Reset de proximidad con el EPC objetivo
        self._prox.reset(res.epc_hex)
        self.prox_bar["value"] = 0
        self.prox_state_var.set("Proximidad: listo")
        self.prox_rssi_var.set("RSSI: —")

    def _prox_set_controls(self, running: bool):
        self._prox_running = bool(running)
        self.btn_prox_start.config(state=("disabled" if running else "normal"))
        self.btn_prox_stop.config(state=("normal" if running else "disabled"))

    def _prox_start(self):
        # Debe haber EPC objetivo
        st = self._prox.state
        if st is None or not st.target_epc:
            # intenta buscar con lo que haya en input
            self._rastreo_buscar()
            st = self._prox.state
            if st is None or not st.target_epc:
                return

        self._prox_stop()
        self._prox_set_controls(True)

        target = st.target_epc
        seen = {"any": False}

        # Modo simulación (demostrativo): RSSI inventado que varía.
        if self._prox_force_sim or (not self._driver.connected):
            self.prox_state_var.set("Proximidad: simulación (demo)")
            self._prox_sim_start()
            self._prox_ui_start()
            return

        def on_tag(tag, _idx):
            epc = (tag.epc_hex or "").lower()
            if epc != target:
                return
            seen["any"] = True
            now_ms = int(self.tk.call("clock", "milliseconds"))
            self._prox.update(tag.rssi, now_ms)

        def on_err(e):
            self._on_scan_error(e)
            self._prox_stop()

        self._scanner.reset()
        self._scanner.start(on_tag_read=on_tag, on_error=on_err)
        self._prox_ui_start()

    def _prox_stop(self):
        self._prox_set_controls(False)
        # Detiene loop UI
        if self._prox_ui_job is not None:
            try:
                self.after_cancel(self._prox_ui_job)
            except Exception:
                pass
        self._prox_ui_job = None
        if getattr(self, "_prox_sim_job", None) is not None:
            try:
                self.after_cancel(self._prox_sim_job)
            except Exception:
                pass
        self._prox_sim_job = None
        # No detener el scanner global si estamos en otra pantalla, pero aquí sí:
        try:
            self._scanner.stop()
        except Exception:
            pass

    def _prox_ui_start(self):
        # Actualiza barra/labels cada 200ms y marca "sin señal" si no se ve recientemente
        def tick():
            if not self._prox_running:
                return
            st = self._prox.state
            now_ms = int(self.tk.call("clock", "milliseconds"))
            lvl = self._prox.level_0_100()
            self.prox_bar["value"] = lvl
            if st and st.ema_rssi is not None:
                self.prox_state_var.set(f"Proximidad: {self._prox.label()}  ({lvl}%)")
                self.prox_rssi_var.set(f"RSSI: {st.ema_rssi:.1f} dBm (último {st.last_rssi} dBm)")
                if st.last_seen_ms is not None and now_ms - st.last_seen_ms > 1200:
                    self.prox_state_var.set("Proximidad: Sin señal (no se ve el tag)")
            else:
                self.prox_state_var.set("Proximidad: Sin señal")
                self.prox_rssi_var.set("RSSI: —")
            self._prox_ui_job = self.after(200, tick)

        self._prox_ui_job = self.after(100, tick)

    def _prox_sim_start(self):
        # Simulación simple: random walk entre -90 y -35 dBm
        cur = {"r": -75}

        def step():
            if not self._prox_running:
                return
            cur["r"] += random.randint(-3, 3)
            if cur["r"] < -90:
                cur["r"] = -90
            if cur["r"] > -35:
                cur["r"] = -35
            now_ms = int(self.tk.call("clock", "milliseconds"))
            self._prox.update(cur["r"], now_ms)
            self._prox_sim_job = self.after(250, step)

        self._prox_sim_job = self.after(250, step)

    def _build_escritura(self):
        self._frame_escritura = tk.Frame(self.container)
        ttk.Button(
            self._frame_escritura,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._show_frame("menu"),
        ).pack(anchor="w", padx=8, pady=6)
        tk.Label(
            self._frame_escritura,
            text="Escribir tag",
            font=("", 14, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 8))

        tk.Label(
            self._frame_escritura,
            text="Flujo: escanea 1 etiqueta → escribe el código del activo → (futuro) programar EPC.",
            font=("", 8),
            wraplength=440,
            justify="left",
            fg="#444",
        ).pack(anchor="w", padx=12, pady=(0, 6))

        box = tk.Frame(self._frame_escritura)
        box.pack(fill="both", expand=True, padx=12, pady=(4, 6))

        self.write_current_epc_var = tk.StringVar(value="EPC actual: —")
        self.write_current_code_var = tk.StringVar(value="Código actual (si aplica): —")
        self.write_new_epc_var = tk.StringVar(value="EPC nuevo: —")
        self.write_status_var = tk.StringVar(value="")

        tk.Label(box, textvariable=self.write_current_epc_var, font=("", 9), anchor="w").pack(fill="x")
        tk.Label(box, textvariable=self.write_current_code_var, font=("", 8), fg="#444", anchor="w").pack(
            fill="x", pady=(1, 8)
        )

        row = tk.Frame(box)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Código activo:", font=("", 10)).pack(side="left")
        self.write_code_in_var = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.write_code_in_var, font=("", 10)).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.write_code_in_var.trace_add("write", lambda *_: self._write_calc_new_epc(silent=True))

        tk.Label(box, textvariable=self.write_new_epc_var, font=("", 9), anchor="w").pack(fill="x", pady=(8, 2))
        tk.Label(box, textvariable=self.write_status_var, font=("", 8), fg="#444", wraplength=440, justify="left").pack(
            fill="x", pady=(2, 0)
        )

        row2 = tk.Frame(self._frame_escritura)
        row2.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(row2, text="Escanear etiqueta", style="HandheldBig.TButton", command=self._write_scan_once).pack(
            side="left", fill="x", expand=True, ipady=2
        )

        row3 = tk.Frame(self._frame_escritura)
        row3.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(row3, text="Escribir (simulado)", style="HandheldBig.TButton", command=self._write_execute).pack(
            side="left", fill="x", expand=True, ipady=2
        )

        # Estado interno
        self._write_current_epc = ""
        self._write_new_epc = ""
        # (la simulación/hardware la gestiona TagWriterService)

    def _write_scan_once(self):
        try:
            r = self._tag_writer.scan_one_tag(self._driver)
        except Exception as e:
            messagebox.showerror("Escritura", str(e))
            return

        self._write_current_epc = r.epc_hex
        suf = " (simulado)" if r.simulated else ""
        self.write_current_epc_var.set(f"EPC actual: {r.epc_hex}{suf}")
        self.write_current_code_var.set(f"Código actual (si aplica): {r.decoded_code or '—'}")
        self.write_status_var.set("Etiqueta leída. Escribe el código del activo para generar el EPC nuevo.")
        self._write_calc_new_epc(silent=True)

    def _write_calc_new_epc(self, silent: bool = False):
        code = (self.write_code_in_var.get() or "").strip()
        if not code:
            self._write_new_epc = ""
            self.write_new_epc_var.set("EPC nuevo: —")
            return
        epc = self._tag_writer.compute_new_epc(code)
        if not epc:
            self._write_new_epc = ""
            self.write_new_epc_var.set("EPC nuevo: —")
            return
        self._write_new_epc = epc
        self.write_new_epc_var.set(f"EPC nuevo: {epc}  (desde {code})")
        if not silent:
            self.write_status_var.set("Listo para escribir (simulado).")

    def _write_execute(self):
        if not self._write_new_epc:
            self._write_calc_new_epc(silent=True)
        try:
            wr = self._tag_writer.write_epc(self._driver, self._write_current_epc, self._write_new_epc)
        except Exception as e:
            messagebox.showerror("Escritura", str(e))
            return

        old = self._write_current_epc
        self._write_current_epc = wr.new_epc_hex
        code = (self.write_code_in_var.get() or "").strip()
        suf = " (simulado)" if wr.simulated else ""
        self.write_current_epc_var.set(f"EPC actual: {self._write_current_epc}{suf}")
        self.write_current_code_var.set(f"Código actual (si aplica): {code or '—'}")
        self.write_status_var.set(write_status_programmed(old, self._write_current_epc))
        messagebox.showinfo("Escritura", "Etiqueta programada." if not wr.simulated else "Simulación: etiqueta programada.")

    def _build_hid(self):
        """Modo pistola como teclado Bluetooth: sin inventario en esta pantalla (flujograma: uso con laptop + web)."""
        self._frame_hid = tk.Frame(self.container)
        ttk.Button(
            self._frame_hid,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._show_frame("menu"),
        ).pack(anchor="w", padx=8, pady=6)
        tk.Label(
            self._frame_hid,
            text="Modo teclado (Bluetooth)",
            font=("", 14, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 6))
        tk.Label(
            self._frame_hid,
            text="Empareja la pistola con la laptop. Si ya se ha hecho antes, primero olvida el dispositivo en la laptop. Después, empareja de nuevo.",
            font=("", 9),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=12, pady=2)
       

    def _legend_chip(self, parent, text, bg):
        f = tk.Frame(parent, bg=bg, bd=1, relief="solid")
        tk.Label(f, text=text, bg=bg, padx=4, pady=1, font=("", 8)).pack()
        return f

    def _on_filter_change(self):
        self._apply_result_filter()

    def _result_new_scan(self):
        self._show_frame("setup")

    def _toggle_pause(self):
        if not self._scanner.is_running():
            return
        if self._scanner.is_paused():
            self._scanner.resume()
            self.btn_pause.config(text="Pausar")
        else:
            self._scanner.pause()
            self.btn_pause.config(text="Reanudar")

    def _set_scan_controls_reading(self, active):
        """active=True: pistoleo en curso (Iniciar off, Detener/Pausar on). active=False: listo para iniciar."""
        if active:
            self.btn_begin_pistol.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.btn_pause.config(state="normal", text="Pausar")
            self.btn_cancel_scan.config(state="normal")
        else:
            self.btn_begin_pistol.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled", text="Pausar")

    def _fill_scan_tree_and_header(self):
        loc = self._location_key()
        self._refresh_setup_hint()
        self._expected_set = self._inventory.get_expected_set(loc)
        self._tree_expected_items = {}
        self._tree_new_items = {}
        for item in self.scan_tree.get_children():
            self.scan_tree.delete(item)
        for epc in sorted(list(self._expected_set)):
            disp = asset_display_from_epc(epc)
            iid = self.scan_tree.insert("", tk.END, values=("NO ESCANEADO", disp, ""), tags=("missing",))
            self._tree_expected_items[epc] = iid
        self.scan_line_location.set("Ubicación: {0}".format(loc))
        self.scan_line_time.set("Tiempo: 0.0 s")
        self.scan_line_counts.set(
            "Esperados: {0} | Leídos únicos: 0".format(self._inventory.expected_count(loc))
        )

    def go_to_scan_screen(self):
        """Solo navega a la pantalla de inventario; no arranca el lector (evita el mismo clic como trigger)."""
        self._cancel_pending_pistol_start()
        self._scanner.resume()
        self._scanner.stop()
        self._stop_scan_timer()
        self._recent_log = []
        self.listbox.delete(0, tk.END)
        self._fill_scan_tree_and_header()
        self._set_scan_controls_reading(False)
        self._show_frame("scan")

    def begin_pistol_scan(self):
        """Aquí sí arranca el escaneo continuo (simulación de pistoleo)."""
        if self._scanner.is_running():
            return
        self._cancel_pending_pistol_start()
        self._scanner.reset()
        self._recent_log = []
        self.listbox.delete(0, tk.END)
        self._fill_scan_tree_and_header()
        self._set_scan_controls_reading(True)
        # Pequeño retraso: el clic del botón no debe solaparse con la primera lectura (trigger simulado).
        self._pistol_start_job = self.after(120, self._start_pistol_thread)

    def _cancel_pending_pistol_start(self):
        if self._pistol_start_job is not None:
            try:
                self.after_cancel(self._pistol_start_job)
            except Exception:
                pass
            self._pistol_start_job = None

    def _start_pistol_thread(self):
        self._pistol_start_job = None
        if self._scanner.is_running():
            return
        self._scan_started_ms = int(self.tk.call("clock", "milliseconds"))
        self._start_scan_timer()
        self._scanner.resume()
        self._scanner.start(on_tag_read=self._on_tag_read, on_error=self._on_scan_error)

    def _on_scan_error(self, e: Exception):
        # Corre en hilo de Scanner; brincar a hilo UI con after()
        def ui():
            self._cancel_pending_pistol_start()
            self._scanner.resume()
            self._scanner.stop()
            self._stop_scan_timer()
            self._set_scan_controls_reading(False)
            msg = (
                "Se perdió la conexión con el lector (serial).\n\n"
                f"Detalle: {e}\n\n"
                "Causas típicas:\n"
                "- Cable/OTG flojo o el Arduino se reinició\n"
                "- Otro proceso está usando el puerto (p. ej. Monitor Serie / servicio)\n"
                "- Puerto equivocado (/dev/ttyUSB0 vs /dev/ttyACM0)\n\n"
                "Tip: prueba en terminal:\n"
                "  ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null\n"
                "  lsof /dev/ttyUSB0 2>/dev/null\n"
            )
            messagebox.showerror("Lector desconectado", msg)

        try:
            self.after(0, ui)
        except Exception:
            pass

    def connect(self):
        if self._driver.connected:
            messagebox.showinfo("Info", "Ya conectado.")
            self.btn_continue.config(state="normal")
            self.home_status_var.set("Lector: conectado")
            return
        port = self.port_var.get().strip()
        port_l = port.lower()
        if port_l.startswith("/dev/ttyusb"):
            port = "/dev/ttyUSB" + port[len("/dev/ttyusb") :]
        elif port_l.startswith("/dev/ttyacm"):
            port = "/dev/ttyACM" + port[len("/dev/ttyacm") :]
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
        self.home_status_var.set("Lector: conectado ({0} @ {1})".format(port, baud))
        self.btn_connect.config(state="disabled")
        self.btn_continue.config(state="normal")

    def stop_scan(self):
        self._cancel_pending_pistol_start()
        self._scanner.resume()
        self._scanner.stop()
        self._stop_scan_timer()
        self._set_scan_controls_reading(False)
        self._compare_and_show()
        self._show_frame("result")

    def _export_tipo_ubicacion_updated(self):
        """Genera un reporte de sesión con el MISMO formato que el catálogo de activos.

        - Salida: lista JSON con objetos `{idDetalle, tipoUbicacion, activo:{...}}`
        - Solo incluye los activos escaneados en esta sesión (found)
        - tipoUbicacion:
          - C si el EPC era esperado en la ubicación actual
          - U si el EPC fue escaneado pero no era esperado en la ubicación actual
        """
        try:
            loc = self._location_key()
            snap = self._last_snap or {"seen_epcs": set()}
            found = set(snap.get("seen_epcs") or set())
            expected = set(self._expected_set or set())

            here = os.path.dirname(os.path.abspath(__file__))
            web_dir = os.path.abspath(os.path.join(here, "..", "..", "pi_ble_hid", "web"))
            activos_path = os.path.join(web_dir, "activosPiso2_Computacion.json")
            if not os.path.isfile(activos_path):
                messagebox.showerror("Actualización", f"No existe:\n{activos_path}")
                return
            rows = json.loads(open(activos_path, "r", encoding="utf-8").read())
            if not isinstance(rows, list):
                messagebox.showerror("Actualización", "El JSON de activos no tiene formato de lista.")
                return

            # Index por código de activo para recuperar el row original sin modificar su estructura.
            by_code = {}
            for r in rows:
                a = (r or {}).get("activo") or {}
                code = a.get("activo")
                if code:
                    by_code[str(code).strip()] = r

            expected_l = {str(x).lower() for x in expected}
            out_rows = []
            found_l = {str(x).lower() for x in found}

            # 1) Escaneados: C/U (o ACTIVO NUEVO si no existe en catálogo base)
            for epc in sorted(found_l):
                code = epc12_hex_to_asset_code(epc)
                src = by_code.get(code) if code else None
                if src:
                    rr = json.loads(json.dumps(src, ensure_ascii=False))  # deep copy sin cambiar formato
                    rr["tipoUbicacion"] = "C" if epc in expected_l else "U"
                    out_rows.append(rr)
                    continue

                # Activo NUEVO (no existe en el catálogo base): conservar formato "tipo webservice"
                out_rows.append(
                    {
                        "idDetalle": None,
                        "tipoUbicacion": "U",
                        "activo": {
                            "activo": code or None,
                            "descripcion": "ACTIVO NUEVO",
                            "idUbicacion": None,
                            "nombreUbicacion": loc,
                            "nombreResponsable": None,
                        },
                    }
                )

            # 2) Esperados pero NO escaneados en esta ubicación: N
            for epc in sorted(expected_l.difference(found_l)):
                code = epc12_hex_to_asset_code(epc)
                if not code:
                    continue
                src = by_code.get(code)
                if not src:
                    continue
                rr = json.loads(json.dumps(src, ensure_ascii=False))  # deep copy
                rr["tipoUbicacion"] = "N"
                out_rows.append(rr)

            out_dir = os.path.abspath(os.path.join(web_dir, "resultados"))
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_loc = "".join([c for c in loc if c.isalnum() or c in (" ", "-", "_", "·")]).strip().replace(" ", "_")
            out_path = os.path.join(out_dir, f"activosPiso2_Computacion_sesion_{safe_loc}_{ts}.json")
            open(out_path, "w", encoding="utf-8").write(json.dumps(out_rows, ensure_ascii=False, indent=2))

            messagebox.showinfo("Actualización", f"Archivo generado:\n{out_path}")
        except Exception:
            # No bloquea el flujo principal
            return

    def cancel_scan(self):
        self._cancel_pending_pistol_start()
        self._scanner.resume()
        self._scanner.stop()
        self._stop_scan_timer()
        self._set_scan_controls_reading(False)
        self._show_frame("setup")

    def _start_scan_timer(self):
        self._stop_scan_timer()

        def tick():
            if not self._scanner.is_running():
                return
            now_ms = int(self.tk.call("clock", "milliseconds"))
            elapsed_s = 0.0
            if self._scan_started_ms is not None:
                elapsed_s = max(0.0, (now_ms - self._scan_started_ms) / 1000.0)
            loc = self._location_key()
            snap = self._scanner.snapshot()
            uniques = len(snap["seen_epcs"])
            self.scan_line_location.set("Ubicación: {0}".format(loc))
            self.scan_line_time.set("Tiempo: {0:.1f} s".format(elapsed_s))
            self.scan_line_counts.set(
                "Esperados: {0} | Leídos únicos: {1}".format(self._inventory.expected_count(loc), uniques)
            )
            self._scan_timer_job = self.after(250, tick)

        self._scan_timer_job = self.after(250, tick)

    def _stop_scan_timer(self):
        if self._scan_timer_job is not None:
            try:
                self.after_cancel(self._scan_timer_job)
            except Exception:
                pass
        self._scan_timer_job = None
        self._scan_started_ms = None

    def _append_log_line(self, line):
        self._recent_log.append(line)
        while len(self._recent_log) > self._LOG_MAX_LINES:
            self._recent_log.pop(0)
        self.listbox.delete(0, tk.END)
        for ln in self._recent_log:
            self.listbox.insert(tk.END, ln)

    def _on_tag_read(self, tag, idx_in_batch):
        line = "{0}  RSSI={1}".format(tag.epc_hex, tag.rssi)
        delay_ms = idx_in_batch * 45

        def append():
            self._append_log_line(line)
            self._update_scan_tree_live(tag)

        if delay_ms <= 0:
            self.after(0, append)
        else:
            self.after(delay_ms, append)

    def _update_scan_tree_live(self, tag):
        epc = tag.epc_hex
        if epc in self._expected_set:
            iid = self._tree_expected_items.get(epc)
            if iid is not None:
                try:
                    disp = asset_display_from_epc(epc)
                    self.scan_tree.item(
                        iid,
                        values=("ENCONTRADO", disp, tag.rssi),
                        tags=("found",),
                    )
                except Exception:
                    pass
            return

        iid_new = self._tree_new_items.get(epc)
        if iid_new is None:
            disp = asset_display_from_epc(epc)
            iid_new = self.scan_tree.insert("", tk.END, values=("ACTIVO NUEVO", disp, tag.rssi), tags=("new",))
            self._tree_new_items[epc] = iid_new
        else:
            try:
                disp = asset_display_from_epc(epc)
                self.scan_tree.item(iid_new, values=("ACTIVO NUEVO", disp, tag.rssi), tags=("new",))
            except Exception:
                pass

    def _compare_and_show(self):
        loc = self._location_key()
        r, snap, expected = self._inventory.compare_location(loc)
        self._last_snap = snap
        self._result_location = loc

        self.result_line_location.set("Ubicación: {0}".format(loc))
        self.result_line_stats.set(
            "Esperados: {0} | ENCONTRADOS: {1} | Faltan: {2} | Nuevos: {3}".format(
                len(expected),
                len(r.encontrados),
                len(r.faltantes),
                len(r.nuevos),
            )
        )

        self._result_rows = []
        self._result_iid_to_epc = {}
        self._result_rows = build_result_rows(r, snap)

        self._filter_mode.set("todos")
        self._apply_result_filter()

    def _apply_result_filter(self):
        mode = self._filter_mode.get()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._result_iid_to_epc = {}

        for row in self._result_rows:
            if mode == "faltantes" and row["kind"] != "faltante":
                continue
            if mode == "nuevos" and row["kind"] != "nuevo":
                continue
            tag = "found"
            if row["kind"] == "faltante":
                tag = "missing"
            elif row["kind"] == "nuevo":
                tag = "new"
            epc = row["epc"]
            disp = asset_display_from_epc(epc)
            iid = self.tree.insert(
                "",
                tk.END,
                values=(row["status"], disp, row["rssi"]),
                tags=(tag,),
            )
            self._result_iid_to_epc[iid] = epc

    def _on_result_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if len(vals) < 3:
            return
        status, _disp, rssi = vals[0], vals[1], vals[2]
        epc = self._result_iid_to_epc.get(sel[0], "")
        self.detail_epc_var.set(epc)
        self.detail_code_var.set(asset_code_or_dash(epc))
        self.detail_status_var.set(status)
        self.detail_loc_var.set(self._result_location)
        self.detail_rssi_var.set(rssi if rssi else "—")
        self._show_frame("detail")

    def on_close(self):
        try:
            self._cancel_pending_pistol_start()
            self._scanner.resume()
            self._scanner.stop()
            self._driver.close()
        finally:
            self.destroy()


def main():
    HandheldApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
