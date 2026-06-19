"""Prepara filas para la tabla de resultados a partir del dominio y de la instantánea del escáner."""

from __future__ import annotations


def construir_filas_resultado(resultado_comparacion, muestra: dict) -> list[dict]:
    """
    Convierte el resultado de dominio y la instantánea (``instantanea()``) del escáner en filas listas para la interfaz.

    Salida: lista de dicts con llaves:
      - tipo: encontrado|faltante|nuevo
      - estado: texto UI
      - epc: epc_hex (string)
      - rssi: último rssi si aplica (o "")
    """
    ultimo_rssi = (muestra or {}).get("last_rssi") or {}

    salida: list[dict] = []
    for epc in getattr(resultado_comparacion, "encontrados", []) or []:
        salida.append(
            {
                "tipo": "encontrado",
                "estado": "ENCONTRADO",
                "epc": epc,
                "rssi": ultimo_rssi.get(epc, ""),
            }
        )
    for epc in getattr(resultado_comparacion, "faltantes", []) or []:
        salida.append(
            {
                "tipo": "faltante",
                "estado": "NO ESCANEADO",
                "epc": epc,
                "rssi": "",
            }
        )
    for epc in getattr(resultado_comparacion, "nuevos", []) or []:
        salida.append(
            {
                "tipo": "nuevo",
                "estado": "ACTIVO NUEVO",
                "epc": epc,
                "rssi": ultimo_rssi.get(epc, ""),
            }
        )
    return salida
