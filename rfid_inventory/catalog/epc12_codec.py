"""Codec EPC12: código (ASCII) <-> hex (12 bytes).

Convención del proyecto:
- EPC = 12 bytes
- contenido: ASCII del código (máx 12) + padding 0x00
"""

from __future__ import annotations

_LONGITUD_MAXIMA_BYTES = 12


def codigo_activo_a_epc12_hex(codigo: str) -> str:
    s = (codigo or "").strip()
    b = s.encode("ascii", errors="ignore")[:_LONGITUD_MAXIMA_BYTES]
    b = b.ljust(_LONGITUD_MAXIMA_BYTES, b"\x00")
    return b.hex()


def epc12_hex_a_codigo_activo(epc_en_hex: str) -> str:
    """Devuelve string ASCII sin padding. Si no se puede, retorna ''."""
    try:
        b = bytes.fromhex((epc_en_hex or "").strip()[: (_LONGITUD_MAXIMA_BYTES * 2)])
    except Exception:
        return ""
    b = b.split(b"\x00", 1)[0]
    try:
        return b.decode("ascii", errors="ignore").strip()
    except Exception:
        return ""
