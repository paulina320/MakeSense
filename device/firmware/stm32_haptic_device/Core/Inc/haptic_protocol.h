#ifndef HAPTIC_PROTOCOL_H
#define HAPTIC_PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

#define HAPTIC_SYNC0 0xA5U
#define HAPTIC_SYNC1 0x5AU
#define HAPTIC_MSG_SAMPLES 0x01U
#define HAPTIC_MSG_OUTPUT_BUFFER 0x02U
#define HAPTIC_MSG_ERROR 0x03U
#define HAPTIC_MSG_STATUS 0x04U
#define HAPTIC_MSG_LOOPBACK 0x05U
#define HAPTIC_MSG_IMU_SAMPLES 0x06U
#define HAPTIC_MAX_BINARY_PAYLOAD 256U
#define HAPTIC_FRAME_HEADER_SIZE 7U
#define HAPTIC_FRAME_CRC_SIZE 2U

uint16_t HapticProtocol_Crc16Update(uint16_t crc, uint8_t data);
uint16_t HapticProtocol_Crc16(const uint8_t *data, uint16_t length);
uint16_t HapticProtocol_FrameCrc(uint8_t type, uint16_t length, uint16_t sequence, const uint8_t *payload);
void HapticProtocol_BuildHeader(uint8_t *header, uint8_t type, uint16_t length, uint16_t sequence);

#endif
