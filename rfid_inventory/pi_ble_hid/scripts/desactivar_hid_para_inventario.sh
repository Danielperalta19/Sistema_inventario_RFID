#!/usr/bin/env bash
# Detiene y deshabilita servicios BLE HID para que el lector R200 use el serial sin competencia.
# Uso en la Pi (inventario / pruebas):
#   chmod +x desactivar_hid_para_inventario.sh
#   sudo ./desactivar_hid_para_inventario.sh

set -euo pipefail

SERVICIOS=(
  rfid-hid-gatt.service
  rfid-hid-bt-up-post.service
  rfid-hid-btmgmt-refresh.service
  rfid-hid-btmgmt-after-gatt.service
)

echo "Deteniendo procesos GATT..."
sudo pkill -f gatt_server_rfid.py 2>/dev/null || true

for u in "${SERVICIOS[@]}"; do
  if systemctl list-unit-files "$u" &>/dev/null; then
    echo "  stop + disable $u"
    sudo systemctl stop "$u" 2>/dev/null || true
    sudo systemctl disable "$u" 2>/dev/null || true
  fi
done

if systemctl list-unit-files rfid-hid-bt-up.service &>/dev/null; then
  echo "  (rfid-hid-bt-up.service se deja habilitado; solo afecta Bluetooth visible)"
fi

echo ""
echo "Listo. Comprueba que el puerto esté libre:"
echo "  systemctl is-active rfid-hid-gatt.service || echo 'gatt inactivo (OK)'"
echo "  ls -l /dev/serial0"
echo ""
echo "En config.json de la app: features.bluetooth_hid_enabled: false"
