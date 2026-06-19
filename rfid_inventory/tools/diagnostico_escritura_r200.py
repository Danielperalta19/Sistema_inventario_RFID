#!/usr/bin/env python3
"""Diagnóstico de escritura R200: escanea, imprime EPC hex/PC y prueba grabar.

Uso en la Pi:
  python rfid_inventory/tools/diagnostico_escritura_r200.py --puerto /dev/serial0
  RFID_SERIAL_DEBUG=1 python rfid_inventory/tools/diagnostico_escritura_r200.py --puerto /dev/serial0 --codigo FA003798
"""

from __future__ import annotations

import argparse
import os
import sys

_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _raiz not in sys.path:
    sys.path.insert(0, _raiz)

from rfid_inventory.catalog.epc12_codec import codigo_activo_a_epc12_hex
from rfid_inventory.drivers.r200_driver import LectorR200


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico escritura R200")
    parser.add_argument("--puerto", default="/dev/serial0")
    parser.add_argument("--baudios", type=int, default=115200)
    parser.add_argument("--codigo", default="FA003798", help="Código activo a grabar (máx 12)")
    args = parser.parse_args()

    epc_nuevo = codigo_activo_a_epc12_hex(args.codigo)
    if not epc_nuevo:
        print("Código inválido.")
        return 1

    lector = LectorR200()
    print("Conectando {0} @ {1}...".format(args.puerto, args.baudios))
    lector.conectar(args.puerto, args.baudios, debug=True)

    try:
        print("\n--- Escaneo ---")
        t = lector.leer_primera_etiqueta_una_encuesta()
        if not t:
            print("No se detectó etiqueta.")
            return 2
        print("EPC hex:", t.epc_hex)
        print("PC:     ", hex(t.pc) if t.pc is not None else "—")
        print("RSSI:   ", t.rssi)
        print("Nuevo EPC (hex):", epc_nuevo)

        print("\n--- Escritura ---")
        lector.programar_epc12_en_etiqueta(
            epc_actual_hex=t.epc_hex,
            epc_nuevo_hex=epc_nuevo,
            pc_etiqueta=t.pc,
        )
        print("OK: etiqueta grabada.")

        print("\n--- Verificación ---")
        t2 = lector.leer_primera_etiqueta_una_encuesta()
        if t2:
            print("EPC después:", t2.epc_hex)
        return 0
    except Exception as e:
        print("ERROR:", e)
        return 3
    finally:
        lector.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
