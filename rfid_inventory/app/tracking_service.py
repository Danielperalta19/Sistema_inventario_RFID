"""Servicio de rastreo: EPC/código -> ubicación(es) esperada(s) según catálogo."""

from __future__ import annotations

from dataclasses import dataclass

from rfid_inventory.catalog.epc12_codec import codigo_activo_a_epc12_hex, epc12_hex_a_codigo_activo


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
        ficha_min = ficha.lower()
        hex_validos = "0123456789abcdef"
        if len(ficha_min) >= 24 and all(c in hex_validos for c in ficha_min[:24]):
            epc = ficha_min[:24]
            return (epc, epc12_hex_a_codigo_activo(epc))
        codigo = ficha
        epc = codigo_activo_a_epc12_hex(codigo)
        return (epc, codigo)

    def rastrear(self, texto: str) -> ResultadoRastreo | None:
        epc, codigo = self.normalizar_entrada(texto)
        if not epc:
            return None
        lista_ubic = self._indice_epc_a_ubicaciones.get(epc.lower(), [])
        return ResultadoRastreo(epc_en_hex=epc, codigo_activo=codigo or "", ubicaciones=lista_ubic)
