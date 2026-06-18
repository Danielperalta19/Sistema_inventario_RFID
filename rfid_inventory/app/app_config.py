"""Carga de ``config.json`` y reglas para leer flags (p. ej. escritura con hardware real)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfiguracionSerial:
    baudios: int = 115200
    puerto_defecto_windows: str = "COM5"
    puerto_defecto_pi_respaldo: str = "/dev/serial0"
    auto_conectar_al_iniciar: bool = True


@dataclass(frozen=True)
class ConfiguracionFunciones:
    escritura_con_hardware: bool = True
    forzar_simulacion_proximidad: bool = False
    bluetooth_hid_habilitado: bool = False


@dataclass(frozen=True)
class ConfiguracionAplicacion:
    serie: ConfiguracionSerial
    funciones: ConfiguracionFunciones


def _valor_anidado(d: dict, *claves, default=None):
    actual = d
    for c in claves:
        if not isinstance(actual, dict) or c not in actual:
            return default
        actual = actual[c]
    return actual


def cargar_configuracion_aplicacion(ruta_raiz_repositorio: str) -> ConfiguracionAplicacion:
    """
    Carga `config.json` en la raíz del repo.
    Si no existe o está malformado, regresa defaults (no revienta la app).
    """
    ruta = os.path.join(ruta_raiz_repositorio, "config.json")
    if not os.path.isfile(ruta):
        return ConfiguracionAplicacion(
            serie=ConfiguracionSerial(),
            funciones=ConfiguracionFunciones(),
        )
    try:
        crudo = json.loads(open(ruta, "r", encoding="utf-8").read())
    except Exception:
        return ConfiguracionAplicacion(
            serie=ConfiguracionSerial(),
            funciones=ConfiguracionFunciones(),
        )

    serie = ConfiguracionSerial(
        baudios=int(_valor_anidado(crudo, "serial", "baud", default=115200) or 115200),
        puerto_defecto_windows=str(
            _valor_anidado(crudo, "serial", "default_port_windows", default="COM5") or "COM5"
        ),
        puerto_defecto_pi_respaldo=str(
            _valor_anidado(crudo, "serial", "default_port_pi_fallback", default="/dev/serial0")
            or "/dev/serial0"
        ),
        auto_conectar_al_iniciar=bool(
            _valor_anidado(crudo, "serial", "auto_connect_on_start", default=True)
        ),
    )
    funciones = ConfiguracionFunciones(
        escritura_con_hardware=bool(
            _valor_anidado(crudo, "features", "write_use_hardware", default=True)
        ),
        forzar_simulacion_proximidad=bool(
            _valor_anidado(crudo, "features", "prox_force_sim", default=False)
        ),
        bluetooth_hid_habilitado=bool(
            _valor_anidado(crudo, "features", "bluetooth_hid_enabled", default=False)
        ),
    )
    return ConfiguracionAplicacion(serie=serie, funciones=funciones)


def bluetooth_hid_habilitado_resuelto(config: ConfiguracionAplicacion) -> bool:
    """Modo teclado BLE / GATT. Prioridad: env ``RFID_BLUETOOTH_HID`` (1/0) y luego config.json."""
    v = os.environ.get("RFID_BLUETOOTH_HID", "").strip().lower()
    if v in {"1", "true", "yes"}:
        return True
    if v in {"0", "false", "no"}:
        return False
    return bool(config.funciones.bluetooth_hid_habilitado)


def auto_conectar_lector_resuelto(config: ConfiguracionAplicacion) -> bool:
    """Conexión automática al abrir la app. Prioridad: env ``RFID_AUTO_CONNECT`` y luego config."""
    v = os.environ.get("RFID_AUTO_CONNECT", "").strip().lower()
    if v in {"1", "true", "yes"}:
        return True
    if v in {"0", "false", "no"}:
        return False
    return bool(config.serie.auto_conectar_al_iniciar)


def hardware_escritura_resuelto(config: ConfiguracionAplicacion) -> bool:
    """Escritura real de EPC: `config.json` + opcional override por variable de entorno.

    Si `RFID_WRITE_USE_HARDWARE` está definida, tiene prioridad sobre `config.json`:
    - valores que activan: 1, true, yes
    - valores que desactivan: 0, false, no
    """
    v = os.environ.get("RFID_WRITE_USE_HARDWARE", "").strip().lower()
    if v in {"1", "true", "yes"}:
        return True
    if v in {"0", "false", "no"}:
        return False
    return bool(config.funciones.escritura_con_hardware)
