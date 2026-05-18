"""Interfaz gráfica principal (Tkinter): inventario, rastreo, escritura de etiqueta y modo HID.

Pantalla de diseño: 480×320 (por ejemplo Waveshare en Raspberry Pi).
"""

import argparse
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
import time

from rfid_inventory.app import Escaner
from rfid_inventory.app.inventory_presenter import construir_filas_resultado
from rfid_inventory.app.inventory_service import ServicioInventario
from rfid_inventory.app.proximity_tracker import RastreadorProximidad
from rfid_inventory.app.tag_writer_service import ServicioEscrituraEtiquetas
from rfid_inventory.app.tracking_service import ServicioRastreo
from rfid_inventory.app.app_config import cargar_configuracion_aplicacion, hardware_escritura_resuelto
from rfid_inventory.catalog.catalog_loader import (
    aplanar_ubicaciones_a_mapa_epcs,
    cargar_ubicaciones_anidadas_desde_json,
    rutas_catalogo_por_defecto,
)
from rfid_inventory.catalog.epc12_codec import epc12_hex_a_codigo_activo
from rfid_inventory.drivers import LectorR200
from rfid_inventory.ui.ui_formatters import (
    codigo_activo_o_guion_desde_epc,
    estado_escritura_programada,
    mostrar_activo_desde_epc,
)


def _ubicaciones_ejemplo_anidadas():
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


def _texto_ubicacion(edificio, sala):
    return "{0} · {1}".format(edificio, sala)


class AplicacionInventario(tk.Tk):
    _MAX_LINEAS_LOG_ESCANEO = 3

    def __init__(self, *, kiosk: bool = False):
        super().__init__()
        self._modo_kiosk = bool(kiosk)
        self.title("Inventario RFID")
        self.geometry("480x320")
        self.minsize(480, 320)
        if self._modo_kiosk:
            self._aplicar_modo_kiosk_pantalla()

        self._escaneo_inicio_ms = None
        self._tarea_temporizador_escaneo = None
        self._tarea_inicio_pistoleo = None
        self._conjunto_epcs_esperados = set()
        self._lineas_log_escaneo = []
        self._arbol_escaneo_items_esperados = {}
        self._arbol_escaneo_items_nuevos = {}

        self._ubicacion_texto_resultados = ""
        self._filas_resultados_inventario = []
        self._resultado_iid_a_epc = {}
        self._ultima_muestra_escaneo = None
        self._modo_filtro_resultados = tk.StringVar(value="todos")

        self._lector = LectorR200()
        self._escaner = Escaner(self._lector)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        self._configuracion = cargar_configuracion_aplicacion(repo_root)
        rutas_catalogo = rutas_catalogo_por_defecto(
            repo_root, prefer_web_dir=self._configuracion.catalogo.preferir_directorio_web
        )
        self._ubicaciones_anidadas = (
            cargar_ubicaciones_anidadas_desde_json(rutas_catalogo) or _ubicaciones_ejemplo_anidadas()
        )
        self._mapa_ubicacion_a_epcs = aplanar_ubicaciones_a_mapa_epcs(self._ubicaciones_anidadas)
        self._servicio_inventario = ServicioInventario(self._mapa_ubicacion_a_epcs, self._escaner)

        self._servicio_rastreo = ServicioRastreo(self._ubicaciones_anidadas)
        self._rastreador_proximidad = RastreadorProximidad(alpha=0.25)
        self._servicio_escritura = ServicioEscrituraEtiquetas(
            usar_hardware=hardware_escritura_resuelto(self._configuracion)
        )
        self._forzar_sim_proximidad = bool(self._configuracion.funciones.forzar_simulacion_proximidad)
        self._proximidad_activa = False
        self._tarea_ui_proximidad = None
        self._gatt_detenido_automaticamente_para_inventario = False
        self._advertido_fallo_sudo_gatt = False

        self._inicializar_estilos()

        self.contenedor = tk.Frame(self)
        self.contenedor.pack(fill="both", expand=True)

        self._marco_menu = None
        self._marco_inicio = None
        self._marco_conexion = None
        self._marco_ubicacion = None
        self._marco_escaneo = None
        self._marco_resultados = None
        self._marco_detalle = None
        self._marco_rastreo = None
        self._marco_escritura = None
        self._marco_hid = None

        # A dónde avanzar después de conectar (menú o pantalla de ubicación)
        self._marco_despues_conexion = "menu"

        self._construir_inicio()
        self._construir_menu()
        self._construir_conexion()
        self._construir_ubicacion()
        self._construir_escaneo()
        self._construir_resultados()
        self._construir_detalle()
        self._construir_rastreo()
        self._construir_escritura()
        self._construir_hid()

        self._mostrar_marco("inicio")

        self.protocol("WM_DELETE_WINDOW", self.al_cerrar_ventana)
        if self._modo_kiosk:
            self._kiosk_bind_elevar_teclado_en_focos_texto()

    def _aplicar_modo_kiosk_pantalla(self) -> None:
        """Kiosco en Linux: sin decoración de ventana y a pantalla completa (no EWMH fullscreen).

        ``-fullscreen`` de Tk suele dejar el teclado del sistema detrás; ``zoomed``
        deja barra del gestor y botón minimizar. Sin decoración (overrideredirect)
        cubre el área útil; conviene desactivar el panel del escritorio (lxpanel).

        Opcional: ``sudo apt install xdotool`` para intentar traer el teclado
        virtual al frente al enfocar un campo (ver ``_kiosk_elevar_teclado_xdotool``).
        """
        try:
            self.update_idletasks()
        except tk.TclError:
            pass
        if os.name == "posix":
            try:
                sw = max(int(self.winfo_screenwidth()), 480)
                sh = max(int(self.winfo_screenheight()), 320)
                self.resizable(False, False)
                self.minsize(sw, sh)
                self.maxsize(sw, sh)
                self.overrideredirect(True)
                self.geometry(f"{sw}x{sh}+0+0")
                return
            except tk.TclError:
                pass
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            pass

    def _kiosk_bind_elevar_teclado_en_focos_texto(self) -> None:
        if os.name != "posix" or not self._modo_kiosk:
            return
        self._kiosk_tarea_elevar_teclado = None

        def en_focus(_event=None):
            w = self.focus_get()
            if w is None:
                return
            wc = w.winfo_class()
            if wc not in ("Entry", "Text", "TEntry"):
                return
            if self._kiosk_tarea_elevar_teclado is not None:
                try:
                    self.after_cancel(self._kiosk_tarea_elevar_teclado)
                except Exception:
                    pass
            self._kiosk_tarea_elevar_teclado = self.after(280, self._kiosk_elevar_teclado_xdotool)

        self.bind_all("<FocusIn>", en_focus, add="+")

    def _kiosk_elevar_teclado_xdotool(self) -> None:
        self._kiosk_tarea_elevar_teclado = None
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return
        patrones = [
            ("classname", "Onboard"),
            ("class", "Onboard"),
            ("classname", "onboard"),
            ("name", "Onboard"),
            ("classname", "matchbox-keyboard"),
            ("classname", "Matchbox-keyboard"),
            ("classname", "squeekboard"),
            ("classname", "Squeekboard"),
            ("class", "wf-osk"),
        ]
        for onlyvisible in (True, False):
            for kind, name in patrones:
                try:
                    cmd = [xdotool, "search"]
                    if onlyvisible:
                        cmd.append("--onlyvisible")
                    cmd.extend([f"--{kind}", name])
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                    if r.returncode != 0 or not (r.stdout or "").strip():
                        continue
                    for wid in (r.stdout or "").strip().splitlines():
                        wid = wid.strip()
                        if not wid:
                            continue
                        subprocess.run(
                            [xdotool, "windowactivate", wid],
                            capture_output=True,
                            timeout=2,
                        )
                        subprocess.run(
                            [xdotool, "windowraise", wid],
                            capture_output=True,
                            timeout=2,
                        )
                    return
                except Exception:
                    continue

    def _habilitar_publicidad_ble_y_abrir_modo_hid(self):
        """Activa advertising BLE (btmgmt) y abre la pantalla HID.

        La UI cambia al instante. El cierre del serial (puede tardar en el driver
        USB) y el ``systemctl start`` van en hilos aparte para no congelar Tkinter.
        Requiere sudoers NOPASSWD para el usuario (ej. `user`) en btmgmt.
        """
        self._mostrar_marco("modo_hid")
        threading.Thread(target=self._hid_hilo_cerrar_serial_y_continuar, daemon=True).start()

    def _hid_hilo_cerrar_serial_y_continuar(self) -> None:
        """Cierra el lector fuera del hilo de Tk: ``close()`` del USB a veces bloquea mucho tiempo."""
        try:
            self._lector.cerrar()
        except Exception:
            pass
        try:
            self.after(0, self._hid_en_main_despues_cerrar_serial)
        except Exception:
            pass

    def _hid_en_main_despues_cerrar_serial(self) -> None:
        """Tras soltar el USB: detiene escáner/temporizador en el hilo de la UI."""
        self._cancelar_inicio_pistoleo_pendiente()
        self._detener_temporizador_escaneo()
        self._ajustar_controles_escaneo_activo(False)
        try:
            self._escaner.reanudar()
            self._escaner.detener()
        except Exception:
            pass
        try:
            self._proximidad_detener()
        except Exception:
            pass

        def hilo_systemctl_start():
            self._intentar_reanudar_gatt_si_lo_pausamos()

        threading.Thread(target=hilo_systemctl_start, daemon=True).start()

        if os.name != "posix":
            return

        def hilo_trabajador():
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

        threading.Thread(target=hilo_trabajador, daemon=True).start()

    def _sugerir_puerto_serial_pi(self) -> str:
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
            # Respaldo: /dev/ttyUSB* y luego /dev/ttyACM*
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

    def _normalizar_texto_puerto_serial(self, puerto: str) -> str:
        p = (puerto or "").strip()
        if not p:
            return ""
        pl = p.lower()
        if pl.startswith("/dev/ttyusb"):
            return "/dev/ttyUSB" + p[len("/dev/ttyusb") :]
        if pl.startswith("/dev/ttyacm"):
            return "/dev/ttyACM" + p[len("/dev/ttyacm") :]
        return p

    def _rfid_port_en_default_hid_gatt(self) -> str | None:
        ruta = "/etc/default/rfid-hid-gatt"
        if not os.path.isfile(ruta):
            return None
        try:
            with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    line = raw.split("#", 1)[0].strip()
                    if line.upper().startswith("RFID_PORT="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        return val if val else None
        except OSError:
            return None
        return None

    def _servicio_rfid_hid_gatt_activo(self) -> bool:
        if os.name != "posix":
            return False
        systemctl = shutil.which("systemctl")
        if not systemctl:
            return False
        try:
            r = subprocess.run(
                [systemctl, "is-active", "rfid-hid-gatt.service"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            return r.returncode == 0 and (r.stdout or "").strip() == "active"
        except Exception:
            return False

    def _mismo_dispositivo_serial(self, a: str, b: str) -> bool:
        if not a or not b:
            return False
        ca = self._normalizar_texto_puerto_serial(a)
        cb = self._normalizar_texto_puerto_serial(b)
        if ca == cb:
            return True
        try:
            return os.path.exists(ca) and os.path.exists(cb) and os.path.samefile(ca, cb)
        except OSError:
            try:
                return os.path.realpath(ca) == os.path.realpath(cb)
            except OSError:
                return False

    def _hay_conflicto_hid_gatt_puerto(self) -> bool:
        """True si rfid-hid-gatt está activo y RFID_PORT apunta al mismo dispositivo que la GUI."""
        if not self._servicio_rfid_hid_gatt_activo():
            return False
        puerto_gui = self._normalizar_texto_puerto_serial(self.var_puerto_serial.get())
        def_port = self._rfid_port_en_default_hid_gatt()
        if not def_port:
            return False
        return self._mismo_dispositivo_serial(puerto_gui, def_port)

    def _sudo_systemctl_gatt(self, accion: str) -> bool:
        """accion: 'stop' o 'start'. Requiere sudoers NOPASSWD para systemctl."""
        if os.name != "posix":
            return False
        systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
        try:
            r = subprocess.run(
                ["sudo", "-n", systemctl, accion, "rfid-hid-gatt.service"],
                capture_output=True,
                text=True,
                timeout=22,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _asegurar_puerto_sin_servicio_gatt_conflicto(self) -> None:
        """Detiene rfid-hid-gatt sin pedir contraseña si está configurado sudo -n (instalación típica)."""
        if not self._hay_conflicto_hid_gatt_puerto():
            return
        if self._sudo_systemctl_gatt("stop"):
            self._gatt_detenido_automaticamente_para_inventario = True
            time.sleep(0.25)
            return
        if self._advertido_fallo_sudo_gatt:
            return
        self._advertido_fallo_sudo_gatt = True
        messagebox.showwarning(
            "Puerto serial compartido",
            "El servicio «rfid-hid-gatt» usa el mismo puerto que el inventario.\n\n"
            "No pude detenerlo solo (hace falta permitir systemctl sin contraseña).\n"
            "En la Pi, con visudo, agrega una línea como (cambia `user` por tu usuario):\n\n"
            "  user ALL=(root) NOPASSWD: /usr/bin/systemctl stop rfid-hid-gatt.service, "
            "/usr/bin/systemctl start rfid-hid-gatt.service\n\n"
            "O detén el servicio a mano antes de pistoleo:\n"
            "  sudo systemctl stop rfid-hid-gatt",
        )

    def _intentar_reanudar_gatt_si_lo_pausamos(self) -> None:
        """Al volver al modo Bluetooth, reactiva el servicio si esta app lo había parado."""
        if not self._gatt_detenido_automaticamente_para_inventario:
            return
        if self._sudo_systemctl_gatt("start"):
            self._gatt_detenido_automaticamente_para_inventario = False

    def _clave_ubicacion_actual(self):
        return _texto_ubicacion(self.var_edificio.get(), self.var_sala.get())

    def _inicializar_estilos(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        # Ajuste compacto para 480×320 (Waveshare): balance legibilidad/espacio.
        style.configure("Treeview", rowheight=16)
        style.configure("Treeview.Heading", font=("", 8, "bold"))
        style.configure("Handheld.TButton", font=("", 10))
        style.configure("HandheldBig.TButton", font=("", 12))

    def _mostrar_marco(self, nombre_marco):
        for w in self.contenedor.winfo_children():
            w.pack_forget()
        if nombre_marco == "inicio":
            self._marco_inicio.pack(fill="both", expand=True)
        elif nombre_marco == "menu":
            self._marco_menu.pack(fill="both", expand=True)
        elif nombre_marco == "conexion":
            self._marco_conexion.pack(fill="both", expand=True)
        elif nombre_marco == "ubicacion":
            self._marco_ubicacion.pack(fill="both", expand=True)
        elif nombre_marco == "escaneo":
            self._marco_escaneo.pack(fill="both", expand=True)
        elif nombre_marco == "resultados":
            self._marco_resultados.pack(fill="both", expand=True)
        elif nombre_marco == "detalle":
            self._marco_detalle.pack(fill="both", expand=True)
        elif nombre_marco == "rastreo":
            self._marco_rastreo.pack(fill="both", expand=True)
        elif nombre_marco == "escritura":
            self._marco_escritura.pack(fill="both", expand=True)
        elif nombre_marco == "modo_hid":
            self._marco_hid.pack(fill="both", expand=True)

    def _construir_inicio(self):
        self._marco_inicio = tk.Frame(self.contenedor)

        tk.Label(
            self._marco_inicio,
            text="Sistema de Inventario RFID",
            font=("", 15, "bold"),
        ).pack(pady=(28, 6))

        tk.Label(
            self._marco_inicio,
            text="Pantalla 480×320 · Raspberry Pi",
            font=("", 8),
            fg="#555",
        ).pack(pady=(0, 14))

        ttk.Button(
            self._marco_inicio,
            text="Iniciar",
            style="HandheldBig.TButton",
            command=lambda: self._abrir_pantalla_conexion(siguiente_marco="menu"),
        ).pack(fill="x", padx=28, ipady=6)

    def _construir_menu(self):
        self._marco_menu = tk.Frame(self.contenedor)

        tk.Label(
            self._marco_menu,
            text="Sistema de Inventario RFID",
            font=("", 14, "bold"),
        ).pack(pady=(6, 2))
        tk.Label(
            self._marco_menu,
            text="Elige una opción",
            font=("", 8),
            fg="#555",
        ).pack(pady=(0, 6))

        def boton_grande(parent, text, command):
            b = ttk.Button(
                parent,
                text=text,
                style="HandheldBig.TButton",
                command=command,
            )
            b.pack(fill="x", padx=14, pady=3, ipady=4)
            return b

        boton_grande(
            self._marco_menu,
            "Inventario en ubicación",
            self._entrar_inventario_ubicacion,
        )
        boton_grande(
            self._marco_menu,
            "Rastrear activo",
            self._entrar_rastreo,
        )
        boton_grande(
            self._marco_menu,
            "Escribir etiqueta",
            lambda: self._mostrar_marco("escritura"),
        )
        boton_grande(
            self._marco_menu,
            "Modo Lector Bluetooth",
            self._habilitar_publicidad_ble_y_abrir_modo_hid,
        )

    def _construir_conexion(self):
        """Lector serial: conectar y seguir a selección de ubicación (flujograma: inventario del lugar)."""
        self._marco_conexion = tk.Frame(self.contenedor)

        ttk.Button(
            self._marco_conexion,
            text="Inicio",
            style="Handheld.TButton",
            command=lambda: self._mostrar_marco("inicio"),
        ).pack(anchor="w", padx=8, pady=(4, 0))

        tk.Label(
            self._marco_conexion,
            text="Inventario en ubicación",
            font=("", 13, "bold"),
        ).pack(pady=(3, 2))

        tk.Label(
            self._marco_conexion,
            text="Conecta el lector RFID al puerto",
            font=("", 8),
            wraplength=440,
            justify="center",
        ).pack(pady=(0, 6))

        row = tk.Frame(self._marco_conexion)
        row.pack(fill="x", padx=12, pady=3)

        tk.Label(row, text="Puerto:", font=("", 10)).pack(side="left")
        # Default: si estamos en Pi, sugiere /dev/serial/by-id; si no, COM5.
        default_port = (
            self._sugerir_puerto_serial_pi()
            if os.name == "posix"
            else self._configuracion.serie.puerto_defecto_windows
        )
        if os.name == "posix" and not default_port:
            default_port = self._configuracion.serie.puerto_defecto_pi_respaldo
        self.var_puerto_serial = tk.StringVar(value=default_port or ("COM5" if os.name != "posix" else "/dev/ttyUSB0"))
        tk.Entry(row, textvariable=self.var_puerto_serial, width=20, font=("", 10)).pack(side="left", padx=(4, 6))

        def poner_puerto_windows():
            self.var_puerto_serial.set("COM5")

        def poner_puerto_pi():
            p = self._sugerir_puerto_serial_pi()
            if p:
                self.var_puerto_serial.set(p)
            else:
                self.var_puerto_serial.set("/dev/ttyUSB0")

        ttk.Button(row, text="Windows", style="Handheld.TButton", command=poner_puerto_windows).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Raspberry Pi", style="Handheld.TButton", command=poner_puerto_pi).pack(side="left", padx=(0, 0))

        # Segunda fila: baud + conectar (evita overflow horizontal en 480×320)
        row2 = tk.Frame(self._marco_conexion)
        row2.pack(fill="x", padx=12, pady=(0, 3))

        tk.Label(row2, text="Baud:", font=("", 10)).pack(side="left")
        self.var_baudios = tk.StringVar(value=str(self._configuracion.serie.baudios))
        tk.Entry(row2, textvariable=self.var_baudios, width=8, font=("", 10)).pack(side="left", padx=(4, 8))

        self.btn_conectar_lector = ttk.Button(row2, text="Conectar", command=self.conectar_lector, style="HandheldBig.TButton")
        self.btn_conectar_lector.pack(side="left", fill="x", expand=True, padx=(0, 0), ipady=2)

        self.var_estado_lector = tk.StringVar(value="Lector: desconectado")
        tk.Label(
            self._marco_conexion, textvariable=self.var_estado_lector, font=("", 8), wraplength=440, justify="center"
        ).pack(fill="x", padx=12, pady=(6, 6))

        self.btn_continuar = ttk.Button(
            self._marco_conexion,
            text="Continuar",
            style="HandheldBig.TButton",
            command=self._continuar_tras_conexion,
            state="disabled",
        )
        self.btn_continuar.pack(pady=4, ipadx=16, ipady=6)

    def _abrir_pantalla_conexion(self, siguiente_marco: str):
        """Pantalla de conexión reutilizable: al conectar, avanza a siguiente_marco."""
        self._marco_despues_conexion = siguiente_marco or "menu"
        # Texto del botón de continuar según el flujo
        if self._marco_despues_conexion == "ubicacion":
            self.btn_continuar.config(text="Continuar (ubicación)")
        else:
            self.btn_continuar.config(text="Ir al menú")

        # Si ya está conectado, habilita continuar sin reconectar
        if self._lector.connected:
            self.var_estado_lector.set("Lector: conectado")
            self.btn_conectar_lector.config(state="disabled")
            self.btn_continuar.config(state="normal")
        else:
            self.var_estado_lector.set("Lector: desconectado")
            self.btn_conectar_lector.config(state="normal")
            self.btn_continuar.config(state="disabled")

        self._mostrar_marco("conexion")

    def _continuar_tras_conexion(self):
        if self._marco_despues_conexion == "ubicacion":
            self._mostrar_marco("ubicacion")
        else:
            self._mostrar_marco("menu")

    def _entrar_inventario_ubicacion(self):
        """Entrar al módulo de inventario por ubicación."""
        if self._lector.connected:
            self._mostrar_marco("ubicacion")
        else:
            self._abrir_pantalla_conexion(siguiente_marco="ubicacion")

    def _construir_ubicacion(self):
        self._marco_ubicacion = tk.Frame(self.contenedor)

        tk.Label(self._marco_ubicacion, text="Ubicación del inventario", font=("", 11, "bold")).pack(
            anchor="w", padx=12, pady=(8, 6)
        )

        row_b = tk.Frame(self._marco_ubicacion)
        row_b.pack(fill="x", padx=12, pady=4)
        tk.Label(row_b, text="Edificio:", font=("", 10)).pack(anchor="w")
        buildings = sorted(list(self._ubicaciones_anidadas.keys()))
        self.var_edificio = tk.StringVar(value=buildings[0])
        self.combo_edificio = ttk.Combobox(
            row_b,
            textvariable=self.var_edificio,
            values=buildings,
            state="readonly",
            width=32,
            font=("", 10),
        )
        self.combo_edificio.pack(fill="x", pady=(2, 0))

        row_r = tk.Frame(self._marco_ubicacion)
        row_r.pack(fill="x", padx=12, pady=6)
        tk.Label(row_r, text="Cubículo / lab / sala:", font=("", 10)).pack(anchor="w")
        self.var_sala = tk.StringVar()
        first_rooms = sorted(list(self._ubicaciones_anidadas[buildings[0]].keys()))
        self.var_sala.set(first_rooms[0])
        self.combo_sala = ttk.Combobox(
            row_r,
            textvariable=self.var_sala,
            values=first_rooms,
            state="readonly",
            width=32,
            font=("", 10),
        )
        self.combo_sala.pack(fill="x", pady=(2, 0))

        self.combo_edificio.bind("<<ComboboxSelected>>", self._al_seleccionar_edificio)
        self.combo_sala.bind("<<ComboboxSelected>>", lambda _e: self._actualizar_pista_ubicacion())

        self.var_pista_ubicacion = tk.StringVar(value="")
        tk.Label(self._marco_ubicacion, textvariable=self.var_pista_ubicacion, font=("", 8), fg="#444", wraplength=440).pack(
            fill="x", padx=12, pady=(3, 6)
        )
        self._actualizar_pista_ubicacion()

        row_btns = tk.Frame(self._marco_ubicacion)
        row_btns.pack(fill="x", side="bottom", pady=8)

        ttk.Button(
            row_btns,
            text="Atrás",
            style="Handheld.TButton",
            command=lambda: self._mostrar_marco("menu"),
        ).pack(side="left", padx=8)

        self.btn_ir_escaneo = ttk.Button(
            row_btns,
            text="Siguiente",
            style="HandheldBig.TButton",
            command=self.ir_a_pantalla_escaneo,
        )
        self.btn_ir_escaneo.pack(side="right", padx=8, ipadx=8, ipady=4)

    def _actualizar_pista_ubicacion(self):
        self.var_pista_ubicacion.set("Selección: {0}".format(self._clave_ubicacion_actual()))

    def _al_seleccionar_edificio(self, event=None):
        ed = self.var_edificio.get()
        rooms = sorted(list(self._ubicaciones_anidadas.get(ed, {}).keys()))
        self.combo_sala["values"] = rooms
        if rooms:
            self.var_sala.set(rooms[0])
        self._actualizar_pista_ubicacion()
        
    def _construir_escaneo(self):
        self._marco_escaneo = tk.Frame(self.contenedor)

        top = tk.Frame(self._marco_escaneo)
        top.pack(fill="x", padx=10, pady=(3, 1))

        tk.Label(
            top,
            text="Inicia el pistoleo cuando quieras",
            font=("", 8, "bold"),
            fg="#2E7D32",
        ).pack(anchor="w", fill="x")

        self.var_linea_ubicacion_escaneo = tk.StringVar(value="Ubicación: —")
        self.var_linea_tiempo_escaneo = tk.StringVar(value="Tiempo: 0.0 s")
        self.var_linea_conteos_escaneo = tk.StringVar(value="Esperados: 0 | Leídos únicos: 0")

        tk.Label(top, textvariable=self.var_linea_ubicacion_escaneo, font=("", 9), anchor="w").pack(fill="x")
        tk.Label(top, textvariable=self.var_linea_conteos_escaneo, font=("", 9), anchor="w").pack(fill="x")

        mid = tk.Frame(self._marco_escaneo)
        mid.pack(fill="both", expand=True, padx=8, pady=2)

        tree_wrap = tk.Frame(mid)
        tree_wrap.pack(fill="both", expand=True, pady=(2, 2))

        self.arbol_escaneo = ttk.Treeview(
            tree_wrap,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=9,
        )
        self.arbol_escaneo.heading("status", text="Estado")
        self.arbol_escaneo.heading("epc", text="Activo")
        self.arbol_escaneo.heading("rssi", text="RSSI")
        self.arbol_escaneo.column("status", width=88, anchor="center")
        self.arbol_escaneo.column("epc", width=250, anchor="w")
        self.arbol_escaneo.column("rssi", width=48, anchor="center")
        vsb_s = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.arbol_escaneo.yview)
        self.arbol_escaneo.configure(yscrollcommand=vsb_s.set)
        self.arbol_escaneo.pack(side="left", fill="both", expand=True)
        vsb_s.pack(side="right", fill="y")
        # Estilos para los tags
        self.arbol_escaneo.tag_configure("encontrado", background="#F4F4F4")
        self.arbol_escaneo.tag_configure("faltante", background="#FF7F7F")
        self.arbol_escaneo.tag_configure("nuevo", background="#90EE90")

        # Log interno (no visible): lo mantenemos para debug sin ocupar espacio en 480×320
        self.lista_log_escaneo = tk.Listbox(self._marco_escaneo, height=self._MAX_LINEAS_LOG_ESCANEO, font=("Consolas", 8))

        row_pistol = tk.Frame(self._marco_escaneo)
        row_pistol.pack(fill="x", side="bottom", pady=(2, 2))
        # Botones para el pistoleo 
        self.btn_iniciar_pistoleo = tk.Button(
            row_pistol,
            text="Presionar Trigger",
            font=("", 9, "bold"),
            bg="#2E7D32",
            fg="white",
            activebackground="#1B5E20",
            activeforeground="white",
            relief="flat",
            command=self.iniciar_pistoleo,
        )
        self.btn_iniciar_pistoleo.pack(side="left", fill="x", expand=True, padx=(10, 6), ipady=2)

        self.btn_detener_escaneo = tk.Button(
            row_pistol,
            text="Detener",
            font=("", 9, "bold"),
            bg="#C62828",
            fg="white",
            activebackground="#B71C1C",
            activeforeground="white",
            relief="flat",
            command=self.detener_escaneo,
        )
        self.btn_detener_escaneo.pack(side="right", fill="x", expand=True, padx=(6, 10), ipady=2)

        row = tk.Frame(self._marco_escaneo)
        row.pack(fill="x", side="bottom", pady=(0, 4))

        self.btn_pausar_escaneo = ttk.Button(
            row,
            text="Pausar",
            style="Handheld.TButton",
            command=self._alternar_pausa_escaneo,
        )
        self.btn_pausar_escaneo.pack(side="left", padx=(10, 4), ipadx=4, ipady=2)

        self.btn_cancelar_escaneo = ttk.Button(
            row,
            text="Cancelar",
            style="Handheld.TButton",
            command=self.cancelar_escaneo,
        )
        self.btn_cancelar_escaneo.pack(side="left", padx=4, ipadx=4, ipady=2)

        self._ajustar_controles_escaneo_activo(False)
                
    def _construir_resultados(self):
        self._marco_resultados = tk.Frame(self.contenedor)

        head = tk.Frame(self._marco_resultados)
        head.pack(fill="x", padx=10, pady=(8, 4))

        self.var_linea_ubicacion_resultados = tk.StringVar(value="Ubicación: ")
        self.var_linea_estadisticas_resultados = tk.StringVar(value="Esperados: 0 | OK: 0 | Faltan: 0 | Nuevos: 0")

        tk.Label(head, textvariable=self.var_linea_ubicacion_resultados, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(head, textvariable=self.var_linea_estadisticas_resultados, font=("", 10), anchor="w").pack(fill="x")

        filt = tk.Frame(self._marco_resultados)
        filt.pack(fill="x", padx=8, pady=(2, 4))

        tk.Label(filt, text="Ver:", font=("", 9)).pack(side="left", padx=(0, 6))
        for val, label in (("todos", "Todos"), ("faltantes", "Solo faltantes"), ("nuevos", "Solo nuevos")):
            ttk.Radiobutton(
                filt,
                text=label,
                value=val,
                variable=self._modo_filtro_resultados,
                command=self._al_cambiar_filtro_resultados,
            ).pack(side="left", padx=2)

        tree_frame = tk.Frame(self._marco_resultados)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
            
        self.arbol_resultados = ttk.Treeview(
            tree_frame,
            columns=("status", "epc", "rssi"),
            show="headings",
            height=7,
        )
        self.arbol_resultados.heading("status", text="Estado")
        self.arbol_resultados.heading("epc", text="Activo")
        self.arbol_resultados.heading("rssi", text="RSSI")
        self.arbol_resultados.column("status", width=96, anchor="center")
        self.arbol_resultados.column("epc", width=270, anchor="w")
        self.arbol_resultados.column("rssi", width=52, anchor="center")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.arbol_resultados.yview)
        self.arbol_resultados.configure(yscrollcommand=vsb.set)
        self.arbol_resultados.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        self.arbol_resultados.tag_configure("encontrado", background="#F4F4F4")
        self.arbol_resultados.tag_configure("faltante", background="#FF7F7F")
        self.arbol_resultados.tag_configure("nuevo", background="#90EE90")

        self.arbol_resultados.bind("<Double-1>", self._al_doble_clic_resultado)

        legend = tk.Frame(self._marco_resultados)
        legend.pack(fill="x", padx=8)
        self._chip_leyenda(legend, "ENCONTRADO", "#F4F4F4").pack(side="left", padx=(0, 4))
        self._chip_leyenda(legend, "NO ESCANEADO", "#FF7F7F").pack(side="left", padx=(0, 4))
        self._chip_leyenda(legend, "ACTIVO NUEVO", "#90EE90").pack(side="left")

        row = tk.Frame(self._marco_resultados)
        row.pack(fill="x", pady=(6, 10))

        btns = tk.Frame(row)
        btns.pack(fill="x", padx=12)

        ttk.Button(
            btns,
            text="Nuevo escaneo",
            style="HandheldBig.TButton",
            command=self._nuevo_escaneo_desde_resultados,
        ).pack(side="left", fill="x", expand=True, ipadx=8, ipady=4, padx=(0, 6))

        ttk.Button(
            btns,
            text="Subir reporte",
            style="HandheldBig.TButton",
            command=self._exportar_tipo_ubicacion_actualizado,
        ).pack(side="left", fill="x", expand=True, ipadx=8, ipady=4, padx=(0, 6))

        ttk.Button(
            btns,
            text="Menú",
            style="HandheldBig.TButton",
            command=self._volver_menu_desde_resultados,
        ).pack(side="right", fill="x", expand=True, ipadx=8, ipady=4, padx=(6, 0))

    def _construir_detalle(self):
        self._marco_detalle = tk.Frame(self.contenedor)

        tk.Label(self._marco_detalle, text="Detalle de activo", font=("", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 8))

        box = tk.Frame(self._marco_detalle)
        box.pack(fill="both", expand=True, padx=12)

        self.var_detalle_epc = tk.StringVar(value="")
        self.var_detalle_estado = tk.StringVar(value="")
        self.var_detalle_ubicacion = tk.StringVar(value="")
        self.var_detalle_rssi = tk.StringVar(value="")

        def fila_detalle(lbl, var):
            r = tk.Frame(box)
            r.pack(fill="x", pady=4)
            tk.Label(r, text=lbl, font=("", 9), width=18, anchor="w").pack(side="left")
            tk.Label(r, textvariable=var, font=("", 9), wraplength=320, justify="left", anchor="w").pack(side="left")

        self.var_detalle_codigo_activo = tk.StringVar(value="")
        fila_detalle("Activo:", self.var_detalle_codigo_activo)
        fila_detalle("EPC:", self.var_detalle_epc)
        fila_detalle("Estado:", self.var_detalle_estado)
        fila_detalle("Ubicación esperada:", self.var_detalle_ubicacion)
        fila_detalle("Última RSSI:", self.var_detalle_rssi)

        ttk.Button(
            self._marco_detalle,
            text="Volver",
            style="HandheldBig.TButton",
            command=lambda: self._mostrar_marco("resultados"),
        ).pack(side="bottom", pady=16, ipadx=16, ipady=6)

        ttk.Button(
            self._marco_detalle,
            text="Menú",
            style="Handheld.TButton",
            command=self._volver_menu_desde_resultados,
        ).pack(side="bottom", pady=(0, 10), ipadx=10, ipady=2)

    def _volver_menu_desde_resultados(self):
        """Salir del flujo de inventario a menú principal."""
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reanudar()
        self._escaner.detener()
        self._detener_temporizador_escaneo()
        self._ajustar_controles_escaneo_activo(False)
        self._mostrar_marco("menu")

    def _construir_rastreo(self):
        self._marco_rastreo = tk.Frame(self.contenedor)
        ttk.Button(
            self._marco_rastreo,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._mostrar_marco("menu"),
        ).pack(anchor="w", padx=8, pady=6)
        tk.Label(
            self._marco_rastreo,
            text="Rastrear activo",
            font=("", 13, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 4))

        tk.Label(
            self._marco_rastreo,
            text="Busca por código de activo.",
            font=("", 8),
            wraplength=440,
            justify="left",
            fg="#444",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        row = tk.Frame(self._marco_rastreo)
        row.pack(fill="x", padx=12, pady=3)

        self.var_rastreo_busqueda = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.var_rastreo_busqueda, font=("", 10)).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row, text="Buscar", style="Handheld.TButton", command=self._rastreo_buscar).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Limpiar", style="Handheld.TButton", command=lambda: self.var_rastreo_busqueda.set("")).pack(side="left")

        box = tk.Frame(self._marco_rastreo)
        box.pack(fill="both", expand=True, padx=12, pady=(4, 4))

        self.var_rastreo_activo = tk.StringVar(value="Activo: —")
        self.var_rastreo_epc = tk.StringVar(value="EPC: —")
        self.var_rastreo_ubicacion = tk.StringVar(value="Ubicación esperada: —")

        tk.Label(box, textvariable=self.var_rastreo_activo, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(box, textvariable=self.var_rastreo_epc, font=("", 8), fg="#444", anchor="w").pack(fill="x", pady=(1, 4))
        tk.Label(box, textvariable=self.var_rastreo_ubicacion, font=("", 9), wraplength=440, justify="left", anchor="w").pack(
            fill="x"
        )

        # Proximidad (frío/caliente)
        prox = tk.Frame(self._marco_rastreo)
        prox.pack(fill="x", padx=12, pady=(0, 4))

        self.var_proximidad_estado = tk.StringVar(value="Proximidad: —")
        self.var_proximidad_rssi = tk.StringVar(value="RSSI: —")
        tk.Label(prox, textvariable=self.var_proximidad_estado, font=("", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(prox, textvariable=self.var_proximidad_rssi, font=("", 8), fg="#444", anchor="w").pack(fill="x", pady=(1, 4))

        self.barra_proximidad = ttk.Progressbar(prox, orient="horizontal", mode="determinate", maximum=100)
        self.barra_proximidad.pack(fill="x")

        row3 = tk.Frame(self._marco_rastreo)
        row3.pack(fill="x", padx=12, pady=(3, 6))
        self.btn_proximidad_iniciar = ttk.Button(row3, text="Iniciar rastreo", style="HandheldBig.TButton", command=self._proximidad_iniciar)
        self.btn_proximidad_iniciar.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)
        self.btn_proximidad_detener = ttk.Button(row3, text="Detener", style="HandheldBig.TButton", command=self._proximidad_detener, state="disabled")
        self.btn_proximidad_detener.pack(side="right", fill="x", expand=True, padx=(6, 0), ipady=2)

    def _entrar_rastreo(self):
        # Evita que el scanner quede leyendo en background.
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reanudar()
        self._escaner.detener()
        self._detener_temporizador_escaneo()
        self._ajustar_controles_escaneo_activo(False)
        self._mostrar_marco("rastreo")
        self._proximidad_detener()

    def _rastreo_normalizar_entrada(self, texto: str) -> tuple[str, str]:
        return self._servicio_rastreo.normalizar_entrada(texto)

    def _rastreo_buscar(self):
        resultado_rastreo = self._servicio_rastreo.rastrear(self.var_rastreo_busqueda.get())
        if not resultado_rastreo:
            messagebox.showinfo("Rastreo", "Escribe un EPC (hex) o un código de activo.")
            return
        self.var_rastreo_activo.set("Activo: {0}".format(resultado_rastreo.codigo_activo or "(desconocido)"))
        self.var_rastreo_epc.set("EPC: {0}".format(resultado_rastreo.epc_en_hex))
        if not resultado_rastreo.ubicaciones:
            self.var_rastreo_ubicacion.set("Ubicación esperada: (no encontrado en catálogo)")
        elif len(resultado_rastreo.ubicaciones) == 1:
            self.var_rastreo_ubicacion.set("Ubicación esperada: {0}".format(resultado_rastreo.ubicaciones[0]))
        else:
            ubicaciones_lista = resultado_rastreo.ubicaciones
            self.var_rastreo_ubicacion.set("Ubicación esperada: " + " | ".join(ubicaciones_lista[:4]) + (" ..." if len(ubicaciones_lista) > 4 else ""))
        # Reset de proximidad con el EPC objetivo
        self._rastreador_proximidad.reiniciar(resultado_rastreo.epc_en_hex)
        self.barra_proximidad["value"] = 0
        self.var_proximidad_estado.set("Proximidad: listo")
        self.var_proximidad_rssi.set("RSSI: —")

    def _proximidad_ajustar_controles(self, activa: bool):
        self._proximidad_activa = bool(activa)
        self.btn_proximidad_iniciar.config(state=("disabled" if activa else "normal"))
        self.btn_proximidad_detener.config(state=("normal" if activa else "disabled"))

    def _proximidad_iniciar(self):
        # Debe haber EPC objetivo
        st = self._rastreador_proximidad.estado
        if st is None or not st.epc_objetivo:
            # intenta buscar con lo que haya en input
            self._rastreo_buscar()
            st = self._rastreador_proximidad.estado
            if st is None or not st.epc_objetivo:
                return

        self._proximidad_detener()
        self._proximidad_ajustar_controles(True)

        objetivo = st.epc_objetivo
        seen = {"any": False}

        # Modo simulación (demostrativo): RSSI inventado que varía.
        if self._forzar_sim_proximidad or (not self._lector.connected):
            self.var_proximidad_estado.set("Proximidad: simulación (demo)")
            self._proximidad_iniciar_simulacion()
            self._proximidad_iniciar_actualizacion_ui()
            return

        def al_tag(tag, _idx):
            epc = (tag.epc_hex or "").lower()
            if epc != objetivo:
                return
            seen["any"] = True
            instante_ms = int(self.tk.call("clock", "milliseconds"))
            self._rastreador_proximidad.actualizar(tag.rssi, instante_ms)

        def al_error(e):
            self._al_error_escaneo(e)
            self._proximidad_detener()

        self._escaner.reiniciar()
        self._escaner.iniciar(al_leer_etiqueta=al_tag, al_error=al_error)
        self._proximidad_iniciar_actualizacion_ui()

    def _proximidad_detener(self):
        self._proximidad_ajustar_controles(False)
        # Detiene loop UI
        if self._tarea_ui_proximidad is not None:
            try:
                self.after_cancel(self._tarea_ui_proximidad)
            except Exception:
                pass
        self._tarea_ui_proximidad = None
        if getattr(self, "_tarea_sim_proximidad", None) is not None:
            try:
                self.after_cancel(self._tarea_sim_proximidad)
            except Exception:
                pass
        self._tarea_sim_proximidad = None
        # Aquí sí detenemos el escáner; en otras pantallas no forzamos stop desde este módulo.
        try:
            self._escaner.detener()
        except Exception:
            pass

    def _proximidad_iniciar_actualizacion_ui(self):
        # Actualiza barra/labels cada 200ms y marca "sin señal" si no se ve recientemente
        def actualizar_proximidad_ui():
            if not self._proximidad_activa:
                return
            estado_prox = self._rastreador_proximidad.estado
            instante_ms = int(self.tk.call("clock", "milliseconds"))
            nivel = self._rastreador_proximidad.nivel_porcentaje()
            self.barra_proximidad["value"] = nivel
            if estado_prox and estado_prox.rssi_suavizado is not None:
                self.var_proximidad_estado.set(f"Proximidad: {self._rastreador_proximidad.texto_nivel()}  ({nivel}%)")
                self.var_proximidad_rssi.set(f"RSSI: {estado_prox.rssi_suavizado:.1f} dBm (último {estado_prox.ultimo_rssi} dBm)")
                if estado_prox.ultima_lectura_ms is not None and instante_ms - estado_prox.ultima_lectura_ms > 1200:
                    self.var_proximidad_estado.set("Proximidad: Sin señal (no se ve el tag)")
            else:
                self.var_proximidad_estado.set("Proximidad: Sin señal")
                self.var_proximidad_rssi.set("RSSI: —")
            self._tarea_ui_proximidad = self.after(200, actualizar_proximidad_ui)

        self._tarea_ui_proximidad = self.after(100, actualizar_proximidad_ui)

    def _proximidad_iniciar_simulacion(self):
        # Simulación simple: random walk entre -90 y -35 dBm
        cur = {"r": -75}

        def paso_simulacion():
            if not self._proximidad_activa:
                return
            cur["r"] += random.randint(-3, 3)
            if cur["r"] < -90:
                cur["r"] = -90
            if cur["r"] > -35:
                cur["r"] = -35
            instante_ms = int(self.tk.call("clock", "milliseconds"))
            self._rastreador_proximidad.actualizar(cur["r"], instante_ms)
            self._tarea_sim_proximidad = self.after(250, paso_simulacion)

        self._tarea_sim_proximidad = self.after(250, paso_simulacion)

    def _construir_escritura(self):
        self._marco_escritura = tk.Frame(self.contenedor)
        ttk.Button(
            self._marco_escritura,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._mostrar_marco("menu"),
        ).pack(anchor="w", padx=8, pady=4)
        tk.Label(
            self._marco_escritura,
            text="Escribir tag",
            font=("", 14, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 4))

        box = tk.Frame(self._marco_escritura)
        box.pack(fill="both", expand=True, padx=12, pady=(2, 4))

        self.var_escritura_epc_actual = tk.StringVar(value="EPC actual: —")
        self.var_escritura_codigo_actual = tk.StringVar(value="Código actual (si aplica): —")
        self.var_escritura_epc_nuevo = tk.StringVar(value="EPC nuevo: —")
        self.var_escritura_estado = tk.StringVar(value="")

        tk.Label(box, textvariable=self.var_escritura_epc_actual, font=("", 9), anchor="w").pack(fill="x")
        tk.Label(box, textvariable=self.var_escritura_codigo_actual, font=("", 8), fg="#444", anchor="w").pack(
            fill="x", pady=(1, 5)
        )

        row = tk.Frame(box)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Código activo:", font=("", 10)).pack(side="left")
        self.var_escritura_codigo_entrada = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.var_escritura_codigo_entrada, font=("", 10)).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.var_escritura_codigo_entrada.trace_add("write", lambda *_: self._escritura_calcular_nuevo_epc(silent=True))

        tk.Label(box, textvariable=self.var_escritura_epc_nuevo, font=("", 9), anchor="w").pack(fill="x", pady=(8, 2))
        tk.Label(box, textvariable=self.var_escritura_estado, font=("", 8), fg="#444", wraplength=440, justify="left").pack(
            fill="x", pady=(2, 0)
        )

        row2 = tk.Frame(self._marco_escritura)
        row2.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(row2, text="Escanear", style="HandheldBig.TButton", command=self._escritura_escanear_una_vez).pack(
            side="left", fill="x", expand=True, ipady=2
        )

        row3 = tk.Frame(self._marco_escritura)
        row3.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(row3, text="Escribir", style="HandheldBig.TButton", command=self._escritura_ejecutar_programacion).pack(
            side="left", fill="x", expand=True, ipady=2
        )

        # Estado interno
        self._epc_memoria_escritura_actual = ""
        self._epc_memoria_escritura_nuevo = ""
        # (la simulación/hardware la gestiona ServicioEscrituraEtiquetas)

    def _escritura_escanear_una_vez(self):
        try:
            lectura = self._servicio_escritura.escanear_una_etiqueta(self._lector)
        except Exception as e:
            messagebox.showerror("Escritura", str(e))
            return

        self._epc_memoria_escritura_actual = lectura.epc_en_hex
        suf = " (simulado)" if lectura.simulado else ""
        self.var_escritura_epc_actual.set(f"EPC actual: {lectura.epc_en_hex}{suf}")
        self.var_escritura_codigo_actual.set(f"Código actual (si aplica): {lectura.codigo_decodificado or '—'}")
        self.var_escritura_estado.set("Etiqueta leída. Escribe el código del activo para generar el EPC nuevo.")
        self._escritura_calcular_nuevo_epc(silent=True)

    def _escritura_calcular_nuevo_epc(self, silent: bool = False):
        codigo = (self.var_escritura_codigo_entrada.get() or "").strip()
        if not codigo:
            self._epc_memoria_escritura_nuevo = ""
            self.var_escritura_epc_nuevo.set("EPC nuevo: —")
            return
        epc = self._servicio_escritura.calcular_epc_desde_codigo(codigo)
        if not epc:
            self._epc_memoria_escritura_nuevo = ""
            self.var_escritura_epc_nuevo.set("EPC nuevo: —")
            return
        self._epc_memoria_escritura_nuevo = epc
        self.var_escritura_epc_nuevo.set(f"EPC nuevo: {epc}  (desde {codigo})")
        if not silent:
            self.var_escritura_estado.set("Listo para escribir (simulado).")

    def _escritura_ejecutar_programacion(self):
        if not self._epc_memoria_escritura_nuevo:
            self._escritura_calcular_nuevo_epc(silent=True)
        try:
            resultado_escritura = self._servicio_escritura.programar_epc(
                self._lector, self._epc_memoria_escritura_actual, self._epc_memoria_escritura_nuevo
            )
        except Exception as e:
            messagebox.showerror("Escritura", str(e))
            return

        epc_anterior = self._epc_memoria_escritura_actual
        self._epc_memoria_escritura_actual = resultado_escritura.epc_nuevo_en_hex
        codigo = (self.var_escritura_codigo_entrada.get() or "").strip()
        suf = " (simulado)" if resultado_escritura.simulado else ""
        self.var_escritura_epc_actual.set(f"EPC actual: {self._epc_memoria_escritura_actual}{suf}")
        self.var_escritura_codigo_actual.set(f"Código actual (si aplica): {codigo or '—'}")
        self.var_escritura_estado.set(
            estado_escritura_programada(epc_anterior, self._epc_memoria_escritura_actual)
        )
        messagebox.showinfo("Escritura", "Etiqueta programada." if not resultado_escritura.simulado else "Simulación: etiqueta programada.")

    def _construir_hid(self):
        """Modo pistola como teclado Bluetooth."""
        self._marco_hid = tk.Frame(self.contenedor)
        ttk.Button(
            self._marco_hid,
            text="Menú",
            style="Handheld.TButton",
            command=lambda: self._mostrar_marco("menu"),
        ).pack(anchor="w", padx=8, pady=6)
        tk.Label(
            self._marco_hid,
            text="Modo teclado (Bluetooth)",
            font=("", 14, "bold"),
        ).pack(anchor="w", padx=12, pady=(0, 6))
        tk.Label(
            self._marco_hid,
            text="Empareja la pistola con la laptop. Si ya se ha hecho antes, primero olvida el dispositivo en la laptop. Después, empareja de nuevo.",
            font=("", 9),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=12, pady=2)
        tk.Label(
            self._marco_hid,
            text="Para inventario otra vez regresar a menú.",
            font=("", 8),
            fg="#444",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(6, 2))

    def _chip_leyenda(self, parent, text, bg):
        f = tk.Frame(parent, bg=bg, bd=1, relief="solid")
        tk.Label(f, text=text, bg=bg, padx=4, pady=1, font=("", 8)).pack()
        return f

    def _al_cambiar_filtro_resultados(self):
        self._aplicar_filtro_resultados()

    def _nuevo_escaneo_desde_resultados(self):
        self._mostrar_marco("ubicacion")

    def _alternar_pausa_escaneo(self):
        if not self._escaner.esta_en_ejecucion():
            return
        if self._escaner.esta_pausado():
            self._escaner.reanudar()
            self.btn_pausar_escaneo.config(text="Pausar")
        else:
            self._escaner.pausar()
            self.btn_pausar_escaneo.config(text="Reanudar")

    def _ajustar_controles_escaneo_activo(self, en_curso):
        """en_curso=True: pistoleo en curso (Iniciar off, Detener/Pausar on). en_curso=False: listo para iniciar."""
        if en_curso:
            self.btn_iniciar_pistoleo.config(state="disabled")
            self.btn_detener_escaneo.config(state="normal")
            self.btn_pausar_escaneo.config(state="normal", text="Pausar")
            self.btn_cancelar_escaneo.config(state="normal")
        else:
            self.btn_iniciar_pistoleo.config(state="normal")
            self.btn_detener_escaneo.config(state="disabled")
            self.btn_pausar_escaneo.config(state="disabled", text="Pausar")

    def _llenar_arbol_escaneo_y_encabezado(self):
        ubicacion = self._clave_ubicacion_actual()
        self._actualizar_pista_ubicacion()
        self._conjunto_epcs_esperados = self._servicio_inventario.conjunto_esperados(ubicacion)
        self._arbol_escaneo_items_esperados = {}
        self._arbol_escaneo_items_nuevos = {}
        for item in self.arbol_escaneo.get_children():
            self.arbol_escaneo.delete(item)
        for epc in sorted(list(self._conjunto_epcs_esperados)):
            disp = mostrar_activo_desde_epc(epc)
            iid = self.arbol_escaneo.insert("", tk.END, values=("NO ESCANEADO", disp, ""), tags=("faltante",))
            self._arbol_escaneo_items_esperados[epc] = iid
        self.var_linea_ubicacion_escaneo.set("Ubicación: {0}".format(ubicacion))
        self.var_linea_tiempo_escaneo.set("Tiempo: 0.0 s")
        self.var_linea_conteos_escaneo.set(
            "Esperados: {0} | Leídos únicos: 0".format(self._servicio_inventario.cantidad_esperados(ubicacion))
        )

    def ir_a_pantalla_escaneo(self):
        """Solo navega a la pantalla de inventario; no arranca el lector (evita el mismo clic como trigger)."""
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reanudar()
        self._escaner.detener()
        self._detener_temporizador_escaneo()
        self._lineas_log_escaneo = []
        self.lista_log_escaneo.delete(0, tk.END)
        self._llenar_arbol_escaneo_y_encabezado()
        self._ajustar_controles_escaneo_activo(False)
        self._mostrar_marco("escaneo")

    def iniciar_pistoleo(self):
        """Aquí sí arranca el escaneo continuo (simulación de pistoleo)."""
        if self._escaner.esta_en_ejecucion():
            return
        self._asegurar_puerto_sin_servicio_gatt_conflicto()
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reiniciar()
        self._lineas_log_escaneo = []
        self.lista_log_escaneo.delete(0, tk.END)
        self._llenar_arbol_escaneo_y_encabezado()
        self._ajustar_controles_escaneo_activo(True)
        # Pequeño retraso: el clic del botón no debe solaparse con la primera lectura (trigger simulado).
        self._tarea_inicio_pistoleo = self.after(120, self._iniciar_hilo_pistoleo)

    def _cancelar_inicio_pistoleo_pendiente(self):
        if self._tarea_inicio_pistoleo is not None:
            try:
                self.after_cancel(self._tarea_inicio_pistoleo)
            except Exception:
                pass
            self._tarea_inicio_pistoleo = None

    def _iniciar_hilo_pistoleo(self):
        self._tarea_inicio_pistoleo = None
        if self._escaner.esta_en_ejecucion():
            return
        self._escaneo_inicio_ms = int(self.tk.call("clock", "milliseconds"))
        self._iniciar_temporizador_escaneo()
        self._escaner.reanudar()
        self._escaner.iniciar(al_leer_etiqueta=self._al_leer_etiqueta, al_error=self._al_error_escaneo)

    def _al_error_escaneo(self, e: Exception):
        # Corre en hilo de Escaner; brincar a hilo UI con after()
        def ejecutar_ui():
            self._cancelar_inicio_pistoleo_pendiente()
            self._escaner.reanudar()
            self._escaner.detener()
            self._detener_temporizador_escaneo()
            self._ajustar_controles_escaneo_activo(False)
            mensaje_error = (
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
            messagebox.showerror("Lector desconectado", mensaje_error)

        try:
            self.after(0, ejecutar_ui)
        except Exception:
            pass

    def conectar_lector(self):
        if self._lector.connected:
            messagebox.showinfo("Info", "Ya conectado.")
            self.btn_continuar.config(state="normal")
            self.var_estado_lector.set("Lector: conectado")
            return
        port = self.var_puerto_serial.get().strip()
        port_l = port.lower()
        if port_l.startswith("/dev/ttyusb"):
            port = "/dev/ttyUSB" + port[len("/dev/ttyusb") :]
        elif port_l.startswith("/dev/ttyacm"):
            port = "/dev/ttyACM" + port[len("/dev/ttyacm") :]
        if not port:
            messagebox.showerror("Error", "Indica el puerto (COM5, /dev/ttyUSB0, …).")
            return
        try:
            baud = int(self.var_baudios.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Baud inválido.")
            return
        try:
            self._lector.conectar(port, baud, debug=False)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.var_estado_lector.set("Lector: conectado ({0} @ {1})".format(port, baud))
        self.btn_conectar_lector.config(state="disabled")
        self.btn_continuar.config(state="normal")

    def detener_escaneo(self):
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reanudar()
        self._escaner.detener()
        self._detener_temporizador_escaneo()
        self._ajustar_controles_escaneo_activo(False)
        self._comparar_y_mostrar_resultados()
        self._mostrar_marco("resultados")

    def _exportar_tipo_ubicacion_actualizado(self):
        """Genera un reporte de sesión con el MISMO formato que el catálogo de activos.

        - Salida: lista JSON con objetos `{idDetalle, tipoUbicacion, activo:{...}}`
        - Solo incluye los activos escaneados en esta sesión (found)
        - tipoUbicacion:
          - C si el EPC era esperado en la ubicación actual
          - U si el EPC fue escaneado pero no era esperado en la ubicación actual
        """
        try:
            ubicacion = self._clave_ubicacion_actual()
            muestra = self._ultima_muestra_escaneo or {"seen_epcs": set()}
            leidos = set(muestra.get("seen_epcs") or set())
            esperados = set(self._conjunto_epcs_esperados or set())

            directorio_actual = os.path.dirname(os.path.abspath(__file__))
            dir_web = os.path.abspath(os.path.join(directorio_actual, "..", "..", "pi_ble_hid", "web"))
            ruta_activos = os.path.join(dir_web, "activosPiso2_Computacion.json")
            if not os.path.isfile(ruta_activos):
                messagebox.showerror("Actualización", f"No existe:\n{ruta_activos}")
                return
            filas = json.loads(open(ruta_activos, "r", encoding="utf-8").read())
            if not isinstance(filas, list):
                messagebox.showerror("Actualización", "El JSON de activos no tiene formato de lista.")
                return

            # Índice por código de activo para recuperar la fila original sin cambiar su estructura.
            indice_codigo = {}
            for fila in filas:
                activo_obj = (fila or {}).get("activo") or {}
                codigo = activo_obj.get("activo")
                if codigo:
                    indice_codigo[str(codigo).strip()] = fila

            esperados_min = {str(x).lower() for x in esperados}
            filas_salida = []
            leidos_min = {str(x).lower() for x in leidos}

            # 1) Escaneados: C/U (o ACTIVO NUEVO si no existe en catálogo base)
            for epc in sorted(leidos_min):
                codigo = epc12_hex_a_codigo_activo(epc)
                fila_orig = indice_codigo.get(codigo) if codigo else None
                if fila_orig:
                    copia = json.loads(json.dumps(fila_orig, ensure_ascii=False))  # deep copy sin cambiar formato
                    copia["tipoUbicacion"] = "C" if epc in esperados_min else "U"
                    filas_salida.append(copia)
                    continue

                # Activo NUEVO (no existe en el catálogo base): conservar formato "tipo webservice"
                filas_salida.append(
                    {
                        "idDetalle": None,
                        "tipoUbicacion": "U",
                        "activo": {
                            "activo": codigo or None,
                            "descripcion": "ACTIVO NUEVO",
                            "idUbicacion": None,
                            "nombreUbicacion": ubicacion,
                            "nombreResponsable": None,
                        },
                    }
                )

            # 2) Esperados pero NO escaneados en esta ubicación: N
            for epc in sorted(esperados_min.difference(leidos_min)):
                codigo = epc12_hex_a_codigo_activo(epc)
                if not codigo:
                    continue
                fila_orig = indice_codigo.get(codigo)
                if not fila_orig:
                    continue
                copia = json.loads(json.dumps(fila_orig, ensure_ascii=False))  # deep copy
                copia["tipoUbicacion"] = "N"
                filas_salida.append(copia)

            dir_resultados = os.path.abspath(os.path.join(dir_web, "resultados"))
            os.makedirs(dir_resultados, exist_ok=True)
            marca_tiempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            ubicacion_segura = "".join([c for c in ubicacion if c.isalnum() or c in (" ", "-", "_", "·")]).strip().replace(" ", "_")
            ruta_salida = os.path.join(dir_resultados, f"activosPiso2_Computacion_sesion_{ubicacion_segura}_{marca_tiempo}.json")
            open(ruta_salida, "w", encoding="utf-8").write(json.dumps(filas_salida, ensure_ascii=False, indent=2))

            messagebox.showinfo("Actualización", f"Archivo generado:\n{ruta_salida}")
        except Exception:
            # No bloquea el flujo principal
            return

    def cancelar_escaneo(self):
        self._cancelar_inicio_pistoleo_pendiente()
        self._escaner.reanudar()
        self._escaner.detener()
        self._detener_temporizador_escaneo()
        self._ajustar_controles_escaneo_activo(False)
        self._mostrar_marco("ubicacion")

    def _iniciar_temporizador_escaneo(self):
        self._detener_temporizador_escaneo()

        def actualizar_temporizador_escaneo():
            if not self._escaner.esta_en_ejecucion():
                return
            instante_ms = int(self.tk.call("clock", "milliseconds"))
            segundos_transcurridos = 0.0
            if self._escaneo_inicio_ms is not None:
                segundos_transcurridos = max(0.0, (instante_ms - self._escaneo_inicio_ms) / 1000.0)
            ubicacion = self._clave_ubicacion_actual()
            muestra_act = self._escaner.instantanea()
            total_unicos = len(muestra_act["seen_epcs"])
            self.var_linea_ubicacion_escaneo.set("Ubicación: {0}".format(ubicacion))
            self.var_linea_tiempo_escaneo.set("Tiempo: {0:.1f} s".format(segundos_transcurridos))
            self.var_linea_conteos_escaneo.set(
                "Esperados: {0} | Leídos únicos: {1}".format(self._servicio_inventario.cantidad_esperados(ubicacion), total_unicos)
            )
            self._tarea_temporizador_escaneo = self.after(250, actualizar_temporizador_escaneo)

        self._tarea_temporizador_escaneo = self.after(250, actualizar_temporizador_escaneo)

    def _detener_temporizador_escaneo(self):
        if self._tarea_temporizador_escaneo is not None:
            try:
                self.after_cancel(self._tarea_temporizador_escaneo)
            except Exception:
                pass
        self._tarea_temporizador_escaneo = None
        self._escaneo_inicio_ms = None

    def _agregar_linea_log_escaneo(self, fila_log):
        self._lineas_log_escaneo.append(fila_log)
        while len(self._lineas_log_escaneo) > self._MAX_LINEAS_LOG_ESCANEO:
            self._lineas_log_escaneo.pop(0)
        self.lista_log_escaneo.delete(0, tk.END)
        for ln in self._lineas_log_escaneo:
            self.lista_log_escaneo.insert(tk.END, ln)

    def _al_leer_etiqueta(self, tag, idx_in_batch):
        fila_log = "{0}  RSSI={1}".format(tag.epc_hex, tag.rssi)
        delay_ms = idx_in_batch * 45

        def agregar_a_log():
            self._agregar_linea_log_escaneo(fila_log)
            self._actualizar_arbol_escaneo_en_vivo(tag)

        if delay_ms <= 0:
            self.after(0, agregar_a_log)
        else:
            self.after(delay_ms, agregar_a_log)

    def _actualizar_arbol_escaneo_en_vivo(self, tag):
        epc = tag.epc_hex
        if epc in self._conjunto_epcs_esperados:
            iid = self._arbol_escaneo_items_esperados.get(epc)
            if iid is not None:
                try:
                    disp = mostrar_activo_desde_epc(epc)
                    self.arbol_escaneo.item(
                        iid,
                        values=("ENCONTRADO", disp, tag.rssi),
                        tags=("encontrado",),
                    )
                except Exception:
                    pass
            return

        iid_new = self._arbol_escaneo_items_nuevos.get(epc)
        if iid_new is None:
            disp = mostrar_activo_desde_epc(epc)
            iid_new = self.arbol_escaneo.insert("", tk.END, values=("ACTIVO NUEVO", disp, tag.rssi), tags=("nuevo",))
            self._arbol_escaneo_items_nuevos[epc] = iid_new
        else:
            try:
                disp = mostrar_activo_desde_epc(epc)
                self.arbol_escaneo.item(iid_new, values=("ACTIVO NUEVO", disp, tag.rssi), tags=("nuevo",))
            except Exception:
                pass

    def _comparar_y_mostrar_resultados(self):
        ubicacion = self._clave_ubicacion_actual()
        resultado, muestra, epcs_esperados = self._servicio_inventario.comparar_ubicacion(ubicacion)
        self._ultima_muestra_escaneo = muestra
        self._ubicacion_texto_resultados = ubicacion

        self.var_linea_ubicacion_resultados.set("Ubicación: {0}".format(ubicacion))
        self.var_linea_estadisticas_resultados.set(
            "Esperados: {0} | Encontrados: {1} | Faltan: {2} | Nuevos: {3}".format(
                len(epcs_esperados),
                len(resultado.encontrados),
                len(resultado.faltantes),
                len(resultado.nuevos),
            )
        )

        self._filas_resultados_inventario = []
        self._resultado_iid_a_epc = {}
        self._filas_resultados_inventario = construir_filas_resultado(resultado, muestra)

        self._modo_filtro_resultados.set("todos")
        self._aplicar_filtro_resultados()

    def _aplicar_filtro_resultados(self):
        filtro = self._modo_filtro_resultados.get()
        for item in self.arbol_resultados.get_children():
            self.arbol_resultados.delete(item)
        self._resultado_iid_a_epc = {}

        for fila in self._filas_resultados_inventario:
            if filtro == "faltantes" and fila["tipo"] != "faltante":
                continue
            if filtro == "nuevos" and fila["tipo"] != "nuevo":
                continue
            etiqueta = "encontrado"
            if fila["tipo"] == "faltante":
                etiqueta = "faltante"
            elif fila["tipo"] == "nuevo":
                etiqueta = "nuevo"
            epc = fila["epc"]
            texto_activo = mostrar_activo_desde_epc(epc)
            iid = self.arbol_resultados.insert(
                "",
                tk.END,
                values=(fila["estado"], texto_activo, fila["rssi"]),
                tags=(etiqueta,),
            )
            self._resultado_iid_a_epc[iid] = epc

    def _al_doble_clic_resultado(self, event):
        seleccion = self.arbol_resultados.selection()
        if not seleccion:
            return
        valores = self.arbol_resultados.item(seleccion[0], "values")
        if len(valores) < 3:
            return
        estado_fila, _texto, rssi = valores[0], valores[1], valores[2]
        epc = self._resultado_iid_a_epc.get(seleccion[0], "")
        self.var_detalle_epc.set(epc)
        self.var_detalle_codigo_activo.set(codigo_activo_o_guion_desde_epc(epc))
        self.var_detalle_estado.set(estado_fila)
        self.var_detalle_ubicacion.set(self._ubicacion_texto_resultados)
        self.var_detalle_rssi.set(rssi if rssi else "—")
        self._mostrar_marco("detalle")

    def al_cerrar_ventana(self):
        try:
            self._cancelar_inicio_pistoleo_pendiente()
            self._escaner.reanudar()
            self._escaner.detener()
            self._lector.cerrar()
        finally:
            self.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventario RFID (interfaz táctil / lector).")
    parser.add_argument(
        "--kiosk",
        action="store_true",
        help="Pantalla completa (despliegue en Raspberry Pi con escritorio recortado).",
    )
    args = parser.parse_args(argv)
    AplicacionInventario(kiosk=args.kiosk).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
