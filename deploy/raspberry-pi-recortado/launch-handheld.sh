#!/usr/bin/env bash
# Arranque de la GUI en modo kiosco (pantalla completa). Pensado para Raspberry Pi OS con escritorio.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Raíz del repo: .../deploy/raspberry-pi-recortado/ -> sube dos niveles
REPO_DEFAULT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export RFID_REPO_ROOT="${RFID_REPO_ROOT:-${REPO_DEFAULT}}"

cd "${RFID_REPO_ROOT}"

# Evitar salvapantallas que apaguen la TFT durante inventario
if command -v xset >/dev/null 2>&1; then
  xset s off 2>/dev/null || true
  xset s noblank 2>/dev/null || true
  xset -dpms 2>/dev/null || true
fi

PYTHON="${RFID_PYTHON:-python3}"
if [[ -x "${RFID_REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${RFID_REPO_ROOT}/.venv/bin/python"
fi

exec "${PYTHON}" -m rfid_inventory.ui.gui.handheld_app --kiosk
