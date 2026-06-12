import os
import sys
import time

# Librería oficial embebida (vendor) para evitar fallos de pip/piwheels en Raspberry Pi.
_raiz_vendor = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
if os.path.isdir(os.path.join(_raiz_vendor, "rfid_r200")):
    if _raiz_vendor not in sys.path:
        sys.path.insert(0, _raiz_vendor)

from rfid_r200 import R200

# PC Gen2 para EPC de 96 bits (12 bytes). 0x3000 es habitual en tags Impinj/M100.
_PC_EPC_96_BITS = 0x3000


class LecturaEtiqueta:
    """Una lectura de etiqueta: EPC en hexadecimal, RSSI entero y PC (protocol control) si aplica."""

    def __init__(self, epc_hex, rssi, pc=None):
        self.epc_hex = epc_hex
        self.rssi = rssi
        self.pc = pc


class LectorR200:
    """Conexión serial al módulo R200: lecturas y escritura de EPC vía la librería embebida ``rfid_r200``."""

    def __init__(self) -> None:
        self._modulo_rfid = None

    @property
    def connected(self) -> bool:
        return self._modulo_rfid is not None

    def conectar(self, puerto, baudios, debug=False):
        if self._modulo_rfid is not None:
            return
        if not debug:
            debug = os.environ.get("RFID_SERIAL_DEBUG", "").strip() in {
                "1",
                "true",
                "TRUE",
                "yes",
            }
        self._modulo_rfid = R200(puerto, baudios, debug=debug)
        time.sleep(2.0)
        self._configurar_modulo_tras_conexion()

    def _configurar_modulo_tras_conexion(self) -> None:
        """Región US (902–928 MHz, adecuada para México) y demodulador; ignora fallos (p. ej. emulador Arduino)."""
        if self._modulo_rfid is None:
            return
        try:
            self._modulo_rfid.send_command(0x07, [0x21])
            self._modulo_rfid.receive()
        except Exception:
            pass
        try:
            self._modulo_rfid.set_demodulator_params(mixer_g=2, if_g=7, thrd=100)
        except Exception:
            pass
        try:
            self._modulo_rfid.set_power(26.0)
        except Exception:
            pass
        self._restaurar_inventario_abierto()

    def _restaurar_inventario_abierto(self) -> None:
        """Inventario sin filtro Select (todas las etiquetas visibles)."""
        if self._modulo_rfid is None:
            return
        try:
            self._modulo_rfid.limpiar_filtro_select()
        except Exception:
            pass

    def cerrar(self):
        if self._modulo_rfid is None:
            return
        self._modulo_rfid.close()
        self._modulo_rfid = None

    def leer_etiquetas_una_ronda(self):
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        tags, _ = self._modulo_rfid.read_tags()
        salida = []
        for t in tags:
            salida.append(
                LecturaEtiqueta(epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi), pc=int(t.pc))
            )
        return salida

    def leer_primera_etiqueta_una_encuesta(self):
        """Lee una etiqueta con el mismo camino que inventario (sin tocar Select antes)."""
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        try:
            self._modulo_rfid.detener_poll_multiple()
        except Exception:
            pass
        time.sleep(0.05)
        for _ in range(8):
            tags = self.leer_etiquetas_una_ronda()
            if tags:
                return tags[0]
            time.sleep(0.08)
        return None

    def _leer_primera_en_campo(self, restaurar: bool = True, intentos: int = 5):
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        if restaurar:
            self._restaurar_inventario_abierto()
            time.sleep(0.1)
        for _ in range(intentos):
            tags, _ = self._modulo_rfid.read_tags()
            if tags:
                t = tags[0]
                return LecturaEtiqueta(
                    epc_hex=bytes(t.epc).hex(), rssi=int(t.rssi), pc=int(t.pc)
                )
            time.sleep(0.1)
        return None

    @staticmethod
    def _normalizar_hex_epc(epc_hex: str) -> str:
        epc_hex = (epc_hex or "").strip().lower()
        if len(epc_hex) % 2:
            epc_hex = "0" + epc_hex
        return epc_hex

    @staticmethod
    def _mascaras_select(epc_hex: str, pc: int) -> list[bytes]:
        """Variantes de máscara Select (completa, por PC y 96-bit demo)."""
        epc_hex = LectorR200._normalizar_hex_epc(epc_hex)
        if len(epc_hex) < 8:
            raise ValueError("EPC demasiado corto para Select.")
        raw = bytes.fromhex(epc_hex)
        mascaras: list[bytes] = []
        vistos: set[bytes] = set()

        def _agregar(b: bytes) -> None:
            if len(b) >= 2 and b not in vistos:
                vistos.add(b)
                mascaras.append(b)

        _agregar(raw)
        palabras = (int(pc) >> 11) & 0x1F
        if palabras > 0:
            _agregar(raw[: min(palabras * 2, len(raw))])
        if len(raw) >= 12:
            _agregar(raw[:12])
        return mascaras

    @staticmethod
    def _epc_coincide(a: str, b: str) -> bool:
        a = (a or "").strip().lower()
        b = (b or "").strip().lower()
        if not a or not b:
            return False
        n = min(len(a), len(b), 24)
        return a[:n] == b[:n]

    def _verificar_epc_programado(self, epc_esperado_24: str) -> bool:
        esperado = (epc_esperado_24 or "").strip().lower()[:24]
        self._restaurar_inventario_abierto()
        time.sleep(0.1)
        for _ in range(2):
            tags, _ = self._modulo_rfid.read_tags()
            for t in tags:
                leido = bytes(t.epc).hex()
                if self._epc_coincide(esperado, leido):
                    return True
            time.sleep(0.08)
        return False

    def _intentar_write_epc(
        self,
        datos_epc: bytes,
        access_password: int,
        sa_word: int = 2,
        incluir_pc: bool = False,
        pc: int = _PC_EPC_96_BITS,
    ) -> bool:
        payload = datos_epc
        sa = int(sa_word)
        if incluir_pc:
            payload = int(pc).to_bytes(2, "big") + datos_epc
            sa = 1
        try:
            return self._modulo_rfid.write_label(
                access_password=int(access_password),
                membank=0x01,
                sa_word=sa,
                data=payload,
            )
        except RuntimeError:
            raise
        except Exception:
            return False

    def _aplicar_preparacion_escritura(
        self, modo: str, mascara: bytes | None, sel_param: int, select_mode: int | None
    ) -> None:
        self._modulo_rfid.preparar_escritura_minima()
        time.sleep(0.06)
        if modo == "minima":
            return
        if modo == "sin_select":
            self._modulo_rfid.preparar_escritura_sin_select()
            return
        if modo == "select_solo" and mascara is not None:
            self._modulo_rfid.configurar_select_solo_parametros(
                mascara, sel_param=int(sel_param)
            )
            return
        if modo == "select_modo" and mascara is not None and select_mode is not None:
            self._modulo_rfid.set_select_epc_mask(mascara, sel_param=int(sel_param))
            self._modulo_rfid.set_select_mode(int(select_mode))

    def programar_epc12_en_etiqueta(
        self,
        epc_actual_hex: str,
        epc_nuevo_hex: str,
        access_password: int = 0,
        pc_etiqueta: int | None = None,
    ) -> None:
        """Escribe EPC 12 bytes (palabra 2, demo Pointer 02 / Counter 06)."""
        if self._modulo_rfid is None:
            raise RuntimeError("No conectado")
        nuevo = (epc_nuevo_hex or "").strip().lower()
        if not nuevo or len(nuevo) < 24:
            raise ValueError("EPC inválido (se esperan 24 hex / 12 bytes).")

        epc_escaneado = self._normalizar_hex_epc(epc_actual_hex)
        if len(epc_escaneado) < 8:
            raise RuntimeError("Primero escanea una etiqueta.")

        pc = int(pc_etiqueta if pc_etiqueta is not None else _PC_EPC_96_BITS)
        datos_epc = bytes.fromhex(nuevo[:24])
        ultimo_error = ""

        try:
            mascaras = self._mascaras_select(epc_escaneado, pc)
            mascara_full = mascaras[0]
            mascara_96 = next((m for m in mascaras if len(m) == 12), mascaras[-1])

            intentos: list[tuple] = [
                ("minima", None, 0, None, False),
                ("sin_select", None, 0, None, False),
                ("select_solo", mascara_full, 0x01, None, False),
                ("select_solo", mascara_96, 0x01, None, False),
                ("select_modo", mascara_96, 0x01, 0x02, False),
                ("select_modo", mascara_96, 0x01, 0x00, False),
                ("select_modo", mascara_96, 0x01, 0x02, True),
            ]

            for potencia in (20.0, 26.0):
                try:
                    self._modulo_rfid.set_power(potencia)
                except Exception:
                    pass
                for modo, mascara, sel_param, select_mode, incluir_pc in intentos:
                    try:
                        self._aplicar_preparacion_escritura(
                            modo, mascara, sel_param, select_mode
                        )
                    except RuntimeError as e:
                        ultimo_error = str(e)
                        continue
                    time.sleep(0.08)
                    try:
                        if self._intentar_write_epc(
                            datos_epc,
                            access_password,
                            incluir_pc=incluir_pc,
                            pc=pc,
                        ):
                            return
                    except RuntimeError as e:
                        ultimo_error = str(e)
                    else:
                        ultimo_error = "el módulo no confirmó la escritura"
                    if self._verificar_epc_programado(nuevo[:24]):
                        return

            detalle = (ultimo_error or "sin detalle del módulo").strip()
            if "0x10" in detalle or "escritura rechazada" in detalle.lower():
                detalle = (
                    "Select/EPC no coincidió. EPC escaneado (hex): {0}. "
                    "Activa RFID_SERIAL_DEBUG=1 y ejecuta diagnostico_escritura_r200.py"
                ).format(epc_escaneado[:32])
            raise RuntimeError(
                "No se pudo grabar ({0}). Una etiqueta quieta sobre la antena.".format(detalle)
            )
        finally:
            self._restaurar_inventario_abierto()
