import os
import secrets
from dataclasses import dataclass

from rfid_inventory.catalog.epc12_codec import codigo_activo_a_epc12_hex, epc12_hex_a_codigo_activo


@dataclass(frozen=True)
class ResultadoLecturaEtiqueta:
    """Resultado de leer una etiqueta (EPC en hex, código decodificado si aplica, bandera simulación)."""

    epc_en_hex: str
    codigo_decodificado: str | None
    simulado: bool


@dataclass(frozen=True)
class ResultadoEscrituraEtiqueta:
    """Resultado de programar el EPC (hex nuevo y si fue simulación)."""

    epc_nuevo_en_hex: str
    simulado: bool


class ServicioEscrituraEtiquetas:
    """Lógica del módulo «Escribir etiqueta»: simulación o lector real, fuera de la interfaz."""

    def __init__(self, usar_hardware: bool | None = None) -> None:
        """Si ``usar_hardware`` es ``None``, se usa solo la variable ``RFID_WRITE_USE_HARDWARE`` (compatibilidad). La app suele pasar un valor ya resuelto desde ``config.json``."""
        self._banco_epcs_simulados: set[str] = set()
        if usar_hardware is None:
            usar_hardware = os.environ.get("RFID_WRITE_USE_HARDWARE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}
        self._usar_hardware = bool(usar_hardware)

    @property
    def usar_hardware(self) -> bool:
        return self._usar_hardware

    def escanear_una_etiqueta(self, lector) -> ResultadoLecturaEtiqueta:
        """Lee una etiqueta. Con hardware activado usa el lector; si no, genera un EPC simulado."""
        if not self._usar_hardware:
            epc = secrets.token_bytes(12).hex()
            while epc in self._banco_epcs_simulados:
                epc = secrets.token_bytes(12).hex()
            self._banco_epcs_simulados.add(epc)
            return ResultadoLecturaEtiqueta(epc_en_hex=epc, codigo_decodificado=None, simulado=True)

        if not getattr(lector, "connected", False):
            raise RuntimeError("No hay lector conectado.")
        t = lector.leer_primera_etiqueta_una_encuesta()
        if not t:
            raise RuntimeError("No se detectó ninguna etiqueta.")
        epc = (t.epc_hex or "").strip().lower()
        return ResultadoLecturaEtiqueta(
            epc_en_hex=epc, codigo_decodificado=epc12_hex_a_codigo_activo(epc), simulado=False
        )

    def calcular_epc_desde_codigo(self, codigo_activo: str) -> str | None:
        codigo = (codigo_activo or "").strip()
        if not codigo:
            return None
        return codigo_activo_a_epc12_hex(codigo)

    def programar_epc(self, lector, epc_actual_hex: str, epc_nuevo_hex: str) -> ResultadoEscrituraEtiqueta:
        """Programa el EPC en la etiqueta o simula el resultado según ``usar_hardware``."""
        actual = (epc_actual_hex or "").strip().lower()
        nuevo = (epc_nuevo_hex or "").strip().lower()
        if not actual:
            raise RuntimeError("Primero escanea una etiqueta (EPC actual).")
        if not nuevo:
            raise RuntimeError("Escribe el código del activo para generar el EPC nuevo.")

        if not self._usar_hardware:
            return ResultadoEscrituraEtiqueta(epc_nuevo_en_hex=nuevo, simulado=True)

        if not getattr(lector, "connected", False):
            raise RuntimeError("No hay lector conectado.")
        lector.programar_epc12_en_etiqueta(epc_actual_hex=actual, epc_nuevo_hex=nuevo)
        return ResultadoEscrituraEtiqueta(epc_nuevo_en_hex=nuevo, simulado=False)
