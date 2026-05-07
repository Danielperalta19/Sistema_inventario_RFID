from __future__ import annotations

from rfid_inventory.catalog.epc12_codec import epc12_hex_to_asset_code


def asset_display_from_epc(epc_hex: str) -> str:
    """
    Formato de UI: muestra el código (FA/OC/TE...) si se puede, si no muestra EPC hex.
    """
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    return epc12_hex_to_asset_code(epc) or epc


def asset_code_or_dash(epc_hex: str) -> str:
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    return epc12_hex_to_asset_code(epc) or "—"


def short_hex(epc_hex: str, keep: int = 8) -> str:
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    if len(epc) <= keep:
        return epc
    return epc[:keep] + "…"


def write_status_programmed(old_epc: str, new_epc: str) -> str:
    return f"OK: EPC programado ({short_hex(old_epc)} → {short_hex(new_epc)})."

