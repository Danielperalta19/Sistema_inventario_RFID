# R200 Emulator (Arduino Nano)

Este proyecto emula por UART (serial) un subconjunto del protocolo del módulo RFID R200 para que un software en Python que usa la librería `rfid-r200` pueda trabajar sin cambios.

## Qué está emulando

- **Framing**: `0xAA ... checksum ... 0xDD`
- **Checksum**: suma de bytes desde `Type` hasta el último parámetro, `& 0xFF`
- **Comandos**:
  - `0x22` Single Poll (responde con 1..N tramas de tag, `command=0x22`)
  - `0x27` Multiple Poll (empieza a emitir tramas de tag, `command=0x22`)
  - `0x28` Stop Multiple Poll (detiene emisión y responde ACK)
  - `0x03` Get Module Info (responde string simple)

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

