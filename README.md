# Inventario RFID (R200 / emulador) — CICESE

Objetivo: **inventariar por ubicación** comparando una lista de EPC esperados contra lo leído por el lector.

Este repo está hecho para correr en:
- **PC** (Windows) con Arduino (emulador) por USB
- **Raspberry Pi** con Arduino por **USB OTG** (aparece como `/dev/ttyUSB0` o `/dev/ttyACM0`)

## Cómo se ejecuta

### GUI (handheld / Waveshare 480×320)

```bash
python -m rfid_inventory.ui.gui.handheld_app
```

### CLI (opcional)

Se eliminó el modo CLI para mantener el proyecto más simple.

Dependencias: `requirements.txt` (`pyserial` + `pyserial-asyncio`). El código de la librería `rfid_r200` va **incluido** en `rfid_inventory/vendor/` (GPL-3.0, ver `vendor/LICENSE-rfid-r200.txt`) para que en Raspberry Pi no dependas de un wheel roto de pip/piwheels.

## Estructura (lo esencial)

- `rfid_inventory/drivers/r200_driver.py`
  - Conecta por serial y hace `read_tags_once()` → devuelve una lista de `TagRead(epc_hex, rssi)`.
- `rfid_inventory/app/scanner.py`
  - Hilo de fondo que llama a `read_tags_once()` en bucle hasta `stop()`.
  - Notifica **cada lectura** (incluye repetidos) y guarda un snapshot de EPC únicos + último RSSI.
- `rfid_inventory/domain/compare.py`
  - Lógica pura: `compare_expected_found(expected, found)` → OK / FALTA / NUEVO.
- `rfid_inventory/ui/gui/handheld_app.py`
  - UI en Tkinter para Raspberry (480×320): flujo Start → Conectar → Menú → módulos.
- `rfid_inventory/app/tag_writer_service.py`
  - Lógica del módulo “Escribir etiqueta” (simulado por defecto; habilitable con hardware).
- `rfid_inventory/ui/ui_formatters.py`
  - Formateo de UI (mostrar “Activo” decodificando EPC12 cuando aplique).
- `firmware/arduino_r200_emulator/r200_emulador/r200_emulador.ino`
  - Emulador mínimo del protocolo del R200: responde a `multiple poll`, `stop` e `info`.
  - Los EPC (12 bytes) se generan a partir de los códigos de **activo** del JSON de ejemplo: texto ASCII rellenado a 12 bytes con `0x00` (misma lógica que el mock numérico `7501…` pero con `FA000358` etc.). Regenerar el array incluido:
  - `python rfid_inventory/tools/generate_arduino_epc_list.py` → `epc_list_generated.h`
- `rfid_inventory/pi_ble_hid/web/`
  - Catálogo de prueba (JSON) para la app y la página web:
    - `ubicacionesComputacion.json`
    - `activosPiso2_Computacion.json`

## Flags (cuando haya hardware real)

- Para habilitar escritura real de EPC en el módulo “Escribir etiqueta”:

```bash
set RFID_WRITE_USE_HARDWARE=1
python -m rfid_inventory.ui.gui.handheld_app
```

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
