"""Código de activo (texto) ↔ 12 bytes de EPC (memoria de etiqueta / emulador R200)."""

from __future__ import annotations

_MAX = 12


def asset_code_to_epc12_bytes(code: str) -> bytes:
    s = (code or "").strip()
    if len(s) > _MAX:
        s = s[:_MAX]
    b = s.encode("ascii", errors="strict")
    return b.ljust(12, b"\x00")


def asset_code_to_epc12_hex(code: str) -> str:
    return asset_code_to_epc12_bytes(code).hex()
