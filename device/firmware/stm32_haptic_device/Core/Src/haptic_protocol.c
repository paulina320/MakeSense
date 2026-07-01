#include "haptic_protocol.h"

uint16_t HapticProtocol_Crc16Update(uint16_t crc, uint8_t data) {
  crc ^= (uint16_t)data << 8;
  for (uint8_t i = 0; i < 8U; i++) {
    if ((crc & 0x8000U) != 0U) {
      crc = (uint16_t)((crc << 1U) ^ 0x1021U);
    } else {
      crc = (uint16_t)(crc << 1U);
    }
  }
  return crc;
}

uint16_t HapticProtocol_Crc16(const uint8_t *data, uint16_t length) {
  uint16_t crc = 0xFFFFU;
  for (uint16_t i = 0; i < length; i++) {
    crc = HapticProtocol_Crc16Update(crc, data[i]);
  }
  return crc;
}

void HapticProtocol_BuildHeader(uint8_t *header, uint8_t type, uint16_t length, uint16_t sequence) {
  header[0] = HAPTIC_SYNC0;
  header[1] = HAPTIC_SYNC1;
  header[2] = type;
  header[3] = (uint8_t)(length & 0xFFU);
  header[4] = (uint8_t)(length >> 8);
  header[5] = (uint8_t)(sequence & 0xFFU);
  header[6] = (uint8_t)(sequence >> 8);
}

uint16_t HapticProtocol_FrameCrc(uint8_t type, uint16_t length, uint16_t sequence, const uint8_t *payload) {
  uint8_t header[HAPTIC_FRAME_HEADER_SIZE];
  HapticProtocol_BuildHeader(header, type, length, sequence);
  uint16_t crc = HapticProtocol_Crc16(header, sizeof(header));
  for (uint16_t i = 0; i < length; i++) {
    crc = HapticProtocol_Crc16Update(crc, payload[i]);
  }
  return crc;
}
