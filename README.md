# Sistema de inventario RFID (R200 + Raspberry Pi)

Sistema portátil de inventario RFID UHF para el CICESE, basado en una “pistola” con **Raspberry Pi Zero 2 W** y el módulo **RFID R200** (UART 115200, frames binarios).

El objetivo es que el personal pueda:

- **Auditar inventario** por sala: escanear y comparar tags detectados vs inventario esperado.
- **Escribir/asignar tags**: escribir datos (p. ej. EPC) a un tag y confirmar OK/FAIL.
- **Rastrear un tag**: buscar un EPC objetivo y mostrar “proximidad” con RSSI.

## Estructura del repositorio

- `rfid_inventory/`: paquete Python de la aplicación (Raspberry Pi).
- `firmware/arduino_r200_emulator/`: emulador del R200 en Arduino Nano (para desarrollo sin hardware final).
- `tools/pc/`: utilidades para probar desde PC (por ejemplo `pyserial`).

## Estado actual

Mientras llegan todos los componentes, se usa un **emulador del R200** (Arduino Nano) para avanzar en:

- parsing/encoding de frames
- driver UART
- flujos de “inventario”, “escritura” y “rastreo”

## Hardware objetivo (resumen)

- Raspberry Pi Zero 2 W
- Módulo RFID R200 UHF
- Antena UHF (SMA)
- Botón trigger (GPIO): presionar = start scan, soltar = stop scan
- Pantalla táctil (futuro, UI)

## Protocolo (resumen)

Frame:

`0xAA | TYPE | CMD | LEN_MSB | LEN_LSB | DATA | CHECKSUM | 0xDD`

- `TYPE`: `0x00` comando, `0x01` respuesta, `0x02` notificación
- `CHECKSUM`: suma de bytes desde `TYPE` hasta el final de `DATA`, `& 0xFF`

Comandos clave:

- `0x27` start multiple poll (scan)
- `0x28` stop multiple poll
- `0x49` write

## Emulador R200 (Arduino Nano)

El emulador sirve para que el software en Python pueda probarse sin el R200 real.

## Cómo usar en Arduino IDE

1. Abre `firmware/arduino_r200_emulator/r200_emulador.ino`
2. Selecciona **Arduino Nano** y el puerto correcto.
3. Compila y sube.

## Probar sin Raspberry (desde tu PC)

El monitor serial del Arduino IDE es para texto; como el R200 usa **bytes binarios**, lo más fácil es usar Python + `pyserial`.

1. Instala pyserial:

```bash
py -m pip install pyserial
```

2. Ejecuta el tester (cambia `COM3` por tu puerto):

```bash
py tools/pc/test_emulator.py --port COM3 --baud 115200
```

3. En el prompt, prueba:
   - `info` (get module info)
   - `single` (single poll)
   - `multiple` (multiple poll; verás varias tramas)
   - `stop` (stop multiple poll)

## Conexión UART

Arduino Nano (ATmega328P):

- **D0 (RX)** ← TX del adaptador UART (o de la Raspberry, si conectas directo)
- **D1 (TX)** → RX del adaptador UART / Raspberry
- **GND** ↔ GND

**Importante**: usa niveles 3.3V si conectas a Raspberry (o un level shifter).

## Simular gatillo (trigger) con un botón

El emulador puede hacer “stream” de tags mientras mantienes presionado un botón, sin necesidad de enviar `0x27/0x28`.

- **Cableado**:
  - Botón entre **D2** y **GND** del Nano.
  - No necesitas resistencias externas (usa `INPUT_PULLUP`).
- **Comportamiento**:
  - **Presionado**: envía frames de tags (Type `0x02`, Command `0x22`) continuamente.
  - **Suelto**: deja de enviar.
- **Config**: en `firmware/arduino_r200_emulator/r200_emulador.ino`:
  - `SIMULAR_GATILLO = true/false`
  - `PIN_GATILLO = 2`

## Cambiar tags simulados

Edita `EPC_LIST` en `firmware/arduino_r200_emulator/r200_emulador.ino`. Cada EPC es de **12 bytes**.

