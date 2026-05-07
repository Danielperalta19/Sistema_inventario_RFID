"""Codec EPC12: código (ASCII) <-> hex (12 bytes).

Convención del proyecto:
- EPC = 12 bytes
- contenido: ASCII del código (máx 12) + padding 0x00
"""

from __future__ import annotations


_MAX = 12


def asset_code_to_epc12_hex(code: str) -> str:
    s = (code or "").strip()
    b = s.encode("ascii", errors="ignore")[:_MAX]
    b = b.ljust(_MAX, b"\x00")
    return b.hex()


def epc12_hex_to_asset_code(epc_hex: str) -> str:
    """Devuelve string ASCII sin padding. Si no se puede, retorna ''."""
    try:
        b = bytes.fromhex((epc_hex or "").strip()[: (_MAX * 2)])
    except Exception:
        return ""
    b = b.split(b"\x00", 1)[0]
    try:
        return b.decode("ascii", errors="ignore").strip()
    except Exception:
        return ""

