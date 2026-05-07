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

from .epc12_codec import asset_code_to_epc12_hex


def _read_json_first(paths: list[str]) -> Any:
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        try:
            return json.loads(open(p, "r", encoding="utf-8").read())
        except Exception:
            continue
    return None


def _parse_nombre_ubicacion(nombre: str) -> tuple[str, str]:
    """Extrae edificio y 'sala' desde el string del catálogo."""
    if not nombre:
        return ("(Sin edificio)", "(Sin sala)")
    parts = [p.strip() for p in str(nombre).split(" - ") if p.strip()]
    fields: dict[str, str] = {}
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


@dataclass(frozen=True)
class CatalogPaths:
    ubicaciones_paths: list[str]
    activos_paths: list[str]


def default_catalog_paths(repo_root: str) -> CatalogPaths:
    """Conveniencia: rutas típicas del repo (web/ primero)."""
    web_dir = os.path.join(repo_root, "rfid_inventory", "pi_ble_hid", "web")
    data_dir = os.path.join(repo_root, "rfid_inventory", "data", "catalog_ejemplo")
    return CatalogPaths(
        ubicaciones_paths=[
            os.path.join(web_dir, "ubicacionesComputacion.json"),
            os.path.join(data_dir, "ubicacionesComputacion.json"),
        ],
        activos_paths=[
            os.path.join(web_dir, "activosPiso2_Computacion.json"),
            os.path.join(data_dir, "activosPiso2_Computacion.json"),
        ],
    )


def load_locations_nested_from_json(paths: CatalogPaths) -> dict[str, dict[str, list[str]]]:
    """edificio -> sala -> lista de EPC esperados (hex)."""
    ubic_rows = _read_json_first(paths.ubicaciones_paths) or []
    activo_rows = _read_json_first(paths.activos_paths) or []
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

    # 1) Publica TODAS las ubicaciones, aunque no tengan activos.
    for _uid, u in ubic_by_id.items():
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_from_ubic_row(u)
        out.setdefault(edif, {}).setdefault(sala, [])
        seen_per_room.setdefault((edif, sala), set())

    # 2) Agrega activos que hagan match por idUbicacion; ignora activos fuera del catálogo de ubicaciones.
    for r in activo_rows:
        a = (r or {}).get("activo") or {}
        code = a.get("activo")
        if not code:
            continue
        uid = a.get("idUbicacion")
        if not (isinstance(uid, int) and uid in ubic_by_id):
            continue
        u = ubic_by_id[uid]
        edif = u.get("edificio") or "(Sin edificio)"
        sala = _sala_from_ubic_row(u)
        epc_hex = asset_code_to_epc12_hex(str(code))
        key = (edif, sala)
        if epc_hex in seen_per_room.setdefault(key, set()):
            continue
        seen_per_room[key].add(epc_hex)
        out.setdefault(edif, {}).setdefault(sala, []).append(epc_hex)

    # Orden estable
    for edif in out:
        for sala in out[edif]:
            out[edif][sala].sort()
    return out


def flatten_locations(nested: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for edif, rooms in nested.items():
        for sala, epcs in rooms.items():
            out[f"{edif} · {sala}"] = epcs
    return out

