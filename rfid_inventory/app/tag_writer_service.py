import os
import secrets
from dataclasses import dataclass

from rfid_inventory.catalog.epc12_codec import asset_code_to_epc12_hex, epc12_hex_to_asset_code


@dataclass(frozen=True)
class TagScanResult:
    epc_hex: str
    decoded_code: str | None
    simulated: bool


@dataclass(frozen=True)
class TagWriteResult:
    new_epc_hex: str
    simulated: bool


class TagWriterService:
    """
    Capa de aplicación para el módulo "Escribir etiqueta".

    - Mantiene la lógica (simulación vs hardware real) fuera de la UI.
    - La UI solo renderiza strings y llama a este servicio.
    """

    def __init__(self) -> None:
        self._sim_bank: set[str] = set()
        self._use_hardware = os.environ.get("RFID_WRITE_USE_HARDWARE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}

    @property
    def use_hardware(self) -> bool:
        return self._use_hardware

    def scan_one_tag(self, driver) -> TagScanResult:
        """
        Lee 1 tag. Si `RFID_WRITE_USE_HARDWARE=1` usa el driver real, si no simula.
        """
        if not self._use_hardware:
            epc = secrets.token_bytes(12).hex()
            while epc in self._sim_bank:
                epc = secrets.token_bytes(12).hex()
            self._sim_bank.add(epc)
            return TagScanResult(epc_hex=epc, decoded_code=None, simulated=True)

        if not getattr(driver, "connected", False):
            raise RuntimeError("No hay lector conectado.")
        t = driver.read_one_tag_single_poll()
        if not t:
            raise RuntimeError("No se detectó ninguna etiqueta.")
        epc = (t.epc_hex or "").strip().lower()
        return TagScanResult(epc_hex=epc, decoded_code=epc12_hex_to_asset_code(epc), simulated=False)

    def compute_new_epc(self, asset_code: str) -> str | None:
        code = (asset_code or "").strip()
        if not code:
            return None
        return asset_code_to_epc12_hex(code)

    def write_epc(self, driver, current_epc_hex: str, new_epc_hex: str) -> TagWriteResult:
        """
        Programa el EPC. Si `RFID_WRITE_USE_HARDWARE=1` usa el driver real, si no simula.
        """
        cur = (current_epc_hex or "").strip().lower()
        new = (new_epc_hex or "").strip().lower()
        if not cur:
            raise RuntimeError("Primero escanea una etiqueta (EPC actual).")
        if not new:
            raise RuntimeError("Escribe el código del activo para generar el EPC nuevo.")

        if not self._use_hardware:
            return TagWriteResult(new_epc_hex=new, simulated=True)

        if not getattr(driver, "connected", False):
            raise RuntimeError("No hay lector conectado.")
        driver.write_epc12_hex(current_epc_hex=cur, new_epc12_hex=new)
        return TagWriteResult(new_epc_hex=new, simulated=False)

