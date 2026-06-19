#!/bin/sh
# Vuelve a levantar el HID BLE con lector (si RFID_PORT está en /etc/default/rfid-hid-gatt).
set -e
exec sudo systemctl start rfid-hid-gatt.service
