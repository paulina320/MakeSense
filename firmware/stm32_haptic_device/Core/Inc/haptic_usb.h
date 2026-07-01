#ifndef HAPTIC_USB_H
#define HAPTIC_USB_H

#include <stdbool.h>
#include <stdint.h>

void HapticUsb_OnRx(uint8_t *data, uint32_t length);
uint16_t HapticUsb_Available(void);
bool HapticUsb_ReadByte(uint8_t *value);
bool HapticUsb_Write(const uint8_t *data, uint16_t length);
bool HapticUsb_WriteText(const char *text);

#endif
