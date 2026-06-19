"""Cliente HTTP simple para los endpoints de inventarios (usa `requests`).

Configurable vía variables de entorno:
- `RFID_WS_BASE_URL` (por defecto https://consultas-web-inf.cicese.mx:8445)
- `RFID_WS_TIMEOUT` (segundos, por defecto 8)
- `RFID_WS_LOAD_ASSETS` (si está a '1' o 'true', el loader intentará cargar activos desde el WS)
"""
from __future__ import annotations

import os
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return os.environ.get("RFID_WS_BASE_URL", "https://consultas-web-inf.cicese.mx:8445")


def _timeout() -> int:
    try:
        return int(os.environ.get("RFID_WS_TIMEOUT", "8"))
    except Exception:
        return 8


def get(path: str, params: dict | None = None) -> Optional[Any]:
    """GET a `BASE_URL + path` con `params`. Devuelve JSON o None en error."""
    url = _base_url().rstrip("/") + (path if path.startswith("/") else f"/{path}")
    try:
        resp = requests.get(url, params=params or {}, timeout=_timeout(), verify=True)
    except requests.RequestException as e:
        logger.warning("HTTP GET %s failed: %s", url, e)
        return None
    if resp.status_code != 200:
        logger.warning("HTTP GET %s status=%s body=%s", url, resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except Exception:
        logger.warning("Failed parsing JSON from %s", url)
        return None


def ws_load_assets_enabled() -> bool:
    # Por defecto activamos la carga de activos desde el web service (según preferencia del usuario).
    v = os.environ.get("RFID_WS_LOAD_ASSETS", "1").strip().lower()
    return v in {"1", "true", "yes"}
