import argparse
import binascii
import time

import serial


def hx(s: str) -> bytes:
    """Convierte una cadena hex (amigable) a bytes.

    Acepta entradas como:
    - aa0022dd
    - AA 00 22 DD
    - 0xaa 0x00 0x22 0xdd
    - 0x27
    """
    s = s.strip().lower()
    # Normalizar prefijos y separadores típicos
    s = s.replace("0x", "")
    for ch in [" ", "\t", "\n", "\r", ",", ";", "_", "-"]:
        s = s.replace(ch, "")

    if not s:
        raise ValueError("Cadena vacía")
    if len(s) % 2 != 0:
        raise ValueError(
            f"La cadena hex tiene longitud impar ({len(s)}). Agrega un 0 al inicio si era necesario."
        )

    try:
        return binascii.unhexlify(s)
    except binascii.Error as e:
        raise ValueError(f"Hex inválido: {e}") from e


def read_some(ser: serial.Serial, total_timeout_s: float) -> bytes:
    """Lee todo lo que llegue durante una ventana de tiempo."""
    end = time.time() + total_timeout_s
    buf = bytearray()
    while time.time() < end:
        chunk = ser.read(512)
        if chunk:
            buf.extend(chunk)
            # Dar un margen corto por si vienen más frames seguidos
            time.sleep(0.02)
        else:
            # No llegó nada por ahora; seguimos hasta que se cumpla el tiempo total
            continue
    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Enviar frames crudos del R200 al emulador (Arduino Nano)."
    )
    ap.add_argument("--port", required=True, help="Puerto COM, por ejemplo COM5")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=0.2, help="Timeout de lectura (segundos)")
    args = ap.parse_args()

    # Frames del protocolo (mismos que usa la librería Python)
    frames = {
        # AA 00 22 00 00 22 DD
        "single": hx("aa0022000022dd"),
        # AA 00 27 00 03 22 00 0A 56 DD
        "multiple": hx("aa0027000322000a56dd"),
        # AA 00 28 00 00 28 DD
        "stop": hx("aa0028000028dd"),
        # AA 00 03 00 01 00 04 DD
        "info": hx("aa000300010004dd"),
    }

    print(f"Abriendo {args.port} @ {args.baud} ...")
    with serial.Serial(args.port, args.baud, timeout=args.timeout, write_timeout=1) as ser:
        # Limpiar buffers (por si el Nano se reinició al abrir el puerto)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        while True:
            cmd = input("Comando [single|multiple|stop|info|hex|salir]: ").strip().lower()
            if cmd in ("q", "quit", "exit"):
                return 0
            if cmd in ("salir",):
                return 0

            if cmd in frames:
                payload = frames[cmd]
            elif cmd == "hex":
                user_hex = input("Bytes en hex (ej. aa0022...dd o 0x27): ")
                try:
                    payload = hx(user_hex)
                except ValueError as e:
                    print("Hex incorrecto:", e)
                    continue
            else:
                print("Comando desconocido.")
                continue

            print("TX:", binascii.hexlify(payload).decode())
            ser.write(payload)

            # Leer respuesta(s). El emulador puede enviar varios frames seguidos.
            data = read_some(ser, total_timeout_s=1.0)
            if data:
                print("RX:", binascii.hexlify(data).decode())
            else:
                print("RX: <sin datos>")


if __name__ == "__main__":
    raise SystemExit(main())

