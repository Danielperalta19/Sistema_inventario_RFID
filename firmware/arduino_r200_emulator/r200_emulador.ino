/*
  Emulador básico del módulo RFID R200 para Arduino Nano.

  Objetivo:
  - Que tu Raspberry (Python + la librería rfid-r200) lo vea como si fuera un R200 real.
  - Por ahora enfocándonos en: single poll (0x22), multiple poll (0x27) y stop (0x28).

  Formato de frame (igual que en la librería Python):
    0xAA | Type | Command | LenMSB | LenLSB | Params... | Checksum | 0xDD

  Checksum:
    suma de bytes desde Type hasta el último parámetro, y luego & 0xFF
*/

#include <Arduino.h>

// ------------------ Constantes del protocolo ------------------
static const uint8_t R200_FRAME_HEADER = 0xAA;
static const uint8_t R200_FRAME_END    = 0xDD;

static const uint8_t FRAME_TYPE_COMMAND      = 0x00;
static const uint8_t FRAME_TYPE_RESPONSE     = 0x01;
static const uint8_t FRAME_TYPE_NOTIFICATION = 0x02;

static const uint8_t CMD_SINGLE_POLL_INSTRUCTION   = 0x22;
static const uint8_t CMD_MULTIPLE_POLL_INSTRUCTION = 0x27;
static const uint8_t CMD_STOP_MULTIPLE_POLL        = 0x28;
static const uint8_t CMD_GET_MODULE_INFO           = 0x03;
static const uint8_t CMD_EXECUTION_FAILURE         = 0xFF;

static const uint8_t ERR_INVENTORY_FAIL = 0x15; // "No tags detected"
static const uint8_t ERR_COMMAND_ERROR  = 0x17; // "Can't execute command"

// ------------------ UART ------------------
// El Nano usa el Serial hardware (pines D0/D1) para hablar como si fuera el R200.
static const uint32_t UART_BAUD = 115200;

// ------------------ Gatillo (trigger) para simular un escaneo real ------------------
// Conecta un botón entre el pin y GND. Usamos INPUT_PULLUP:
// - suelto  = HIGH
// - presionado = LOW
static const bool SIMULAR_GATILLO = true;
static const uint8_t PIN_GATILLO = 2;               // D2
static const uint16_t DEBOUNCE_GATILLO_MS = 30;

// ------------------ Comportamiento del emulador ------------------
// La librería Python lee hasta timeout, así que conviene responder rápido.
static const uint16_t ESPACIO_ENTRE_TAGS_MS = 20;
static const uint16_t DURACION_MULTI_MS = 250;
// Cantidad de EPCs que se "ven" por comando (aleatorio, con repetición permitida).
static const uint8_t SINGLE_MIN_LECTURAS = 1;
static const uint8_t SINGLE_MAX_LECTURAS = 4;
static const uint8_t MULTI_MIN_LECTURAS = 5;
static const uint8_t MULTI_MAX_LECTURAS = 25;

// ------------------ Tags simulados ------------------
// Cada EPC debe tener 12 bytes (así lo espera R200PoolResponse.parse en Python).
static const uint8_t EPC_LIST[][12] = {
  {0x30,0x00,0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88,0x99,0xAA},
  {0x30,0x00,0xDE,0xAD,0xBE,0xEF,0x00,0x11,0x22,0x33,0x44,0x55},
  {0x30,0x00,0x10,0x20,0x30,0x40,0x50,0x60,0x70,0x80,0x90,0xA0},
  {0x30,0x00,0x01,0x23,0x45,0x67,0x89,0xAB,0xCD,0xEF,0x13,0x37},
  {0x30,0x00,0xFE,0xDC,0xBA,0x98,0x76,0x54,0x32,0x10,0x00,0x01},
  {0x30,0x00,0xAA,0xBB,0xCC,0xDD,0xEE,0xFF,0x00,0x11,0x22,0x33},
  {0x30,0x00,0x12,0x34,0x56,0x78,0x9A,0xBC,0xDE,0xF0,0x0D,0x0A},
  {0x30,0x00,0xBE,0xEF,0xCA,0xFE,0xFA,0xCE,0xB0,0x0C,0x12,0x34},
  {0x30,0x00,0x55,0x44,0x33,0x22,0x11,0x00,0xFF,0xEE,0xDD,0xCC},
  {0x30,0x00,0x99,0x88,0x77,0x66,0x55,0x44,0x33,0x22,0x11,0x00},
};
static const uint8_t EPC_COUNT = sizeof(EPC_LIST) / sizeof(EPC_LIST[0]);

// Valores que acompañan el EPC (la librería no valida CRC, pero sí requiere la estructura).
static const uint8_t RSSI_DEFAULT = 0x2A;
static const uint16_t PC_DEFAULT  = 0x3000;
static const uint16_t CRC_DEFAULT = 0x0000;

// ------------------ Variables de "modo multiple" ------------------
static bool multiActivo = false;
static uint32_t multiHastaMs = 0;
static uint32_t ultimoEnvioMs = 0;
static uint16_t multiLecturasRestantes = 0;

// Estado del gatillo
static bool gatilloPresionado = false;
static bool gatilloUltimoNivel = true; // HIGH (por pullup)
static uint32_t gatilloUltimoCambioMs = 0;
static bool escaneoPorGatillo = false;

static void iniciarEscaneoPorGatillo() {
  escaneoPorGatillo = true;
  multiActivo = true;
  ultimoEnvioMs = 0;
  // En modo gatillo queremos "stream" continuo hasta que sueltes.
  // Para reutilizar la lógica, ponemos un número grande.
  multiLecturasRestantes = 0xFFFF;
  multiHastaMs = 0; // no se usa cuando escaneoPorGatillo=true
}

static void detenerEscaneoPorGatillo() {
  escaneoPorGatillo = false;
  multiActivo = false;
  multiLecturasRestantes = 0;
  multiHastaMs = 0;
}

static void actualizarGatillo() {
  if (!SIMULAR_GATILLO) return;

  bool nivel = (digitalRead(PIN_GATILLO) == HIGH); // true=HIGH suelto, false=LOW presionado
  uint32_t ahora = millis();

  if (nivel != gatilloUltimoNivel) {
    gatilloUltimoNivel = nivel;
    gatilloUltimoCambioMs = ahora;
    return;
  }

  // Debounce: solo aceptamos el cambio si se mantuvo estable el tiempo definido
  if (gatilloUltimoCambioMs != 0 && (ahora - gatilloUltimoCambioMs) < DEBOUNCE_GATILLO_MS) return;

  bool presionado = !nivel;
  if (presionado != gatilloPresionado) {
    gatilloPresionado = presionado;
    if (gatilloPresionado) iniciarEscaneoPorGatillo();
    else detenerEscaneoPorGatillo();
  }
}

// ------------------ Utilidades para armar frames ------------------
static uint8_t calcularChecksum(uint8_t type, uint8_t cmd, uint16_t paramLen, const uint8_t* params) {
  uint32_t suma = 0;
  suma += type;
  suma += cmd;
  suma += (uint8_t)((paramLen >> 8) & 0xFF);
  suma += (uint8_t)(paramLen & 0xFF);
  for (uint16_t i = 0; i < paramLen; i++) suma += params[i];
  return (uint8_t)(suma & 0xFF);
}

static void enviarFrame(uint8_t type, uint8_t cmd, const uint8_t* params, uint16_t paramLen) {
  Serial.write(R200_FRAME_HEADER);
  Serial.write(type);
  Serial.write(cmd);
  Serial.write((uint8_t)((paramLen >> 8) & 0xFF));
  Serial.write((uint8_t)(paramLen & 0xFF));
  for (uint16_t i = 0; i < paramLen; i++) Serial.write(params[i]);
  Serial.write(calcularChecksum(type, cmd, paramLen, params));
  Serial.write(R200_FRAME_END);
}

static void enviarError(uint8_t codigo) {
  uint8_t p[1] = { codigo };
  enviarFrame(FRAME_TYPE_RESPONSE, CMD_EXECUTION_FAILURE, p, 1);
}

static void enviarFrameTag(const uint8_t epc12[12], uint8_t tipoFrame) {
  // Params: RSSI(1) + PC(2) + EPC(12) + CRC(2) = 17 bytes (esto espera la librería)
  uint8_t p[17];
  p[0] = RSSI_DEFAULT;
  p[1] = (uint8_t)((PC_DEFAULT >> 8) & 0xFF);
  p[2] = (uint8_t)(PC_DEFAULT & 0xFF);
  for (uint8_t i = 0; i < 12; i++) p[3 + i] = epc12[i];
  p[15] = (uint8_t)((CRC_DEFAULT >> 8) & 0xFF);
  p[16] = (uint8_t)(CRC_DEFAULT & 0xFF);

  // IMPORTANTE: el "command" del frame del tag debe ser 0x22 (así lo filtra la librería).
  enviarFrame(tipoFrame, CMD_SINGLE_POLL_INSTRUCTION, p, 17);
}

static const uint8_t* epcAleatorio() {
  if (EPC_COUNT == 0) return nullptr;
  uint8_t idx = (uint8_t)random(0, EPC_COUNT);
  return EPC_LIST[idx];
}

static void enviarLecturasAleatorias(uint8_t tipoFrame, uint8_t minLecturas, uint8_t maxLecturas) {
  if (EPC_COUNT == 0) {
    enviarError(ERR_INVENTORY_FAIL);
    return;
  }

  if (maxLecturas < minLecturas) maxLecturas = minLecturas;
  uint8_t cantidad = (uint8_t)random(minLecturas, (uint8_t)(maxLecturas + 1));

  for (uint8_t i = 0; i < cantidad; i++) {
    const uint8_t* epc = epcAleatorio();
    if (!epc) break;
    enviarFrameTag(epc, tipoFrame);
    delay(ESPACIO_ENTRE_TAGS_MS);
  }
}

// ------------------ Lectura simple de un frame ------------------
// En vez de una máquina de estados, hacemos:
// 1) Buscar 0xAA
// 2) Leer Type, Command, LenMSB, LenLSB
// 3) Leer params, checksum, 0xDD
struct FrameEntrante {
  uint8_t type;
  uint8_t cmd;
  uint16_t len;
  uint8_t params[256];
  uint8_t checksum;
};

static bool leerFrameSiEstaCompleto(FrameEntrante& f) {
  // Buscar el header 0xAA (descartando basura)
  while (Serial.available() > 0) {
    if ((uint8_t)Serial.peek() == R200_FRAME_HEADER) break;
    Serial.read();
  }

  // Necesitamos al menos header + type + cmd + len(2) = 5 bytes para saber cuánto leer
  if (Serial.available() < 5) return false;

  // Consumir header
  if ((uint8_t)Serial.read() != R200_FRAME_HEADER) return false;

  f.type = (uint8_t)Serial.read();
  f.cmd = (uint8_t)Serial.read();
  uint8_t msb = (uint8_t)Serial.read();
  uint8_t lsb = (uint8_t)Serial.read();
  f.len = ((uint16_t)msb << 8) | (uint16_t)lsb;

  if (f.len > sizeof(f.params)) {
    // Longitud inválida: descartamos y re-sincronizamos
    return false;
  }

  // Necesitamos que esté todo el frame completo: params + checksum + end
  const uint16_t faltan = f.len + 2;
  if (Serial.available() < faltan) return false;

  for (uint16_t i = 0; i < f.len; i++) f.params[i] = (uint8_t)Serial.read();
  f.checksum = (uint8_t)Serial.read();
  uint8_t endByte = (uint8_t)Serial.read();
  if (endByte != R200_FRAME_END) return false;

  // Validar checksum
  uint8_t esperado = calcularChecksum(f.type, f.cmd, f.len, f.params);
  return (esperado == f.checksum);
}

// ------------------ Manejo de comandos ------------------
static void manejarFrame(const FrameEntrante& f) {
  // Solo aceptamos frames tipo "command" (0x00)
  if (f.type != FRAME_TYPE_COMMAND) return;

  if (f.cmd == CMD_SINGLE_POLL_INSTRUCTION) {
    // En un escaneo real no siempre aparecen todos; simulamos una cantidad aleatoria con repetición.
    // En el protocolo, los tags se reportan como "Notification frame" (Type=0x02).
    enviarLecturasAleatorias(FRAME_TYPE_NOTIFICATION, SINGLE_MIN_LECTURAS, SINGLE_MAX_LECTURAS);
    return;
  }

  if (f.cmd == CMD_MULTIPLE_POLL_INSTRUCTION) {
    // Activar modo multiple y mandar un burst inmediato
    multiActivo = true;
    multiHastaMs = millis() + DURACION_MULTI_MS;
    ultimoEnvioMs = 0;
    multiLecturasRestantes = (uint16_t)random(MULTI_MIN_LECTURAS, (uint16_t)(MULTI_MAX_LECTURAS + 1));
    // Burst inmediato (para que el host lea algo antes del timeout)
    enviarLecturasAleatorias(FRAME_TYPE_NOTIFICATION, 1, 6);
    return;
  }

  if (f.cmd == CMD_STOP_MULTIPLE_POLL) {
    multiActivo = false;
    multiHastaMs = 0;
    multiLecturasRestantes = 0;
    const uint8_t ok[1] = { 0x00 };
    enviarFrame(FRAME_TYPE_RESPONSE, CMD_STOP_MULTIPLE_POLL, ok, 1);
    return;
  }

  if (f.cmd == CMD_GET_MODULE_INFO) {
    // Según el protocolo: el primer byte de la respuesta es el "tipo" pedido (0x00 HW, 0x01 SW, 0x02 fabricante)
    uint8_t tipoInfo = 0x00;
    if (f.len >= 1) tipoInfo = f.params[0];

    const char* texto = "M100 V1.00"; // valor típico de ejemplo en el documento
    if (tipoInfo == 0x01) texto = "SW V1.00";
    if (tipoInfo == 0x02) texto = "INNOD R200";

    uint8_t p[1 + 16]; // sobra; limitamos a 15 chars
    p[0] = tipoInfo;
    uint8_t n = 0;
    while (texto[n] != '\0' && n < 15) {
      p[1 + n] = (uint8_t)texto[n];
      n++;
    }
    enviarFrame(FRAME_TYPE_RESPONSE, CMD_GET_MODULE_INFO, p, (uint16_t)(1 + n));
    return;
  }

  // Comando no soportado
  enviarError(ERR_COMMAND_ERROR);
}

void setup() {
  Serial.begin(UART_BAUD);
  // Semilla para aleatoriedad (si A0 está "flotando" ayuda; si no, micros() igual varía).
  randomSeed((unsigned long)micros() ^ (unsigned long)analogRead(A0));

  if (SIMULAR_GATILLO) {
    pinMode(PIN_GATILLO, INPUT_PULLUP);
    gatilloUltimoNivel = true;
    gatilloPresionado = false;
    gatilloUltimoCambioMs = 0;
  }
}

void loop() {
  // 0) Leer el gatillo (si está habilitado)
  actualizarGatillo();

  // 1) Si llegó un frame completo y válido, lo procesamos
  FrameEntrante f;
  if (leerFrameSiEstaCompleto(f)) {
    manejarFrame(f);
  }

  // 2) Si estamos en modo "multiple", seguimos emitiendo tags un rato
  if (multiActivo) {
    uint32_t ahora = millis();

    // Si el multiple viene por comando (0x27), lo detenemos por tiempo (como antes).
    // Si viene por gatillo, NO lo detenemos por tiempo, solo por soltar el botón.
    if (!escaneoPorGatillo) {
      if ((int32_t)(ahora - multiHastaMs) >= 0) {
        multiActivo = false;
        return;
      }
    }

    if (EPC_COUNT == 0) {
      multiActivo = false;
      return;
    }

    if (multiLecturasRestantes == 0) {
      multiActivo = false;
      return;
    }

    if (ultimoEnvioMs == 0 || (ahora - ultimoEnvioMs) >= ESPACIO_ENTRE_TAGS_MS) {
      const uint8_t* epc = epcAleatorio();
      if (epc) {
        enviarFrameTag(epc, FRAME_TYPE_NOTIFICATION);
        multiLecturasRestantes--;
      } else {
        multiActivo = false;
      }
      ultimoEnvioMs = ahora;
    }
  }
}

