"""Catálogo (JSON) y codificación EPC12 del proyecto."""

from .catalog_loader import (
    RutasCatalogo,
    aplanar_ubicaciones_a_mapa_epcs,
    cargar_ubicaciones_anidadas_desde_json,
    rutas_catalogo_por_defecto,
)
from .epc12_codec import codigo_activo_a_epc12_hex, epc12_hex_a_codigo_activo

__all__ = [
    "RutasCatalogo",
    "rutas_catalogo_por_defecto",
    "cargar_ubicaciones_anidadas_desde_json",
    "aplanar_ubicaciones_a_mapa_epcs",
    "codigo_activo_a_epc12_hex",
    "epc12_hex_a_codigo_activo",
]
