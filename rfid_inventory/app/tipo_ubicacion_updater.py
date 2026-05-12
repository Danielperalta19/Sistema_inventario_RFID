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

from rfid_inventory.catalog.epc12_codec import codigo_activo_a_epc12_hex


def actualizar_filas_tipo_ubicacion(
    filas_activos: list[dict[str, Any]],
    epcs_esperados: set[str],
    epcs_leidos: set[str],
) -> list[dict[str, Any]]:
    esperados = {str(x).lower() for x in (epcs_esperados or set())}
    leidos = {str(x).lower() for x in (epcs_leidos or set())}

    salida: list[dict[str, Any]] = copy.deepcopy(filas_activos or [])
    for fila in salida:
        activo = (fila or {}).get("activo") or {}
        codigo = activo.get("activo")
        if not codigo:
            continue
        epc = codigo_activo_a_epc12_hex(str(codigo)).lower()
        if epc in leidos and epc in esperados:
            fila["tipoUbicacion"] = "C"
        elif epc in leidos and epc not in esperados:
            fila["tipoUbicacion"] = "U"
        elif epc in esperados and epc not in leidos:
            fila["tipoUbicacion"] = "N"
        else:
            # No esperado aquí y no encontrado aquí: no cambia (mantiene lo que traiga)
            pass
    return salida
