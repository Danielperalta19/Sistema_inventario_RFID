#!/bin/sh
# Deja el adaptador visible y anuncia LE. Journal: journalctl -t rfid-hid-bt-up -b
#
# En varias RPi+BlueZ, "btmgmt connectable|advertising on" bloquea (no vuelve) y
# con timeout 15 s sale 124; la publicidad estable se logra con bluetoothctl.

jlog() { systemd-cat -t rfid-hid-bt-up -p info; }

# Si rfid-hid-bt-up y -post se disparan a la vez, encolar (evita logs mezclados)
{
  flock -w 200 8 || { echo "flock: imposible tomar lock" | jlog; exit 0; }

  echo "start" | jlog
  sleep 3

  timeout 8 bluetoothctl power on 2>&1 | jlog || true
  timeout 8 bluetoothctl pairable on 2>&1 | jlog || true
  timeout 8 bluetoothctl discoverable on 2>&1 | jlog || true

  # Anuncio LE (en tu Pi esto reemplaza a btmgmt advertising sin colgarse)
  timeout 45 bluetoothctl advertise on 2>&1 | jlog || true

  echo "end" | jlog
  exit 0
} 8>/run/lock/rfid-hid-bt-up.lock
