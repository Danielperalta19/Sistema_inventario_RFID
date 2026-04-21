#!/bin/sh
# Deja el adaptador visible y con anuncio LE. Journal: journalctl -t rfid-hid-bt-up -b

jlog() { systemd-cat -t rfid-hid-bt-up -p info; }

echo "start" | jlog
sleep 3

timeout 8 bluetoothctl power on 2>&1 | jlog || true
timeout 8 bluetoothctl pairable on 2>&1 | jlog || true
timeout 8 bluetoothctl discoverable on 2>&1 | jlog || true

# btmgmt: salida y codigo reales (sin silenciar stderr)
_run_btmgmt() {
  _a="$1"
  _f="/tmp/rfid-bt-$$.log"
  timeout 15 btmgmt -i hci0 "$_a" >"$_f" 2>&1
  _e=$?
  if [ -s "$_f" ]; then cat "$_f" | jlog; else echo "(sin salida)" | jlog; fi
  echo "btmgmt $_a -> exit $_e" | jlog
  rm -f "$_f"
}

_run_btmgmt "connectable on"
_run_btmgmt "advertising on"

timeout 5 bluetoothctl advertise on 2>&1 | jlog || true

echo "end" | jlog
exit 0
