"""Servicio de rastreo: EPC/código -> ubicación(es) esperada(s) según catálogo."""

from __future__ import annotations

from dataclasses import dataclass

from rfid_inventory.catalog.epc12_codec import epc12_hex_a_codigo_activo, entrada_a_epc12_hex, es_epc_hex_24


@dataclass(frozen=True)
class ResultadoRastreo:
    epc_en_hex: str
    codigo_activo: str
    ubicaciones: list[str]


class ServicioRastreo:
    def __init__(self, ubicaciones_anidadas: dict[str, dict[str, list[str]]]):
        self._indice_epc_a_ubicaciones: dict[str, list[str]] = {}
        for edificio, salas in (ubicaciones_anidadas or {}).items():
            for sala, lista_epcs in (salas or {}).items():
                texto_ubicacion = f"{edificio} · {sala}"
                for epc in lista_epcs or []:
                    self._indice_epc_a_ubicaciones.setdefault(str(epc).lower(), []).append(texto_ubicacion)

    def normalizar_entrada(self, texto: str) -> tuple[str, str]:
        en_bruto = (texto or "").strip()
        if not en_bruto:
            return ("", "")
        ficha = en_bruto.split(",")[0].strip().split()[0].strip()
        epc = entrada_a_epc12_hex(ficha)
        if not epc:
            return ("", "")
        if es_epc_hex_24(ficha):
            return (epc, epc12_hex_a_codigo_activo(epc))
        return (epc, ficha)

    def rastrear(self, texto: str) -> ResultadoRastreo | None:
        epc, codigo = self.normalizar_entrada(texto)
        if not epc:
            return None
        lista_ubic = self._indice_epc_a_ubicaciones.get(epc.lower(), [])
        return ResultadoRastreo(epc_en_hex=epc, codigo_activo=codigo or "", ubicaciones=lista_ubic)
