"""Carga y normaliza catálogo (ubicaciones + activos) desde JSON.

Entrada esperada (ejemplos tipo webservices):
- `ubicacionesComputacion.json`: lista de dicts con idUbicacion, edificio, piso, cubo, subcubo, area, barcode, ...
- `activosPiso2_Computacion.json`: lista de dicts con `activo` anidado (incluye idUbicacion, nombreUbicacion, activo)

Salida:
- nested: edificio -> sala -> [epc_hex]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .epc12_codec import codigo_activo_a_epc12_hex


def _leer_json_primera_ruta_valida(rutas: list[str]) -> Any:
    for p in rutas:
        if not p or not os.path.isfile(p):
            continue
        try:
            return json.loads(open(p, "r", encoding="utf-8").read())
        except Exception:
            continue
    return None


def _partir_nombre_ubicacion(nombre: str) -> tuple[str, str]:
    """Extrae edificio y 'sala' desde el string del catálogo."""
    if not nombre:
        return ("(Sin edificio)", "(Sin sala)")
    parts = [p.strip() for p in str(nombre).split(" - ") if p.strip()]
    campos: dict[str, str] = {}
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            campos[k.strip().lower()] = v.strip()
    edificio = campos.get("edificio") or "(Sin edificio)"
    piso = campos.get("piso")
    cubo = campos.get("cubo")
    subcubo = campos.get("subcubo")
    area = campos.get("area")
    partes_sala = []
    if piso:
        partes_sala.append(f"Piso {piso}")
    if cubo:
        partes_sala.append(f"Cubo {cubo}")
    if subcubo:
        partes_sala.append(f"SubCubo {subcubo}")
    if area:
        partes_sala.append(area)
    sala = " · ".join(partes_sala) if partes_sala else str(nombre)
    return (edificio, sala)


def _sala_desde_fila_ubicacion(fila: dict) -> str:
    piso = fila.get("piso")
    cubo = fila.get("cubo")
    subcubo = fila.get("subcubo")
    area = fila.get("area")
    partes_sala = []
    if piso:
        partes_sala.append(f"Piso {piso}")
    if cubo:
        partes_sala.append(f"Cubo {cubo}")
    if subcubo:
        partes_sala.append(f"SubCubo {subcubo}")
    if area:
        partes_sala.append(str(area))
    nombre_u = fila.get("nombreUbicacion")
    return " · ".join(partes_sala) if partes_sala else (str(nombre_u) if nombre_u else "(Sin sala)")


@dataclass(frozen=True)
class RutasCatalogo:
    ubicaciones_paths: list[str]
    activos_paths: list[str]


def rutas_catalogo_por_defecto(ruta_raiz_repositorio: str) -> RutasCatalogo:
    """Rutas del catálogo en ``rfid_inventory/pi_ble_hid/web/``."""
    web_dir = os.path.join(ruta_raiz_repositorio, "rfid_inventory", "pi_ble_hid", "web")
    return RutasCatalogo(
        ubicaciones_paths=[os.path.join(web_dir, "ubicacionesComputacion.json")],
        activos_paths=[os.path.join(web_dir, "activosPiso2_Computacion.json")],
    )


def cargar_ubicaciones_anidadas_desde_json(rutas: RutasCatalogo) -> dict[str, dict[str, list[str]]]:
    """edificio -> sala -> lista de EPC esperados (hex)."""
    filas_ubic = _leer_json_primera_ruta_valida(rutas.ubicaciones_paths) or []
    filas_activos = _leer_json_primera_ruta_valida(rutas.activos_paths) or []
    if not isinstance(filas_ubic, list):
        filas_ubic = []
    if not isinstance(filas_activos, list):
        filas_activos = []

    ubic_por_id: dict[int, dict] = {}
    for u in filas_ubic:
        if not isinstance(u, dict):
            continue
        uid = u.get("idUbicacion")
        if isinstance(uid, int):
            ubic_por_id[uid] = u

    anidado: dict[str, dict[str, list[str]]] = {}
    vistos_por_sala: dict[tuple[str, str], set[str]] = {}

    # 1) Publica TODAS las ubicaciones, aunque no tengan activos.
    for _uid, u in ubic_por_id.items():
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_desde_fila_ubicacion(u)
        anidado.setdefault(edif, {}).setdefault(sala, [])
        vistos_por_sala.setdefault((edif, sala), set())

    # 2) Agrega activos que hagan match por idUbicacion; ignora activos fuera del catálogo de ubicaciones.
    for r in filas_activos:
        a = (r or {}).get("activo") or {}
        code = a.get("activo")
        if not code:
            continue
        uid = a.get("idUbicacion")
        if not (isinstance(uid, int) and uid in ubic_por_id):
            continue
        u = ubic_por_id[uid]
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_desde_fila_ubicacion(u)
        epc_hex = codigo_activo_a_epc12_hex(str(code))
        clave = (edif, sala)
        if epc_hex in vistos_por_sala.setdefault(clave, set()):
            continue
        vistos_por_sala[clave].add(epc_hex)
        anidado.setdefault(edif, {}).setdefault(sala, []).append(epc_hex)

    # Orden estable
    for edif in anidado:
        for sala in anidado[edif]:
            anidado[edif][sala].sort()
    return anidado


def aplanar_ubicaciones_a_mapa_epcs(anidado: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    plano: dict[str, list[str]] = {}
    for edif, salas in anidado.items():
        for sala, epcs in salas.items():
            plano[f"{edif} · {sala}"] = epcs
    return plano
