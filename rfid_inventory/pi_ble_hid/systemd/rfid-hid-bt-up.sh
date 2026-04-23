#!/bin/sh
# Deja el adaptador visible y anuncia LE. Journal: journalctl -t rfid-hid-bt-up -b
#
# bluetoothctl: base + advertise. A veces Windows no lista el dispositivo hasta forzar
# "btmgmt advertising on" (a veces bloquea; timeout + exit en el journal).

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

  # Refuerzo mgmt: en pruebas Windows ve el dispositivo; con timeout 25s a menudo
  # daba 124 ANTES de aplicar el estado — parecía que hacía falta a mano. Subimos a 120s.
  _bml="/tmp/rfid-btmgmt-$$.log"
  if timeout 120 btmgmt -i hci0 advertising on >"$_bml" 2>&1; then
    _bme=0
  else
    _bme=$?
  fi
  if [ -s "$_bml" ]; then cat "$_bml" | jlog; else echo "(btmgmt advertising: sin salida)" | jlog; fi
  echo "btmgmt -i hci0 advertising on -> exit $_bme" | jlog
  rm -f "$_bml"

  echo "end" | jlog
  exit 0
} 8>/run/lock/rfid-hid-bt-up.lock
