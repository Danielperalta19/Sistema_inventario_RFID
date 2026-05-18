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

Dependencias: `requirements.txt` (`pyserial` + `pyserial-asyncio`). La librería `rfid_r200` va **incluida** en `rfid_inventory/vendor/` (GPL-3.0, ver `vendor/LICENSE-rfid-r200.txt`).

**Documentación operativa (Pi, Bluetooth):** carpeta [`docs/`](docs/LEEME.txt) — empezar por `docs/DESPLIEGUE_PI.txt` para despliegue en el lector.

---

## Flujo de la GUI (pantallas)

1. **Inicio** → botón que lleva a **Conectar lector**.
2. **Conectar lector** → puerto/baud, botones rápidos Windows / Raspberry Pi, **Conectar**, luego **Continuar** al menú (o al inventario si el flujo lo pide).
3. **Menú** → cuatro módulos:
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
| Puerto y baud por defecto al abrir “Conectar” | `config.json` → `serial.*` |
| Orden de búsqueda de JSON de catálogo (web vs data) | `config.json` → `catalog.prefer_web_dir` (usa `rfid_inventory/catalog/catalog_loader.py` → `rutas_catalogo_por_defecto`) |
| Escritura real de EPC vs simulación | `config.json` → `features.write_use_hardware` y/o variable de entorno `RFID_WRITE_USE_HARDWARE` (prioridad: **env** si está definida como 1/0/true/false/yes/no) |
| Rastreo: forzar RSSI simulado aunque haya lector | `config.json` → `features.prox_force_sim` |
| Botones Windows / Raspberry en conectar | Código: `handheld_app.py` (sugerencia de `/dev/serial/by-id/`) |
| Export “Actualizar tipoUbicacion” | Código: `handheld_app.py` → carpeta `rfid_inventory/pi_ble_hid/web/resultados/` (ignorada por Git; ver `.gitignore`) |
| Publicidad BLE desde el botón del menú | Código: `handheld_app.py` → `sudo -n btmgmt -i hci0 advertising on` (hoy **`hci0` fijo** en código) |

### Catálogo (ubicaciones + activos)

| Qué | Dónde |
| --- | --- |
| Archivos JSON de ejemplo / operación | `rfid_inventory/pi_ble_hid/web/ubicacionesComputacion.json` y `activosPiso2_Computacion.json` (fallback opcional: `rfid_inventory/data/catalog_ejemplo/` si existiera) |
| Unión ubicación ↔ activo | Por **`idUbicacion`** en el JSON de activos y filas de ubicaciones; lógica en `catalog_loader.py` |

### Raspberry Pi: Bluetooth HID + autostart

| Qué | Dónde |
| --- | --- |
| Documentación (Pi, Bluetooth) | **`docs/`** — ver `docs/LEEME.txt` (`DESPLIEGUE_PI.txt`, `CONEXION_BLUETOOTH_HID.txt`, `AUTOSTART_HID.txt`, `GUIA_MODO_BLUETOOTH_HID_RPI.txt`, …) |
| Autostart GUI en Pi | `deploy/raspberry-pi-recortado/` (`launch-handheld.sh`, `.desktop`) |
| Emparejamiento, `bluetoothctl`, `btmgmt`, systemd | `docs/` + unidades en `rfid_inventory/pi_ble_hid/systemd/` |
| Servidor GATT / teclas | `rfid_inventory/pi_ble_hid/gatt_server_rfid.py`, `hid_keys.py` |
| Referencia upstream (no es el servicio en producción) | `docs/gattServer_upstream.py` |

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
- **`catalog.prefer_web_dir`**: si es `true`, se intenta primero el catálogo en `pi_ble_hid/web/`; si es `false`, primero `data/catalog_ejemplo/`.
- **`features.write_use_hardware`**: si es `true`, el módulo “Escribir tag” usa el lector real (`single poll` / `write_epc12_hex`). Si es `false`, es **simulado** salvo override por entorno (ver mapa).
- **`features.prox_force_sim`**: si es `true`, el rastreo usa **solo simulación** de RSSI (comportamiento demo acordado).

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

## Estructura (lo esencial)

- `rfid_inventory/app/app_config.py` — carga `config.json` (`cargar_configuracion_aplicacion`, `hardware_escritura_resuelto`).
- `rfid_inventory/catalog/catalog_loader.py` — rutas y carga de JSON (`rutas_catalogo_por_defecto`, `cargar_ubicaciones_anidadas_desde_json`); `epc12_codec.py` — EPC ↔ código de activo (`codigo_activo_a_epc12_hex`, `epc12_hex_a_codigo_activo`).
- `rfid_inventory/app/scanner.py` — hilo de lectura continua e instantánea (`Escaner`).
- `rfid_inventory/app/inventory_service.py` — une catálogo + instantánea del escáner + comparación.
- `rfid_inventory/app/inventory_presenter.py` — filas para pantalla de resultados.
- `rfid_inventory/app/tag_writer_service.py` — lógica del módulo escribir etiqueta.
- `rfid_inventory/app/tracking_service.py` / `proximity_tracker.py` — rastreo y suavizado RSSI.
- `rfid_inventory/ui/gui/handheld_app.py` — toda la navegación y widgets.
- `rfid_inventory/ui/ui_formatters.py` — textos “Activo” vs EPC en tablas.
- `rfid_inventory/drivers/r200_driver.py` — serial y operaciones R200 (`LectorR200`, `programar_epc12_en_etiqueta` cuando haya hardware compatible).
- `rfid_inventory/pi_ble_hid/web/` — catálogo y prueba web.
- **`docs/`** — toda la documentación (Bluetooth HID, despliegue kiosco en Pi, bitácora).

---

## Nota de uso (importante)

Un puerto serial solo lo puede abrir **un programa a la vez**. Si corres la app, no dejes abierto el Monitor Serie del Arduino en el mismo puerto.
