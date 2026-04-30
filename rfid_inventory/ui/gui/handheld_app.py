"""Inventario RFID para pantalla pequeña (Waveshare típica 480×320, p. ej. con Raspberry Pi Zero 2 W).

Flujograma (menú principal):
  - Inventario por ubicación: conexión lector → ubicación → escaneo → resultado (y detalle).
  - Rastrear activo / Escribir tag: pendientes de lógica (solo UI placeholder).
  - Modo teclado BT: pistola como lector de códigos hacia la laptop (sin flujo RFID en esta UI).
"""

import json
import os
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from rfid_inventory.app import Scanner
from rfid_inventory.app.inventory_service import InventoryService
from rfid_inventory.drivers import R200Driver


def _asset_code_to_epc12_hex(code: str) -> str:
    """Misma codificación que el emulador: ASCII (máx 12) + 0x00 hasta 12 bytes, y luego hex."""
    s = (code or "").strip()
    b = s.encode("ascii", errors="ignore")[:12]
    b = b.ljust(12, b"\x00")
    return b.hex()


def _parse_nombre_ubicacion(nombre: str) -> tuple[str, str]:
    """Extrae edificio y 'sala' desde el string del catálogo (formato 'Unidad: ... - Edificio: X - ...')."""
    if not nombre:
        return ("(Sin edificio)", "(Sin sala)")
    parts = [p.strip() for p in str(nombre).split(" - ") if p.strip()]
    fields = {}
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    edificio = fields.get("edificio") or "(Sin edificio)"
    piso = fields.get("piso")
    cubo = fields.get("cubo")
    subcubo = fields.get("subcubo")
    area = fields.get("area")
    sala_bits = []
    if piso:
        sala_bits.append(f"Piso {piso}")
    if cubo:
        sala_bits.append(f"Cubo {cubo}")
    if subcubo:
        sala_bits.append(f"SubCubo {subcubo}")
    if area:
        sala_bits.append(area)
    sala = " · ".join(sala_bits) if sala_bits else str(nombre)
    return (edificio, sala)


def _read_json_first(paths: list[str]):
    """Lee el primer JSON existente y válido de una lista de rutas."""
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        try:
            return json.loads(open(p, "r", encoding="utf-8").read())
        except Exception:
            continue
    return None


def _sala_from_ubic_row(u: dict) -> str:
    piso = u.get("piso")
    cubo = u.get("cubo")
    subcubo = u.get("subcubo")
    area = u.get("area")
    sala_bits = []
    if piso:
        sala_bits.append(f"Piso {piso}")
    if cubo:
        sala_bits.append(f"Cubo {cubo}")
    if subcubo:
        sala_bits.append(f"SubCubo {subcubo}")
    if area:
        sala_bits.append(str(area))
    nombre_u = u.get("nombreUbicacion")
    return " · ".join(sala_bits) if sala_bits else (str(nombre_u) if nombre_u else "(Sin sala)")


def _load_locations_nested_from_json() -> dict:
    """edificio -> sala -> lista de EPC esperados (hex).

    Fuente de datos:
    - Ubicaciones: `ubicacionesComputacion.json`
    - Activos por ubicación: `activosPiso2_Computacion.json`

    Relación:
    - Preferentemente por `idUbicacion` (en activos) contra `idUbicacion` (en ubicaciones).
    - Si no existe match, cae a parsear `nombreUbicacion` desde el JSON de activos.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # rfid_inventory/ui/gui -> rfid_inventory -> pi_ble_hid/web
    web_dir = os.path.abspath(os.path.join(here, "..", "..", "pi_ble_hid", "web"))
    data_dir = os.path.abspath(os.path.join(here, "..", "..", "data", "catalog_ejemplo"))

    ubic_paths = [
        os.path.join(web_dir, "ubicacionesComputacion.json"),
        os.path.join(data_dir, "ubicacionesComputacion.json"),
    ]
    activos_paths = [
        os.path.join(web_dir, "activosPiso2_Computacion.json"),
        os.path.join(data_dir, "activosPiso2_Computacion.json"),
    ]

    ubic_rows = _read_json_first(ubic_paths) or []
    activo_rows = _read_json_first(activos_paths) or []
    if not isinstance(ubic_rows, list):
        ubic_rows = []
    if not isinstance(activo_rows, list):
        activo_rows = []

    ubic_by_id: dict[int, dict] = {}
    for u in ubic_rows:
        if not isinstance(u, dict):
            continue
        uid = u.get("idUbicacion")
        if isinstance(uid, int):
            ubic_by_id[uid] = u

    out: dict[str, dict[str, list[str]]] = {}
    seen_per_room: dict[tuple[str, str], set[str]] = {}

    # 1) Primero: publica TODAS las ubicaciones del JSON, aunque no tengan activos.
    for uid, u in ubic_by_id.items():
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_from_ubic_row(u)
        if edif not in out:
            out[edif] = {}
        out[edif].setdefault(sala, [])
        seen_per_room.setdefault((edif, sala), set())

    # 2) Luego: agrega activos que hagan match por idUbicacion.
    for r in activo_rows:
        a = (r or {}).get("activo") or {}
        code = a.get("activo")
        if not code:
            continue

        uid = a.get("idUbicacion")
        if not (isinstance(uid, int) and uid in ubic_by_id):
            # Mantener "solo ubicaciones del JSON": si no hay match, no inventamos ubicación.
            continue
        u = ubic_by_id[uid]
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_from_ubic_row(u)

        key = (edif, sala)
        if key not in seen_per_room:
            seen_per_room[key] = set()
        epc_hex = _asset_code_to_epc12_hex(str(code))
        if epc_hex in seen_per_room[key]:
            continue
        seen_per_room[key].add(epc_hex)
        if edif not in out:
            out[edif] = {}
        out[edif].setdefault(sala, []).append(epc_hex)

    # orden estable
    for edif in out:
        for sala in out[edif]:
            out[edif][sala].sort()
    return out


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


def _flatten_locations(nested):
    flat = {}
    for edif, rooms in nested.items():
        for sala, epcs in rooms.items():
            flat[_location_label(edif, sala)] = epcs
    return flat


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
        self._last_snap = None
        self._filter_mode = tk.StringVar(value="todos")

        self._driver = R200Driver()
        self._scanner = Scanner(self._driver)
        self._nested_locations = _load_locations_nested_from_json() or _mock_locations_nested()
        self._locations = _flatten_locations(self._nested_locations)
        self._inventory = InventoryService(self._locations, self._scanner)

        self._init_style()

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self._frame_menu = None
        self._frame_connect = None
        self._frame_setup = None
        self._frame_scan = None
        self._frame_result = None
        self._frame_detail = None
        self._frame_rastreo = None
        self._frame_escritura = None
        self._frame_hid = None

        self._build_menu()
        self._build_connect()
        self._build_setup()
        self._build_scan()
        self._build_result()
        self._build_detail()
        self._build_rastreo()
        self._build_escritura()
        self._build_hid()

        self._show_frame("menu")

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
        style.configure("Treeview", rowheight=20)
        style.configure("Treeview.Heading", font=("", 9, "bold"))
        style.configure("Handheld.TButton", font=("", 11))
        style.configure("HandheldBig.TButton", font=("", 13))

    def _show_frame(self, name):
        for w in self.container.winfo_children():
            w.pack_forget()
        if name == "menu":
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

    def _build_menu(self):
        self._frame_menu = tk.Frame(self.container)

        tk.Label(
            self._frame_menu,
            text="Sistema de Inventario RFID",
            font=("", 16, "bold"),
        ).pack(pady=(10, 4))
        tk.Label(
            self._frame_menu,
            text="Pantalla 480×320 · elige una opción",
            font=("", 9),
            fg="#555",
        ).pack(pady=(0, 8))

        def big(parent, text, command):
            b = ttk.Button(
                parent,
                text=text,
                style="HandheldBig.TButton",
                command=command,
            )
            b.pack(fill="x", padx=16, pady=4, ipady=6)
            return b

        big(
            self._frame_menu,
            "Inventario en ubicación",
            lambda: self._show_frame("connect"),
        )
        big(
            self._frame_menu,
            "Rastrear activo (próximamente)",
            lambda: self._show_frame("rastreo"),
        )
        big(
            self._frame_menu,
            "Escribir tag (próximamente)",
            lambda: self._show_frame("escritura"),
        )
        big(
            self._frame_menu,
            "Modo teclado (códigos a la laptop)",
            self._hid_enable_advertising_and_open,
        )

    def _build_connect(self):
        """Lector serial: conectar y seguir a selección de ubicación (flujograma: inventario del lugar)."""
        self._frame_connect = tk.Frame(self.container)

        ttk.Button(
            self._frame_connect,
            text="← Menú",
            style="Handheld.TButton",
            command=lambda: self._show_frame("menu"),
        ).pack(anchor="w", padx=8, pady=(6, 0))

        tk.Label(
            self._frame_connect,
            text="Inventario en ubicación",
            font=("", 15, "bold"),
        ).pack(pady=(4, 4))

        tk.Label(
            self._frame_connect,
            text="Conecta el lector RFID al puerto",
            font=("", 9),
            wraplength=440,
            justify="center",
        ).pack(pady=(0, 8))

        row = tk.Frame(self._frame_connect)
        row.pack(fill="x", padx=14, pady=4)

        tk.Label(row, text="Puerto:", font=("", 10)).pack(side="left")
        # Default: si estamos en Pi, sugiere /dev/serial/by-id; si no, COM5.
        default_port = self._suggest_pi_serial_port() if os.name == "posix" else "COM5"
        self.port_var = tk.StringVar(value=default_port or ("COM5" if os.name != "posix" else "/dev/ttyUSB0"))
        tk.Entry(row, textvariable=self.port_var, width=18, font=("", 10)).pack(side="left", padx=(4, 10))

        def set_windows_port():
            self.port_var.set("COM5")

        def set_pi_port():
            p = self._suggest_pi_serial_port()
            if p:
                self.port_var.set(p)
            else:
                self.port_var.set("/dev/ttyUSB0")

        ttk.Button(row, text="Windows", style="Handheld.TButton", command=set_windows_port).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Raspberry Pi", style="Handheld.TButton", command=set_pi_port).pack(side="left", padx=(0, 6))

        tk.Label(row, text="Baud:", font=("", 10)).pack(side="left")
        self.baud_var = tk.StringVar(value="115200")
        tk.Entry(row, textvariable=self.baud_var, width=7, font=("", 10)).pack(side="left", padx=(4, 10))

        self.btn_connect = ttk.Button(row, text="Conectar", command=self.connect, style="Handheld.TButton")
        self.btn_connect.pack(side="left", padx=6)

        self.home_status_var = tk.StringVar(value="Lector: desconectado")
        tk.Label(
            self._frame_connect, textvariable=self.home_status_var, font=("", 9), wraplength=440, justify="center"
        ).pack(fill="x", padx=12, pady=(8, 8))

        self.btn_continue = ttk.Button(
            self._frame_connect,
            text="Continuar (ubicación)",
            style="HandheldBig.TButton",
            command=lambda: self._show_frame("setup"),
            state="disabled",
        )
        self.btn_continue.pack(pady=4, ipadx=16, ipady=6)

    def _build_setup(self):
        self._frame_setup = tk.Frame(self.container)

        tk.Label(self._frame_setup, text="Ubicación del inventario", font=("", 12, "bold")).pack(
            anchor="w", padx=12, pady=(12, 8)
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
        row_r.pack(fill="x", padx=12, pady=8)
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
        tk.Label(self._frame_setup, textvariable=self.setup_hint_var, font=("", 9), fg="#444", wraplength=440).pack(
            fill="x", padx=12, pady=(4, 8)
        )
        self._refresh_setup_hint()

        row_btns = tk.Frame(self._frame_setup)
        row_btns.pack(fill="x", side="bottom", pady=12)

        ttk.Button(
            row_btns,
            text="Atrás",
            style="Handheld.TButton",
            command=lambda: self._show_frame("connect"),
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
        top.pack(fill="x", padx=10, pady=(6, 2))

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
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        tk.Label(mid, text="Activos (esperados en esta ubicación)", font=("", 9), fg="#444").pack(anchor="w")

        tree_wrap = tk.Frame(mid)
        tree_wrap.pack(fill="both", expand=True, pady=(2, 4))

        self.scan_tree = ttk.Treeview(
            tree_wrap,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=5,
        )
        self.scan_tree.heading("status", text="Estado")
        self.scan_tree.heading("epc", text="EPC")
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
        self.listbox.pack(fill="x", padx=10, pady=4)

        row_pistol = tk.Frame(self._frame_scan)
        row_pistol.pack(fill="x", side="bottom", pady=(4, 4))

        self.btn_begin_pistol = tk.Button(
            row_pistol,
            text="Presionar Trigger",
            font=("", 12, "bold"),
            bg="#2E7D32",
            fg="white",
            activebackground="#1B5E20",
            activeforeground="white",
            relief="flat",
            command=self.begin_pistol_scan,
        )
        self.btn_begin_pistol.pack(side="left", fill="x", expand=True, padx=(10, 6), ipady=10)

        self.btn_stop = tk.Button(
            row_pistol,
            text="Detener",
            font=("", 12, "bold"),
            bg="#C62828",
            fg="white",
            activebackground="#B71C1C",
            activeforeground="white",
            relief="flat",
            command=self.stop_scan,
        )
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(6, 10), ipady=10)

        row = tk.Frame(self._frame_scan)
        row.pack(fill="x", side="bottom", pady=(0, 8))

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
        self.tree.heading("epc", text="EPC")
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
            text="← Menú",
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
            text="Pendiente: buscar un EPC y mostrar su ubicación o historial. La lógica se conectará al catálogo o al lector según diseño.",
            font=("", 9),
            wraplength=440,
            justify="left",
            fg="#444",
        ).pack(anchor="w", padx=12, pady=4)

    def _build_escritura(self):
        self._frame_escritura = tk.Frame(self.container)
        ttk.Button(
            self._frame_escritura,
            text="← Menú",
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
            text="Pendiente: programación de EPC en etiquetas (R200 u otro comando). Aquí irá la secuencia de escritura.",
            font=("", 9),
            wraplength=440,
            justify="left",
            fg="#444",
        ).pack(anchor="w", padx=12, pady=4)

    def _build_hid(self):
        """Modo pistola como teclado Bluetooth: sin inventario en esta pantalla (flujograma: uso con laptop + web)."""
        self._frame_hid = tk.Frame(self.container)
        ttk.Button(
            self._frame_hid,
            text="← Menú",
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
            text="La pistola envía códigos a la laptop como lector de barras. Empareja Windows con la Pi y abre el módulo web en el navegador en la laptop.",
            font=("", 9),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=12, pady=2)
        tk.Label(
            self._frame_hid,
            text="En la Pi: servicio BLE (p. ej. gatt_server_rfid en pi_ble_hid). Esta pantalla no inicia el Bluetooth: solo indica el modo operativo.",
            font=("", 8),
            wraplength=440,
            justify="left",
            fg="#666",
        ).pack(anchor="w", padx=12, pady=(6, 4))

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
            iid = self.scan_tree.insert("", tk.END, values=("NO ESCANEADO", epc, ""), tags=("missing",))
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
                    self.scan_tree.item(
                        iid,
                        values=("ENCONTRADO", epc, tag.rssi),
                        tags=("found",),
                    )
                except Exception:
                    pass
            return

        iid_new = self._tree_new_items.get(epc)
        if iid_new is None:
            iid_new = self.scan_tree.insert("", tk.END, values=("ACTIVO NUEVO", epc, tag.rssi), tags=("new",))
            self._tree_new_items[epc] = iid_new
        else:
            try:
                self.scan_tree.item(iid_new, values=("ACTIVO NUEVO", epc, tag.rssi), tags=("new",))
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

        for epc in r.encontrados:
            rss = snap["last_rssi"].get(epc, "")
            self._result_rows.append(
                {"kind": "encontrado", "status": "ENCONTRADO", "epc": epc, "rssi": rss}
            )
        for epc in r.faltantes:
            self._result_rows.append(
                {"kind": "faltante", "status": "NO ESCANEADO", "epc": epc, "rssi": ""}
            )
        for epc in r.nuevos:
            rss = snap["last_rssi"].get(epc, "")
            self._result_rows.append(
                {"kind": "nuevo", "status": "ACTIVO NUEVO", "epc": epc, "rssi": rss}
            )

        self._filter_mode.set("todos")
        self._apply_result_filter()

    def _apply_result_filter(self):
        mode = self._filter_mode.get()
        for item in self.tree.get_children():
            self.tree.delete(item)

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
            self.tree.insert(
                "",
                tk.END,
                values=(row["status"], row["epc"], row["rssi"]),
                tags=(tag,),
            )

    def _on_result_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if len(vals) < 3:
            return
        status, epc, rssi = vals[0], vals[1], vals[2]
        self.detail_epc_var.set(epc)
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
