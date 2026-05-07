"""Actualizar `tipoUbicacion` (C/U/N) a partir de un inventario.

Reglas:
- C: EPC encontrado y era esperado en la ubicación actual
- U: EPC encontrado pero NO era esperado en la ubicación actual (reubicado / nuevo en esta ubicación)
- N (o vacío): EPC esperado en la ubicación actual pero NO fue encontrado

Entrada/Salida trabajan sobre el JSON estilo webservices:
[
  { "idDetalle": ..., "tipoUbicacion": "N", "activo": { "activo": "FA000358", ... } },
  ...
]
"""

from __future__ import annotations

import copy
from typing import Any

from rfid_inventory.catalog.epc12_codec import asset_code_to_epc12_hex


def update_tipo_ubicacion_rows(
    activos_rows: list[dict[str, Any]],
    expected_epcs: set[str],
    found_epcs: set[str],
) -> list[dict[str, Any]]:
    expected = {str(x).lower() for x in (expected_epcs or set())}
    found = {str(x).lower() for x in (found_epcs or set())}

    out: list[dict[str, Any]] = copy.deepcopy(activos_rows or [])
    for r in out:
        a = (r or {}).get("activo") or {}
        code = a.get("activo")
        if not code:
            continue
        epc = asset_code_to_epc12_hex(str(code)).lower()
        if epc in found and epc in expected:
            r["tipoUbicacion"] = "C"
        elif epc in found and epc not in expected:
            r["tipoUbicacion"] = "U"
        elif epc in expected and epc not in found:
            r["tipoUbicacion"] = "N"
        else:
            # No esperado aquí y no encontrado aquí: no cambia (mantiene lo que traiga)
            pass
    return out

