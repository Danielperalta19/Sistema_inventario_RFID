"""Cargar códigos de activo desde el JSON de ejemplo del cliente (webservices)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .asset_epc12 import asset_code_to_epc12_hex


def load_activo_epc_hexes_by_ubicacion(path: str | Path) -> dict[str, list[str]]:
    """nombreUbicacion (texto) -> lista de EPC en hex (24 chars), sin duplicados."""
    data: list[dict[str, Any]] = json.loads(
        Path(path).read_text(encoding="utf-8")
    )
    by_loc: dict[str, set[str]] = {}
    for row in data:
        a = row.get("activo") or {}
        code = a.get("activo")
        loc = a.get("nombreUbicacion") or ""
        if not code or not str(loc).strip():
            continue
        loc = str(loc).strip()
        h = asset_code_to_epc12_hex(str(code).strip())
        if loc not in by_loc:
            by_loc[loc] = set()
        by_loc[loc].add(h)
    return {k: sorted(v) for k, v in by_loc.items()}
