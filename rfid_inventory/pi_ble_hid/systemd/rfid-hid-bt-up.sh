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
  # Sin esto, BlueZ avisa: "discoverable-timeout not set(0) is not recommended" y a veces
  # pasa Discoverable: no poco despues. Si el comando no existe en tu bluez, falla y se ignora.
  timeout 8 bluetoothctl discoverable-timeout 0 2>&1 | jlog || true
  timeout 8 bluetoothctl pairable on 2>&1 | jlog || true
  timeout 8 bluetoothctl discoverable on 2>&1 | jlog || true

  # Anuncio LE; al vencer el timeout, en algunas versiones cesa el anuncio o baja discoverable
  timeout 90 bluetoothctl advertise on 2>&1 | jlog || true

  # Reforzar descubrimiento (advertise a veces deja discoverable en no)
  timeout 5 bluetoothctl discoverable-timeout 0 2>&1 | jlog || true
  timeout 5 bluetoothctl discoverable on 2>&1 | jlog || true

  echo "end" | jlog
  exit 0
} 8>/run/lock/rfid-hid-bt-up.lock
