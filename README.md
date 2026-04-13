# Inventario RFID (R200 / emulador) — CICESE

Objetivo: **inventariar por ubicación** comparando una lista de EPC esperados contra lo leído por el lector.

Este repo está hecho para correr en:
- **PC** (Windows) con Arduino (emulador) por USB
- **Raspberry Pi** con Arduino por **USB OTG** (aparece como `/dev/ttyUSB0` o `/dev/ttyACM0`)

## Cómo se ejecuta

### GUI (ventana)

```bash
python -m rfid_inventory.ui.gui.inventory_app
```

### CLI (terminal, recomendado para Raspberry)

```bash
python -m rfid_inventory.ui.cli.inventory_mode --port COM5
python -m rfid_inventory.ui.cli.inventory_mode --port /dev/ttyUSB0
python -m rfid_inventory.ui.cli.inventory_mode --port /dev/ttyACM0 --seconds 30
```

Dependencias: `requirements.txt` (`pyserial` + `pyserial-asyncio`). El código de la librería `rfid_r200` va **incluido** en `rfid_inventory/vendor/` (GPL-3.0, ver `vendor/LICENSE-rfid-r200.txt`) para que en Raspberry Pi no dependas de un wheel roto de pip/piwheels.

## Estructura (lo esencial)

- `rfid_inventory/drivers/r200_driver.py`
  - Conecta por serial y hace `read_tags_once()` → devuelve una lista de `TagRead(epc_hex, rssi)`.
- `rfid_inventory/app/scanner.py`
  - Hilo de fondo que llama a `read_tags_once()` en bucle hasta `stop()`.
  - Notifica **cada lectura** (incluye repetidos) y guarda un snapshot de EPC únicos + último RSSI.
- `rfid_inventory/domain/compare.py`
  - Lógica pura: `compare_expected_found(expected, found)` → OK / FALTA / NUEVO.
- `rfid_inventory/ui/gui/inventory_app.py`
  - UI en Tkinter: lista “Vistos” (en vivo, con repetidos) + tabla de comparación al detener.
- `rfid_inventory/ui/cli/inventory_mode.py`
  - Misma idea que la GUI pero en terminal: imprime una línea por lectura; ENTER detiene.
- `firmware/arduino_r200_emulator/r200_emulador/r200_emulador.ino`
  - Emulador mínimo del protocolo del R200: responde a `multiple poll`, `stop` e `info`.

## Cómo funciona (explicación para presentar)

1. **Conexión**
   - La UI/CLI abre un puerto serial (COMx o `/dev/tty...`) a **115200**.
2. **Lectura**
   - El driver usa la librería `rfid-r200`, que envía un comando “multiple poll”.
   - El emulador (Arduino) responde mandando varios frames “tag leído”, cada uno con:
     - RSSI simulado
     - EPC de 12 bytes (lo mostramos como hex en Python)
3. **Escaneo en vivo**
   - `Scanner` corre en un hilo y repite `read_tags_once()` muchas veces.
   - Por cada tag que llega, dispara un callback:
     - En GUI: se agrega una línea a “Vistos al escanear” (con repetidos).
     - En CLI: se imprime una línea por lectura.
4. **Detener y comparar**
   - Al detener, se toma un `snapshot()` de EPC **únicos** y se compara contra “esperados”.
   - La tabla de comparación muestra:
     - **OK**: esperado y encontrado
     - **FALTA**: esperado pero no encontrado
     - **NUEVO**: encontrado pero no esperado

## Nota de uso (importante)

- Un puerto serial solo lo puede abrir **un programa a la vez**. Si estás usando Python, no tengas abierto el Monitor Serie de Arduino.
