/*

    - CMD_MULTIPLE_POLL_INSTRUCTION (0x27): responde con varias lecturas
    - CMD_STOP_MULTIPLE_POLL (0x28): responde OK
    - CMD_GET_MODULE_INFO (0x03): texto fijo

  Frame:
    0xAA | Type | Cmd | LenMSB | LenLSB | Params... | Checksum | 0xDD
*/

#include <Arduino.h>
#include <string.h>

static const uint8_t HDR = 0xAA;
static const uint8_t END = 0xDD;

static const uint8_t TYPE_COMMAND = 0x00;
static const uint8_t TYPE_RESPONSE = 0x01;
static const uint8_t TYPE_NOTIFICATION = 0x02;

static const uint8_t CMD_GET_MODULE_INFO = 0x03;
static const uint8_t CMD_MULTIPLE_POLL = 0x27;
static const uint8_t CMD_STOP_MULTIPLE_POLL = 0x28;
static const uint8_t CMD_SINGLE_POLL = 0x22; // el tag-notify usa este cmd
static const uint8_t CMD_EXECUTION_FAILURE = 0xFF;

static const uint32_t UART_BAUD = 115200;

static const uint8_t RSSI_MIN = 18;
static const uint8_t RSSI_MAX = 62;

static const uint16_t PC_DEFAULT = 0x3000;
static const uint16_t CRC_DEFAULT = 0x0000;

static const uint16_t TAG_GAP_MS = 15;
static const uint8_t MULTI_MIN = 6;
static const uint8_t MULTI_MAX = 22;

// EPC = 12 bytes 
static const uint8_t EPC_LIST[][12] = {
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x30}, // 750100000000
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x31}, // 750100000001
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x32}, // 750100000002
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x33}, // 750100000003
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x34}, // 750100000004
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x35}, // 750100000005
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x36}, // 750100000006
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x37}, // 750100000007
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x38}, // 750100000008
  {0x37,0x35,0x30,0x31,0x30,0x30,0x30,0x30,0x30,0x30,0x30,0x39}, // 750100000009
};

static const uint8_t EPC_COUNT = sizeof(EPC_LIST) / sizeof(EPC_LIST[0]);

static uint8_t checksum(uint8_t type, uint8_t cmd, uint16_t len, const uint8_t* params) {
  uint32_t s = 0;
  s = s + type;
  s = s + cmd;
  s = s + (uint8_t)((uint16_t)(len / 256) & 0xFF);
  s = s + (uint8_t)((uint16_t)(len % 256) & 0xFF);
  for (uint16_t i = 0; i < len; i++) {
    s = s + params[i];
  }
  return (uint8_t)(s & 0xFF);
}

static void sendFrame(uint8_t type, uint8_t cmd, const uint8_t* params, uint16_t len) {
  Serial.write(HDR);
  Serial.write(type);
  Serial.write(cmd);
  Serial.write((uint8_t)((uint16_t)(len / 256) & 0xFF));
  Serial.write((uint8_t)((uint16_t)(len % 256) & 0xFF));
  for (uint16_t i = 0; i < len; i++) {
    Serial.write(params[i]);
  }
  Serial.write(checksum(type, cmd, len, params));
  Serial.write(END);
}

static void sendError(uint8_t code) {
  uint8_t p[1] = { code };
  sendFrame(TYPE_RESPONSE, CMD_EXECUTION_FAILURE, p, 1);
}

static uint8_t rssi() {
  return (uint8_t)random((int)RSSI_MIN, (int)RSSI_MAX + 1);
}

static const uint8_t* nextEpc() {
  static uint8_t idx = 0;
  const uint8_t* out = EPC_LIST[idx];
  idx = (uint8_t)((idx + 1) % EPC_COUNT);
  return out;
}

static void sendTagNotify(const uint8_t epc12[12]) {
  uint8_t p[17];
  p[0] = rssi();
  p[1] = (uint8_t)((uint16_t)(PC_DEFAULT / 256) & 0xFF);
  p[2] = (uint8_t)((uint16_t)(PC_DEFAULT % 256) & 0xFF);
  for (uint8_t i = 0; i < 12; i++) {
    p[3 + i] = epc12[i];
  }
  p[15] = (uint8_t)((uint16_t)(CRC_DEFAULT / 256) & 0xFF);
  p[16] = (uint8_t)((uint16_t)(CRC_DEFAULT % 256) & 0xFF);
  sendFrame(TYPE_NOTIFICATION, CMD_SINGLE_POLL, p, 17);
}

struct InFrame {
  uint8_t type;
  uint8_t cmd;
  uint16_t len;
  uint8_t params[256];
  uint8_t csum;
};

static bool readExact(uint8_t* out, uint16_t n, uint16_t timeoutMs) {
  uint32_t t0 = millis();
  uint16_t got = 0;
  while (got < n) {
    if (Serial.available() > 0) {
      out[got++] = (uint8_t)Serial.read();
      continue;
    }
    if ((uint32_t)(millis() - t0) >= timeoutMs) {
      return false;
    }
  }
  return true;
}

static bool readFrame(InFrame& f) {
  while (Serial.available() > 0) {
    if ((uint8_t)Serial.peek() == HDR) {
      break;
    }
    Serial.read();
  }
  if (Serial.available() < 5) return false;

  uint8_t h = 0;
  if (!readExact(&h, 1, 60)) return false;
  if (h != HDR) return false;

  uint8_t fixed[4];
  if (!readExact(fixed, 4, 60)) return false;
  f.type = fixed[0];
  f.cmd = fixed[1];
  f.len = (uint16_t)((uint16_t)fixed[2] * 256 + (uint16_t)fixed[3]);
  if (f.len > sizeof(f.params)) return false;

  if (f.len > 0) {
    if (!readExact(f.params, f.len, 100)) return false;
  }
  if (!readExact(&f.csum, 1, 60)) return false;
  uint8_t endb = 0;
  if (!readExact(&endb, 1, 60)) return false;
  if (endb != END) return false;

  return checksum(f.type, f.cmd, f.len, f.params) == f.csum;
}

static void handle(const InFrame& f) {
  if (f.type != TYPE_COMMAND) {
    return;
  }

  if (f.cmd == CMD_GET_MODULE_INFO) {
    uint8_t tipo = 0x00;
    if (f.len >= 1) {
      tipo = f.params[0];
    }
    const char* text = "R200 EMU";
    uint8_t p[1 + 16];
    p[0] = tipo;
    uint8_t n = 0;
    while (text[n] != '\0' && n < 15) {
      p[1 + n] = (uint8_t)text[n];
      n++;
    }
    sendFrame(TYPE_RESPONSE, CMD_GET_MODULE_INFO, p, (uint16_t)(1 + n));
    return;
  }

  if (f.cmd == CMD_STOP_MULTIPLE_POLL) {
    const uint8_t ok[1] = { 0x00 };
    sendFrame(TYPE_RESPONSE, CMD_STOP_MULTIPLE_POLL, ok, 1);
    return;
  }

  if (f.cmd == CMD_MULTIPLE_POLL) {
    if (EPC_COUNT == 0) {
      sendError(0x15);
      return;
    }
    uint8_t n = (uint8_t)random(MULTI_MIN, (uint8_t)(MULTI_MAX + 1));
    for (uint8_t i = 0; i < n; i++) {
      sendTagNotify(nextEpc());
      delay(TAG_GAP_MS);
    }
    return;
  }

  sendError(0x17);
}

void setup() {
  Serial.begin(UART_BAUD);
  Serial.setTimeout(100);
  randomSeed((unsigned long)micros() ^ (unsigned long)analogRead(A0));
}

void loop() {
  InFrame f;
  if (readFrame(f)) {
    handle(f);
  }
}
