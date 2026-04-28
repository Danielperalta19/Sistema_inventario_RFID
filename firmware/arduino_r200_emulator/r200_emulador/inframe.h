// Tipos del protocolo R200 emulado.
// Debe vivir en un .h incluido al inicio del .ino porque el preprocesador del IDE
// de Arduino inserta prototipos de funciones después de los #include, y esos
// prototipos usan InFrame.
#ifndef INFRAME_H
#define INFRAME_H

#include <Arduino.h>

struct InFrame {
  uint8_t type;
  uint8_t cmd;
  uint16_t len;
  uint8_t params[256];
  uint8_t csum;
};

#endif /* INFRAME_H */

