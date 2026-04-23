"""
Genera firmware/arduino_r200_emulator/r200_emulador/epc_list_generated.h
a partir de data/catalog_ejemplo/activosPiso2_Computacion.json

Cada EPC = código de activo (ASCII) rellenado a 12 bytes con 0x00 (misma idea que
75010000000x: bytes visibles, no SGTIN-96 genérico).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# rfid_inventory/tools/thisfile.py  → parents[2] = raíz del repo
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from rfid_inventory.catalog.asset_epc12 import asset_code_to_epc12_bytes  # noqa: E402

_JSON = _REPO / "rfid_inventory" / "data" / "catalog_ejemplo" / "activosPiso2_Computacion.json"
_OUT = _REPO / "firmware" / "arduino_r200_emulator" / "r200_emulador" / "epc_list_generated.h"


def _load_activo_codes() -> list[str]:
    data = json.loads(_JSON.read_text(encoding="utf-8"))
    seen: set[str] = set()
    out: list[str] = []
    for row in data:
        a = row.get("activo") or {}
        c = a.get("activo")
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _bytes_to_c_init(b: bytes) -> str:
    assert len(b) == 12
    return "{" + ",".join("0x{:02X}".format(x) for x in b) + "}"


def main() -> int:
    if not _JSON.is_file():
        print("No existe:", _JSON, file=sys.stderr)
        return 1
    codes = _load_activo_codes()
    if not codes:
        print("Sin códigos de activo en", _JSON, file=sys.stderr)
        return 1

    lines = [
        "/* generado por rfid_inventory/tools/generate_arduino_epc_list.py */",
        "/* 12 bytes = código de activo (ASCII) + 0x00; orden = aparición única en JSON */",
        "#ifndef EPC_LIST_GENERATED_H",
        "#define EPC_LIST_GENERATED_H",
        "",
        f"/* {len(codes)} entradas */",
        "static const uint8_t EPC_LIST[][12] = {",
    ]
    for c in codes:
        b = asset_code_to_epc12_bytes(c)
        safe = c.replace("*/", "* /")
        lines.append(f"  {_bytes_to_c_init(b)}, // {safe}")
    lines.append("};")
    lines.append("")
    lines.append("#endif /* EPC_LIST_GENERATED_H */")
    lines.append("")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text("\n".join(lines), encoding="utf-8")
    print("Escrito", _OUT, "con", len(codes), "EPCs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
