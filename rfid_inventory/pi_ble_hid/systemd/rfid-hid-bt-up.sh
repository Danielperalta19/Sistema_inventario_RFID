#!/bin/sh
# Ejecutar después de arrancar la Pi (manual o cron @reboot):
#   sudo /home/TU_USUARIO/Sistema_inventario_RFID/rfid_inventory/pi_ble_hid/systemd/rfid-hid-bt-up.sh
#
# Deja el adaptador visible para emparejar / reconectar desde Windows.

sleep 3
timeout 5 bluetoothctl power on 2>/dev/null || true
timeout 5 bluetoothctl pairable on 2>/dev/null || true
timeout 5 bluetoothctl discoverable on 2>/dev/null || true
timeout 5 btmgmt -i hci0 connectable on 2>/dev/null || true
timeout 5 btmgmt -i hci0 advertising on 2>/dev/null || true
exit 0
