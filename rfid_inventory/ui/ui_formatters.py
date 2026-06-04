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


def valor_etiqueta_para_operador(epc_hex: str, codigo_decodificado: str | None = None) -> str:
    """Código de activo si existe; si no, el identificador leído en la etiqueta (sin decir EPC)."""
    codigo = (codigo_decodificado or "").strip()
    if codigo:
        return codigo
    epc = (epc_hex or "").strip().lower()
    return epc if epc else "—"


def hex_corto(epc_hex: str, keep: int = 8) -> str:
    epc = (epc_hex or "").strip().lower()
    if not epc:
        return "—"
    if len(epc) <= keep:
        return epc
    return epc[:keep] + "…"


def estado_escritura_programada(old_epc: str, new_epc: str) -> str:
    return f"OK: EPC programado ({hex_corto(old_epc)} → {hex_corto(new_epc)})."


def estado_escritura_programada_operador(codigo_anterior: str | None, codigo_nuevo: str | None) -> str:
    """Mensaje para pantalla Escribir etiqueta (sin EPC ni hex)."""
    anterior = (codigo_anterior or "").strip() or "—"
    nuevo = (codigo_nuevo or "").strip() or "—"
    if anterior != "—" and nuevo != "—" and anterior != nuevo:
        return "Etiqueta actualizada: {0} → {1}.".format(anterior, nuevo)
    if nuevo != "—":
        return "Etiqueta grabada con código {0}.".format(nuevo)
    return "Etiqueta grabada correctamente."

