#!/bin/sh
# Tras registrar el servidor GATT: clase HID, connectable/advertising y confianza a emparejados.
# Lo invoca rfid-hid-gatt.service (ExecStartPost). Journal: journalctl -t rfid-hid-post-gatt

jlog() { systemd-cat -t rfid-hid-post-gatt -p info; }

sleep 3

if command -v hciconfig >/dev/null 2>&1; then
  hciconfig hci0 class 0x000540 2>&1 | jlog || true
fi

for cmd in "connectable on" "bondable on" "advertising on"; do
  # shellcheck disable=SC2086
  btmgmt -i hci0 $cmd > /tmp/rfid-btmgmt-post.log 2>&1 || true
  if [ -s /tmp/rfid-btmgmt-post.log ]; then
    cat /tmp/rfid-btmgmt-post.log | jlog
  fi
  echo "btmgmt -i hci0 $cmd done" | jlog
done
rm -f /tmp/rfid-btmgmt-post.log

timeout 15 bluetoothctl <<'BTEOF' 2>&1 | jlog || true
discoverable-timeout 0
pairable on
discoverable on
quit
BTEOF

# Auto-aceptar emparejamientos sin pantalla (agente por defecto de esta sesión)
timeout 8 bluetoothctl <<'BTEOF' 2>&1 | jlog || true
agent NoInputNoOutput
default-agent
quit
BTEOF

bluetoothctl devices Paired 2>/dev/null | while read -r _ mac _rest; do
  [ -n "$mac" ] || continue
  echo "trust $mac" | timeout 5 bluetoothctl 2>&1 | jlog || true
done

echo "rfid-hid-post-gatt finished" | jlog
