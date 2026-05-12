"""Textos y formatos para mostrar datos en la interfaz (activo vs EPC, recortes, etc.)."""

from __future__ import annotations

from rfid_inventory.catalog.epc12_codec import epc12_hex_a_codigo_activo


def mostrar_activo_desde_epc(epc_hex: str) -> str:
    """
    Formato de UI: muestra el código (FA/OC/TE...) si se puede, si no muestra EPC hex.
    """
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    return epc12_hex_a_codigo_activo(epc) or epc


def codigo_activo_o_guion_desde_epc(epc_hex: str) -> str:
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    return epc12_hex_a_codigo_activo(epc) or "—"


def hex_corto(epc_hex: str, keep: int = 8) -> str:
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    if len(epc) <= keep:
        return epc
    return epc[:keep] + "…"


def estado_escritura_programada(old_epc: str, new_epc: str) -> str:
    return f"OK: EPC programado ({hex_corto(old_epc)} → {hex_corto(new_epc)})."

