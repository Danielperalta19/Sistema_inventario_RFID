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

  # Misma invocación de bluetoothctl: si cada comando es un proceso distinto, BlueZ
  # a veces sigue avisando "discoverable-timeout not set" al hacer discoverable on.
  # Advertise on va aparte (suele bloquear hasta timeout).
  timeout 20 bluetoothctl <<'BTEOF' 2>&1 | jlog || true
power on
discoverable-timeout 0
pairable on
discoverable on
quit
BTEOF

  # Anuncio LE; al vencer el timeout, en algunas versiones cesa el anuncio o baja discoverable
  timeout 90 bluetoothctl advertise on 2>&1 | jlog || true

  # Reforzar (una sola sesión)
  timeout 15 bluetoothctl <<'BTEOF' 2>&1 | jlog || true
discoverable-timeout 0
discoverable on
quit
BTEOF

  echo "end" | jlog
  exit 0
} 8>/run/lock/rfid-hid-bt-up.lock
