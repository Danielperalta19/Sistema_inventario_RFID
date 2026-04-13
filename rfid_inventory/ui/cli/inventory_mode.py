"""Inventario por terminal: mismo flujo que la GUI (Scanner + driver)."""

import argparse
import threading
import time

from rfid_inventory.app import Scanner
from rfid_inventory.drivers import R200Driver


def run_inventory(port, baud, seconds, debug):
    driver = R200Driver()
    scanner = Scanner(driver)
    print_lock = threading.Lock()
    counts = {}

    def on_tag_read(tag, _idx_in_batch):
        with print_lock:
            counts[tag.epc_hex] = counts.get(tag.epc_hex, 0) + 1
            print(f"{tag.epc_hex}  RSSI={tag.rssi}", flush=True)

    try:
        try:
            driver.connect(port, baud, debug=debug)
        except Exception as e:
            print(f"Error de conexión: {e}", flush=True)
            return 1

        if seconds is None:
            print("Presiona ENTER para INICIAR el escaneo.", flush=True)
            input()
            t0 = time.time()
            print(
                "Escaneando… (cada línea = una lectura, con repeticiones; ENTER para DETENER)",
                flush=True,
            )
            stop_event = threading.Event()

            def wait_enter() -> None:
                try:
                    input()
                finally:
                    stop_event.set()

            threading.Thread(target=wait_enter, daemon=True).start()
            counts.clear()
            scanner.reset()
            scanner.start(on_tag_read)
            try:
                while not stop_event.is_set():
                    time.sleep(0.05)
            except KeyboardInterrupt:
                stop_event.set()
            scanner.stop()
        else:
            t0 = time.time()
            print(
                f"Escaneando {seconds:.1f}s (cada línea = una lectura; Ctrl+C para cortar)",
                flush=True,
            )
            counts.clear()
            scanner.reset()
            scanner.start(on_tag_read)
            try:
                while (time.time() - t0) < seconds:
                    time.sleep(0.05)
            except KeyboardInterrupt:
                pass
            scanner.stop()

        elapsed = time.time() - t0
        snap = scanner.snapshot()
        print(
            "\nÚnicos distintos: {0} EPCs | tiempo {1:.1f}s".format(len(snap["seen_epcs"]), elapsed),
            flush=True,
        )
        for epc in sorted(counts.keys()):
            print(
                "  EPC={0}  lecturas={1}  último RSSI={2}".format(
                    epc, counts[epc], snap["last_rssi"].get(epc, "")
                ),
                flush=True,
            )
        return 0
    finally:
        driver.close()


def main():
    ap = argparse.ArgumentParser(
        description="Modo inventario (CLI), mismo motor que la GUI: lecturas en vivo y repeticiones."
    )
    ap.add_argument(
        "--port",
        required=True,
        help="Puerto serial (Windows: COM5, Raspberry: /dev/ttyUSB0, /dev/ttyACM0, …)",
    )
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument(
        "--seconds",
        type=float,
        default=None,
        metavar="N",
        help="Si se indica, escanea N segundos sin pedir ENTER (útil en scripts o Pi sin teclado)",
    )
    ap.add_argument("--debug", action="store_true", help="Traza serial de rfid-r200")
    args = ap.parse_args()
    return run_inventory(args.port, args.baud, args.seconds, args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
