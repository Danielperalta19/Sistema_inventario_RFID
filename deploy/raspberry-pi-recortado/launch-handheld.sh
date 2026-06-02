#!/usr/bin/env bash
# Arranque de la GUI en Raspberry Pi (autostart o acceso directo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DEFAULT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export RFID_REPO_ROOT="${RFID_REPO_ROOT:-${REPO_DEFAULT}}"
# Sin barra minimizar/cerrar en la ventana (lxpanel sigue). Para desactivar: RFID_SIN_BARRA_TITULO=0
# Si arriba no responde al tacto: RFID_WM_MARGIN_TOP=32

cd "${RFID_REPO_ROOT}"

if command -v flock >/dev/null 2>&1; then
  LOCK="${XDG_RUNTIME_DIR:-/tmp}/rfid-handheld.lock"
  exec 9>"${LOCK}"
  if ! flock -n 9; then
    echo "La app de inventario ya está en ejecución." >&2
    exit 0
  fi
fi

if command -v xset >/dev/null 2>&1; then
  xset s off 2>/dev/null || true
  xset s noblank 2>/dev/null || true
  xset -dpms 2>/dev/null || true
fi

PYTHON="${RFID_PYTHON:-python3}"
if [[ -x "${RFID_REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${RFID_REPO_ROOT}/.venv/bin/python"
fi

exec "${PYTHON}" -m rfid_inventory.ui.gui.handheld_app
