# Inventario RFID (R200 / emulador) — CICESE

Objetivo: **inventariar por ubicación** comparando activos esperados (catálogo) contra lo leído por el lector, con módulos adicionales (rastreo, escritura de etiqueta, modo teclado Bluetooth).

Este repo está hecho para correr en:

- **PC (Windows)** con Arduino (emulador) por USB
- **Raspberry Pi** con lector o emulador por **USB** (p. ej. `/dev/ttyUSB0`, `/dev/ttyACM0` o `/dev/serial/by-id/...`)

Pantalla de referencia de la GUI: **480×320** (p. ej. Waveshare en la Pi).

## Cómo se ejecuta

### GUI (handheld)

```bash
python -m rfid_inventory.ui.gui.handheld_app
```

Dependencias: `requirements.txt` (`pyserial`). La librería `rfid_r200` va **incluida** en `rfid_inventory/vendor/` (GPL-3.0, ver `vendor/LICENSE-rfid-r200.txt`).

**Documentación operativa (Pi, Bluetooth):** carpeta [`docs/`](docs/LEEME.txt) — empezar por `docs/DESPLIEGUE_PI.txt` para despliegue en el lector.

---

## Flujo de la GUI (pantallas)

1. **Inicio** → **Menú** (en la Pi, con `serial.auto_connect_on_start: true`, el lector se conecta solo al abrir).
2. **Conectar lector** (solo si hace falta) → puerto/baud, **Conectar**, luego **Continuar**.
3. **Menú** → módulos:
   - **Inventario en ubicación** → **Ubicación** (edificio + sala) → **Escaneo** (lista de esperados; **Trigger** / **Detener**; sin log de lecturas en pantalla) → **Resultados** (filtros; **Actualizar tipoUbicacion** genera JSON de sesión; doble clic → **Detalle**).
   - **Rastrear activo** → búsqueda por código; proximidad (en demo suele ser **RSSI simulado** según `config.json`).
   - **Escribir tag** → escanear / escribir (simulado o real según configuración).
   - **Modo teclado (Bluetooth)** → en Linux intenta `btmgmt advertising on` (ver mapa de configuración abajo).

No hay modo CLI en este repo (solo la GUI anterior se eliminó a propósito).

---

## Mapa único: dónde se configura cada cosa

### Aplicación Tkinter (`handheld_app`)

| Qué | Dónde |
| --- | --- |
| Puerto, baud y auto-conexión al iniciar | `config.json` → `serial.*` (`auto_connect_on_start`, env `RFID_AUTO_CONNECT`) |
| Escritura real de EPC vs simulación | `config.json` → `features.write_use_hardware` y/o variable de entorno `RFID_WRITE_USE_HARDWARE` (prioridad: **env** si está definida como 1/0/true/false/yes/no) |
| Rastreo: forzar RSSI simulado aunque haya lector | `config.json` → `features.prox_force_sim` |
| Botones Windows / Raspberry en conectar | Código: `handheld_app.py` (sugerencia de `/dev/serial/by-id/`) |
| Export “Actualizar tipoUbicacion” | Código: `handheld_app.py` → carpeta `rfid_inventory/pi_ble_hid/web/resultados/` (ignorada por Git; ver `.gitignore`) |
| Publicidad BLE desde el botón del menú | Código: `handheld_app.py` → `sudo -n btmgmt -i hci0 advertising on` (hoy **`hci0` fijo** en código) |

### Catálogo (ubicaciones + activos)

| Qué | Dónde |
| --- | --- |
| Archivos JSON de catálogo | `rfid_inventory/pi_ble_hid/web/ubicacionesComputacion.json` y `activosPiso2_Computacion.json` |
| Unión ubicación ↔ activo | Por **`idUbicacion`** en el JSON de activos y filas de ubicaciones; lógica en `catalog_loader.py` |

### Raspberry Pi: Bluetooth HID + autostart

| Qué | Dónde |
| --- | --- |
| Documentación (Pi, Bluetooth) | **`docs/`** — ver `docs/LEEME.txt` (`DESPLIEGUE_PI.txt`, `CONEXION_BLUETOOTH_HID.txt`, `AUTOSTART_HID.txt`, `GUIA_MODO_BLUETOOTH_HID_RPI.txt`, …) |
| Autostart GUI en Pi | `deploy/raspberry-pi-recortado/` (`launch-handheld.sh`, `.desktop`) |
| Emparejamiento, `bluetoothctl`, `btmgmt`, systemd | `docs/` + unidades en `rfid_inventory/pi_ble_hid/systemd/` |
| Servidor GATT / teclas | `rfid_inventory/pi_ble_hid/gatt_server_rfid.py`, `hid_keys.py` |
| Demo BLE HID original (referencia MIT) | https://github.com/HeadHodge/Bluez-HID-over-Gatt-Keyboard-Peripheral |

### Firmware emulador Arduino

| Qué | Dónde |
| --- | --- |
| Sketch y lista estática de EPC | `firmware/arduino_r200_emulator/r200_emulador/` (`r200_emulador.ino`, `epc_list_generated.h`, etc.) |

Si regeneras la lista de EPC a partir del catálogo, actualiza `epc_list_generated.h` (no hay script automático en el repo en este momento).

### Protocolo R200 (hardware real)

| Qué | Dónde |
| --- | --- |
| PDFs y esquemas | `r200 DOCUMENTACION/` |
| Driver Python | `rfid_inventory/drivers/r200_driver.py` |
| Comandos bajo nivel | `rfid_inventory/vendor/rfid_r200/rfid_reader_sync.py` |

---

## `config.json` (raíz del repo)

Ejemplo y significado de claves:

- **`serial.baud`**: baud por defecto en la pantalla de conectar (suele ser `115200`).
- **`serial.default_port_windows`**: texto inicial del puerto en Windows (p. ej. `COM5`).
- **`serial.default_port_pi_fallback`**: si no hay `/dev/serial/by-id/`, se usa este valor como respaldo en Linux.
- **`serial.auto_connect_on_start`**: en la Pi, conectar el lector al abrir la app (env `RFID_AUTO_CONNECT`).
- **`features.write_use_hardware`**: por defecto `true` (escritura real). Con `false` o `RFID_WRITE_USE_HARDWARE=0` vuelve la simulación (útil con emulador Arduino sin módulo).
- **`features.prox_force_sim`**: por defecto `false` (RSSI real con lector conectado). Con `true` el rastreo usa RSSI simulado aunque haya hardware.
- **`serial.default_port_pi_fallback`**: por defecto `/dev/serial0` (UART GPIO en Pi).

Override rápido sin tocar JSON (escritura):

```bash
set RFID_WRITE_USE_HARDWARE=1
python -m rfid_inventory.ui.gui.handheld_app
```

En PowerShell también: `$env:RFID_WRITE_USE_HARDWARE="1"`. Con `0` o `false` fuerzas **desactivado** aunque `config.json` diga `true`.

---

## Cómo funciona (alineado a la app actual)

1. **Conexión**  
   La GUI abre el puerto serial indicado (por defecto según `config.json` y botones Windows/Pi).

2. **Lectura en inventario**  
   Tras **Trigger**, la clase `Escaner` en un hilo llama repetidamente al driver (`read_tags_once()` → *multiple poll* en el protocolo). Cada lectura actualiza el **Treeview** (activo decodificado desde EPC12 cuando aplica) y el motor guarda **EPC únicos** y último RSSI para la comparación final.

3. **Detener**  
   Se detiene el hilo; con `instantanea()` se compara contra los esperados de la ubicación (`domain/compare.py` vía `ServicioInventario`).

4. **Resultados**  
   Tabla con filtros; el botón **Actualizar tipoUbicacion** escribe un JSON de **sesión** bajo `pi_ble_hid/web/resultados/`.

5. **Rastrear activo**  
   Solo entrada manual del código; la barra de proximidad depende de `prox_force_sim` y del lector (ver `config.json`).

6. **Escribir tag**  
   Flujo guiado; detrás está `ServicioEscrituraEtiquetas` (simulación o hardware según configuración).

---

## Estructura del repo

Mapa completo en [`docs/ESTRUCTURA.txt`](docs/ESTRUCTURA.txt). Resumen:

| Carpeta | Contenido |
| --- | --- |
| `rfid_inventory/ui/gui/` | App de pantalla (`handheld_app`, teclado virtual, autocompletado ubicación) |
| `rfid_inventory/app/` | Inventario, escáner, rastreo, escritura de tags |
| `rfid_inventory/drivers/` + `vendor/rfid_r200/` | Comunicación con el R200 |
| `rfid_inventory/pi_ble_hid/` | Bluetooth HID y JSON de catálogo |
| `firmware/` | Emulador Arduino |
| `docs/` | Guías Pi y Bluetooth |
| `deploy/` | Autostart en la Raspberry |
| `Diagramas/` | Secuencias y hardware |

---

## Nota de uso (importante)

Un puerto serial solo lo puede abrir **un programa a la vez**. Si corres la app, no dejes abierto el Monitor Serie del Arduino en el mismo puerto.
