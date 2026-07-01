#include "haptic_usb.h"

#include "main.h"
#include "usbd_cdc_if.h"
#include "usbd_def.h"

#include <string.h>

#define HAPTIC_USB_RX_RING_SIZE 16384U
#define HAPTIC_USB_TX_TIMEOUT_MS 20U

static volatile uint16_t rx_head = 0;
static volatile uint16_t rx_tail = 0;
static uint8_t rx_ring[HAPTIC_USB_RX_RING_SIZE];

static uint16_t next_index(uint16_t index) {
  return (uint16_t)((index + 1U) % HAPTIC_USB_RX_RING_SIZE);
}

void HapticUsb_OnRx(uint8_t *data, uint32_t length) {
  for (uint32_t i = 0; i < length; i++) {
    uint16_t next = next_index(rx_head);
    if (next == rx_tail) {
      break;
    }
    rx_ring[rx_head] = data[i];
    rx_head = next;
  }
}

uint16_t HapticUsb_Available(void) {
  uint16_t head = rx_head;
  uint16_t tail = rx_tail;
  if (head >= tail) {
    return (uint16_t)(head - tail);
  }
  return (uint16_t)(HAPTIC_USB_RX_RING_SIZE - tail + head);
}

bool HapticUsb_ReadByte(uint8_t *value) {
  if (rx_head == rx_tail) {
    return false;
  }
  *value = rx_ring[rx_tail];
  rx_tail = next_index(rx_tail);
  return true;
}

bool HapticUsb_Write(const uint8_t *data, uint16_t length) {
  uint32_t started = HAL_GetTick();
  while (length > 0U) {
    uint16_t chunk = length;
    uint8_t result = CDC_Transmit_FS((uint8_t *)data, chunk);
    if (result == USBD_OK) {
      data += chunk;
      length = (uint16_t)(length - chunk);
      started = HAL_GetTick();
      continue;
    }
    if ((HAL_GetTick() - started) > HAPTIC_USB_TX_TIMEOUT_MS) {
      return false;
    }
  }
  return true;
}

bool HapticUsb_WriteText(const char *text) {
  return HapticUsb_Write((const uint8_t *)text, (uint16_t)strlen(text));
}
