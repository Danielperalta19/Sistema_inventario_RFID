#!/bin/sh
# Repara el flujo BLE HID en la Pi (emparejado en Windows pero sin conectar / sin teclas).
# Uso: cd ~/Sistema_inventario_RFID/rfid_inventory/pi_ble_hid && sudo ./scripts/reparar_bluetooth_hid.sh

set -e

PI_BLE="$(cd "$(dirname "$0")/.." && pwd)"
POST_GATT="$PI_BLE/systemd/rfid-hid-post-gatt.sh"

echo "=== Reparar Bluetooth HID (RFID) ==="

echo "[1/6] Detener procesos GATT duplicados..."
sudo pkill -f gatt_server_rfid.py 2>/dev/null || true
sleep 1

echo "[2/6] Reiniciar bluetooth..."
sudo systemctl restart bluetooth
sleep 3

echo "[3/6] Clase de dispositivo = teclado (0x000540)..."
if command -v hciconfig >/dev/null 2>&1; then
  sudo hciconfig hci0 class 0x000540 || true
fi

echo "[4/6] Servicios systemd (bt-up + gatt + post-gatt si está instalado)..."
if [ -f /etc/systemd/system/rfid-hid-bt-up.service ]; then
  sudo systemctl start rfid-hid-bt-up.service || true
fi
if [ -f /etc/systemd/system/rfid-hid-gatt.service ]; then
  sudo systemctl restart rfid-hid-gatt.service
  sleep 5
else
  echo "    rfid-hid-gatt.service no instalado; levantando GATT a mano..."
  if [ -f /etc/default/rfid-hid-gatt ]; then
    set -a
    # shellcheck disable=SC1091
    . /etc/default/rfid-hid-gatt
    set +a
  fi
  cd "$PI_BLE" || exit 1
  sudo -E python3 gatt_server_rfid.py &
  sleep 5
fi

if [ -x "$POST_GATT" ]; then
  echo "[5/6] Post-GATT (advertising + trust)..."
  sudo "$POST_GATT"
elif [ -f /etc/systemd/system/rfid-hid-btmgmt-after-gatt.service ]; then
  sudo systemctl start rfid-hid-btmgmt-after-gatt.service || true
fi

echo "[6/6] Estado actual:"
sudo btmgmt -i hci0 info 2>/dev/null || true
if systemctl is-active rfid-hid-gatt.service >/dev/null 2>&1; then
  systemctl is-active rfid-hid-gatt.service
  journalctl -u rfid-hid-gatt.service -n 8 --no-pager 2>/dev/null || true
fi

cat <<'WIN'

=== En Windows (importante) ===
1. Configuración > Bluetooth: quita/olvida el dispositivo de la Pi si sigue fallando.
2. Abre "Bluetooth LE Explorer" (Microsoft Store), NO uses solo Ajustes para conectar.
3. Busca la Pi > Pair. Luego pulsa **Connect** (debe quedar conectado, no solo emparejado).
4. Abre Bloc de notas y prueba. Si hay RFID_PORT en la Pi, escanea un tag.

Si solo dice "Emparejado" y no "Conectado", el GATT no está activo en la Pi:
  journalctl -u rfid-hid-gatt.service -f

WIN
