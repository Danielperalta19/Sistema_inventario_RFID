from __future__ import annotations


def build_result_rows(compare_result, snap: dict) -> list[dict]:
    """
    Convierte el resultado de dominio + snapshot del scanner en filas listas para UI.

    Salida: lista de dicts con llaves:
      - kind: encontrado|faltante|nuevo
      - status: texto UI
      - epc: epc_hex (string)
      - rssi: último rssi si aplica (o "")
    """
    last_rssi = (snap or {}).get("last_rssi") or {}

    out: list[dict] = []
    for epc in getattr(compare_result, "encontrados", []) or []:
        out.append(
            {
                "kind": "encontrado",
                "status": "ENCONTRADO",
                "epc": epc,
                "rssi": last_rssi.get(epc, ""),
            }
        )
    for epc in getattr(compare_result, "faltantes", []) or []:
        out.append(
            {
                "kind": "faltante",
                "status": "NO ESCANEADO",
                "epc": epc,
                "rssi": "",
            }
        )
    for epc in getattr(compare_result, "nuevos", []) or []:
        out.append(
            {
                "kind": "nuevo",
                "status": "ACTIVO NUEVO",
                "epc": epc,
                "rssi": last_rssi.get(epc, ""),
            }
        )
    return out

