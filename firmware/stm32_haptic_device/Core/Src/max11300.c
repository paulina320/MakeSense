#include "max11300.h"

#ifndef MAX11300_CS_GPIO_Port
#define MAX11300_CS_GPIO_Port GPIOA
#endif

#ifndef MAX11300_CS_Pin
#define MAX11300_CS_Pin GPIO_PIN_4
#endif

#ifndef MAX11300_CNVT_GPIO_Port
#define MAX11300_CNVT_GPIO_Port GPIOB
#endif

#ifndef MAX11300_CNVT_Pin
#define MAX11300_CNVT_Pin GPIO_PIN_0
#endif

static void max_cs(Max11300 *dev, GPIO_PinState state) {
  HAL_GPIO_WritePin(dev->cs_port, dev->cs_pin, state);
}

typedef enum {
  MAX_DMA_IDLE = 0,
  MAX_DMA_READ,
  MAX_DMA_WRITE,
} MaxDmaMode;

static volatile MaxDmaMode dma_mode = MAX_DMA_IDLE;
static Max11300 *dma_dev = 0;
static uint16_t *dma_read_values = 0;
static uint8_t dma_word_count = 0;
static Max11300DmaCallback dma_callback = 0;
static void *dma_user = 0;
static uint8_t dma_tx[1U + (MAX11300_PIN_COUNT * 2U)];
static uint8_t dma_rx[1U + (MAX11300_PIN_COUNT * 2U)];

static void finish_dma(bool ok) {
  Max11300DmaCallback callback = dma_callback;
  void *user = dma_user;

  if (dma_dev != 0) {
    max_cs(dma_dev, GPIO_PIN_SET);
  }

  if (ok && dma_mode == MAX_DMA_READ && dma_read_values != 0) {
    for (uint8_t i = 0; i < dma_word_count; i++) {
      uint8_t offset = (uint8_t)(1U + (i * 2U));
      dma_read_values[i] = (uint16_t)(((uint16_t)dma_rx[offset] << 8) | dma_rx[offset + 1U]);
    }
  }

  dma_mode = MAX_DMA_IDLE;
  dma_dev = 0;
  dma_read_values = 0;
  dma_word_count = 0;
  dma_callback = 0;
  dma_user = 0;

  if (callback != 0) {
    callback(ok, user);
  }
}

void Max11300_Init(Max11300 *dev, SPI_HandleTypeDef *spi) {
  dev->spi = spi;
  dev->cs_port = MAX11300_CS_GPIO_Port;
  dev->cs_pin = MAX11300_CS_Pin;
  dev->cnvt_port = MAX11300_CNVT_GPIO_Port;
  dev->cnvt_pin = MAX11300_CNVT_Pin;
  HAL_GPIO_WritePin(dev->cs_port, dev->cs_pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(dev->cnvt_port, dev->cnvt_pin, GPIO_PIN_SET);
}

bool Max11300_Begin(Max11300 *dev) {
  uint16_t id = 0U;
  return Max11300_ReadRegisters(dev, MAX_DEVICE_ID, &id, 1U) &&
         id == MAX_DEVICE_ID_VALUE;
}

bool Max11300_ReadRegisters(Max11300 *dev, uint8_t reg, uint16_t *values, uint8_t count) {
  if (count == 0U) {
    return true;
  }
  if (count > MAX11300_PIN_COUNT) {
    count = MAX11300_PIN_COUNT;
  }
  uint8_t command = (uint8_t)((reg << 1U) | 1U);
  uint8_t rx[MAX11300_PIN_COUNT * 2U];
  max_cs(dev, GPIO_PIN_RESET);
  HAL_StatusTypeDef status = HAL_SPI_Transmit(dev->spi, &command, 1U, 10U);
  if (status == HAL_OK) {
    status = HAL_SPI_Receive(dev->spi, rx, (uint16_t)(count * 2U), 10U);
  }
  max_cs(dev, GPIO_PIN_SET);
  if (status != HAL_OK) {
    return false;
  }
  for (uint8_t i = 0; i < count; i++) {
    values[i] = (uint16_t)(((uint16_t)rx[i * 2U] << 8) | rx[(i * 2U) + 1U]);
  }
  return status == HAL_OK;
}

bool Max11300_WriteRegisters(Max11300 *dev, uint8_t reg, const uint16_t *values, uint8_t count) {
  if (count == 0U) {
    return true;
  }
  uint8_t tx[1U + (MAX11300_PIN_COUNT * 2U)];
  if (count > MAX11300_PIN_COUNT) {
    count = MAX11300_PIN_COUNT;
  }
  tx[0] = (uint8_t)(reg << 1U);
  for (uint8_t i = 0; i < count; i++) {
    tx[1U + (i * 2U)] = (uint8_t)(values[i] >> 8);
    tx[2U + (i * 2U)] = (uint8_t)(values[i] & 0xFFU);
  }
  max_cs(dev, GPIO_PIN_RESET);
  HAL_StatusTypeDef status = HAL_SPI_Transmit(dev->spi, tx, (uint16_t)(1U + (count * 2U)), 20U);
  max_cs(dev, GPIO_PIN_SET);
  return status == HAL_OK;
}

uint16_t Max11300_ReadRegister(Max11300 *dev, uint8_t reg) {
  uint16_t value = 0;
  Max11300_ReadRegisters(dev, reg, &value, 1U);
  return value;
}

bool Max11300_WriteRegister(Max11300 *dev, uint8_t reg, uint16_t value) {
  return Max11300_WriteRegisters(dev, reg, &value, 1U);
}

bool Max11300_ReadModifyWrite(Max11300 *dev, uint8_t reg, uint16_t mask, uint16_t value) {
  uint16_t current = Max11300_ReadRegister(dev, reg);
  current = (uint16_t)((current & ~mask) | value);
  return Max11300_WriteRegister(dev, reg, current);
}

bool Max11300_SetPinMode(Max11300 *dev, uint8_t pin, Max11300PinMode mode, int8_t partner) {
  if (pin >= MAX11300_PIN_COUNT) {
    return false;
  }
  uint16_t config = Max11300_ReadRegister(dev, (uint8_t)(MAX_FUNC_BASE + pin));
  config &= (uint16_t)~MAX_FUNCID_MASK;
  switch (mode) {
    case MAX_PIN_ADC:
      config |= MAX_FUNCID_ADC;
      break;
    case MAX_PIN_DAC:
      config |= MAX_FUNCID_DAC;
      break;
    case MAX_PIN_ADC_DIFF_POS:
      config |= MAX_FUNCID_ADC_DIFF_POS;
      if (partner >= 0 && partner < (int8_t)MAX11300_PIN_COUNT) {
        uint16_t neg = Max11300_ReadRegister(dev, (uint8_t)(MAX_FUNC_BASE + (uint8_t)partner));
        neg = (uint16_t)((neg & ~MAX_FUNCID_MASK) | MAX_FUNCID_ADC_DIFF_NEG);
        if (!Max11300_WriteRegister(dev, (uint8_t)(MAX_FUNC_BASE + (uint8_t)partner), neg)) {
          return false;
        }
      }
      break;
    case MAX_PIN_ADC_DIFF_NEG:
      config |= MAX_FUNCID_ADC_DIFF_NEG;
      break;
    case MAX_PIN_HIGH_Z:
    default:
      config = MAX_FUNCID_HI_Z;
      break;
  }
  return Max11300_WriteRegister(dev, (uint8_t)(MAX_FUNC_BASE + pin), config);
}

bool Max11300_SetPinAdcRange(Max11300 *dev, uint8_t pin, uint16_t range) {
  return Max11300_ReadModifyWrite(dev, (uint8_t)(MAX_FUNC_BASE + pin), MAX_FUNCPRM_RANGE_MASK, range);
}

bool Max11300_SetPinDacRange(Max11300 *dev, uint8_t pin, uint16_t range) {
  return Max11300_ReadModifyWrite(dev, (uint8_t)(MAX_FUNC_BASE + pin), MAX_FUNCPRM_RANGE_MASK, range);
}

bool Max11300_SetPinAveraging(Max11300 *dev, uint8_t pin, uint8_t samples) {
  uint16_t code = 0;
  while (samples > 1U && code < 7U) {
    samples = (uint8_t)(samples >> 1U);
    code++;
  }
  return Max11300_ReadModifyWrite(dev, (uint8_t)(MAX_FUNC_BASE + pin), MAX_FUNCPRM_AVG_MASK, (uint16_t)(code << MAX_FUNCPRM_AVG));
}

bool Max11300_SetDacRef(Max11300 *dev, Max11300DacRef reference) {
  return Max11300_ReadModifyWrite(dev, MAX_DEVCTL, (uint16_t)(1U << MAX_DACREF), reference ? (uint16_t)(1U << MAX_DACREF) : 0U);
}

bool Max11300_SetDacMode(Max11300 *dev, uint16_t mode) {
  return Max11300_ReadModifyWrite(dev, MAX_DEVCTL, MAX_DACCTL_MASK, mode);
}

bool Max11300_SetConversionRate(Max11300 *dev, uint16_t rate) {
  return Max11300_ReadModifyWrite(dev, MAX_DEVCTL, MAX_ADCCONV_MASK, rate);
}

bool Max11300_SetAdcMode(Max11300 *dev, uint16_t mode) {
  return Max11300_ReadModifyWrite(dev, MAX_DEVCTL, MAX_ADCCTL_MASK, mode);
}

uint16_t Max11300_ReadAnalogPin(Max11300 *dev, uint8_t pin) {
  if (pin >= MAX11300_PIN_COUNT) {
    return 2048U;
  }
  return Max11300_ReadRegister(dev, (uint8_t)(MAX_ADCDAT_BASE + pin));
}

bool Max11300_WriteAnalogPin(Max11300 *dev, uint8_t pin, uint16_t value) {
  if (pin >= MAX11300_PIN_COUNT) {
    return false;
  }
  return Max11300_WriteRegister(dev, (uint8_t)(MAX_DACDAT_BASE + pin), value);
}

bool Max11300_BurstAnalogRead(Max11300 *dev, uint8_t start_pin, uint16_t *samples, uint8_t count) {
  if (start_pin >= MAX11300_PIN_COUNT) {
    return false;
  }
  if ((uint16_t)start_pin + count > MAX11300_PIN_COUNT) {
    count = (uint8_t)(MAX11300_PIN_COUNT - start_pin);
  }
  return Max11300_ReadRegisters(dev, (uint8_t)(MAX_ADCDAT_BASE + start_pin), samples, count);
}

bool Max11300_BurstAnalogWrite(Max11300 *dev, uint8_t start_pin, const uint16_t *samples, uint8_t count) {
  if (start_pin >= MAX11300_PIN_COUNT) {
    return false;
  }
  if ((uint16_t)start_pin + count > MAX11300_PIN_COUNT) {
    count = (uint8_t)(MAX11300_PIN_COUNT - start_pin);
  }
  return Max11300_WriteRegisters(dev, (uint8_t)(MAX_DACDAT_BASE + start_pin), samples, count);
}

bool Max11300_IsDmaBusy(void) {
  return dma_mode != MAX_DMA_IDLE;
}

bool Max11300_ReadRegistersDma(Max11300 *dev, uint8_t reg, uint16_t *values, uint8_t count, Max11300DmaCallback callback, void *user) {
  if (count == 0U) {
    if (callback != 0) {
      callback(true, user);
    }
    return true;
  }
  if (count > MAX11300_PIN_COUNT || dma_mode != MAX_DMA_IDLE || dev == 0 || values == 0) {
    return false;
  }

  dma_tx[0] = (uint8_t)((reg << 1U) | 1U);
  for (uint8_t i = 1; i < (uint8_t)(1U + (count * 2U)); i++) {
    dma_tx[i] = 0U;
    dma_rx[i] = 0U;
  }
  dma_rx[0] = 0U;

  dma_mode = MAX_DMA_READ;
  dma_dev = dev;
  dma_read_values = values;
  dma_word_count = count;
  dma_callback = callback;
  dma_user = user;

  max_cs(dev, GPIO_PIN_RESET);
  if (HAL_SPI_TransmitReceive_DMA(dev->spi, dma_tx, dma_rx, (uint16_t)(1U + (count * 2U))) != HAL_OK) {
    finish_dma(false);
    return false;
  }
  return true;
}

bool Max11300_WriteRegistersDma(Max11300 *dev, uint8_t reg, const uint16_t *values, uint8_t count, Max11300DmaCallback callback, void *user) {
  if (count == 0U) {
    if (callback != 0) {
      callback(true, user);
    }
    return true;
  }
  if (count > MAX11300_PIN_COUNT || dma_mode != MAX_DMA_IDLE || dev == 0 || values == 0) {
    return false;
  }

  dma_tx[0] = (uint8_t)(reg << 1U);
  for (uint8_t i = 0; i < count; i++) {
    dma_tx[1U + (i * 2U)] = (uint8_t)(values[i] >> 8);
    dma_tx[2U + (i * 2U)] = (uint8_t)(values[i] & 0xFFU);
  }

  dma_mode = MAX_DMA_WRITE;
  dma_dev = dev;
  dma_read_values = 0;
  dma_word_count = count;
  dma_callback = callback;
  dma_user = user;

  max_cs(dev, GPIO_PIN_RESET);
  if (HAL_SPI_Transmit_DMA(dev->spi, dma_tx, (uint16_t)(1U + (count * 2U))) != HAL_OK) {
    finish_dma(false);
    return false;
  }
  return true;
}

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi) {
  if (dma_dev != 0 && hspi == dma_dev->spi && dma_mode == MAX_DMA_READ) {
    finish_dma(true);
  }
}

void HAL_SPI_TxCpltCallback(SPI_HandleTypeDef *hspi) {
  if (dma_dev != 0 && hspi == dma_dev->spi && dma_mode == MAX_DMA_WRITE) {
    finish_dma(true);
  }
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi) {
  if (dma_dev != 0 && hspi == dma_dev->spi) {
    finish_dma(false);
  }
}
