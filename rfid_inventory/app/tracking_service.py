"""Servicio de rastreo: EPC/código -> ubicación(es) esperada(s) según catálogo."""

from __future__ import annotations

from dataclasses import dataclass

from rfid_inventory.catalog.epc12_codec import asset_code_to_epc12_hex, epc12_hex_to_asset_code


@dataclass(frozen=True)
class TrackResult:
    epc_hex: str
    asset_code: str
    locations: list[str]


class TrackingService:
    def __init__(self, nested_locations: dict[str, dict[str, list[str]]]):
        self._epc_index: dict[str, list[str]] = {}
        for edif, rooms in (nested_locations or {}).items():
            for sala, epcs in (rooms or {}).items():
                loc = f"{edif} · {sala}"
                for epc in epcs or []:
                    self._epc_index.setdefault(str(epc).lower(), []).append(loc)

    def normalize_input(self, s: str) -> tuple[str, str]:
        raw = (s or "").strip()
        if not raw:
            return ("", "")
        token = raw.split(",")[0].strip().split()[0].strip()
        t = token.lower()
        hexchars = "0123456789abcdef"
        if len(t) >= 24 and all(c in hexchars for c in t[:24]):
            epc = t[:24]
            return (epc, epc12_hex_to_asset_code(epc))
        code = token
        epc = asset_code_to_epc12_hex(code)
        return (epc, code)

    def track(self, s: str) -> TrackResult | None:
        epc, code = self.normalize_input(s)
        if not epc:
            return None
        locs = self._epc_index.get(epc.lower(), [])
        return TrackResult(epc_hex=epc, asset_code=code or "", locations=locs)

