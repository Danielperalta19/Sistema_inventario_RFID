"""Codec EPC12: código (ASCII) <-> hex (12 bytes).

Convención del proyecto:
- EPC = 12 bytes (96 bits) = 24 caracteres hex
- Código activo: ASCII (máx 12) + padding 0x00
- Etiqueta virgen / EPC directo: 24 caracteres hex (0-9, a-f)
"""

from __future__ import annotations

_LONGITUD_MAXIMA_BYTES = 12
_LONGITUD_HEX_EPC = _LONGITUD_MAXIMA_BYTES * 2
_HEX_VALIDOS = frozenset("0123456789abcdef")


def es_epc_hex_24(texto: str) -> bool:
    """True si ``texto`` son al menos 24 dígitos hex (EPC virgen o hex directo)."""
    s = (texto or "").strip().lower()
    if len(s) < _LONGITUD_HEX_EPC:
        return False
    return all(c in _HEX_VALIDOS for c in s[:_LONGITUD_HEX_EPC])


def codigo_activo_a_epc12_hex(codigo: str) -> str:
    s = (codigo or "").strip()
    b = s.encode("ascii", errors="ignore")[:_LONGITUD_MAXIMA_BYTES]
    b = b.ljust(_LONGITUD_MAXIMA_BYTES, b"\x00")
    return b.hex()


def entrada_a_epc12_hex(texto: str) -> str | None:
    """Convierte entrada de escritura/rastreo a EPC hex (24 caracteres).

    - 24 hex → EPC tal cual (etiqueta virgen reprogramada con hex directo)
    - otro texto → código activo ASCII (p. ej. FA003798)
    """
    bruto = (texto or "").strip()
    if not bruto:
        return None
    if es_epc_hex_24(bruto):
        return bruto.lower()[:_LONGITUD_HEX_EPC]
    codificado = codigo_activo_a_epc12_hex(bruto)
    return codificado if codificado else None


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
