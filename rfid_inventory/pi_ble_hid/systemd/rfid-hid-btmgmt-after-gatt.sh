#!/bin/sh
# Tras levantar el HID (GATT), aplica btmgmt con margen. En RPi+BlueZ, un solo
# disparo a los 8s a veces no basta: el anuncio del GATT y bluetoothctl
# pisan "current settings". Dos pasadas con pausa alineó pruebas con "a mano".
# Journal: journalctl -t rfid-hid-btmgmt-after -b

jlog() { systemd-cat -t rfid-hid-btmgmt-after -p info; }

echo "start" | jlog
sleep 20
echo "btmgmt 1" | jlog
timeout 90 btmgmt -i hci0 advertising on 2>&1 | jlog || echo "btmgmt 1 -> exit $?" | jlog
sleep 20
echo "btmgmt 2" | jlog
timeout 90 btmgmt -i hci0 advertising on 2>&1 | jlog || echo "btmgmt 2 -> exit $?" | jlog
echo "end" | jlog
exit 0
