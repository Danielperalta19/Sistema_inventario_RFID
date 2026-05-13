#!/bin/sh
# Libera el puerto serial del lector RFID para la GUI de inventario.
# El servicio rfid-hid-gatt (gatt_server_rfid.py) también abre RFID_PORT.
set -e
exec sudo systemctl stop rfid-hid-gatt.service
