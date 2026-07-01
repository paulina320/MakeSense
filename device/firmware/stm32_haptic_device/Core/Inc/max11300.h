#ifndef MAX11300_H
#define MAX11300_H

#include "stm32f4xx_hal.h"
#include <stdbool.h>
#include <stdint.h>

#define MAX11300_PIN_COUNT 20U

#define MAX_DEVICE_ID 0x00U
#define MAX_DEVICE_ID_VALUE 0x0424U
#define MAX_DEVCTL 0x10U
#define MAX_FUNC_BASE 0x20U
#define MAX_ADCDAT_BASE 0x40U
#define MAX_DACDAT_BASE 0x60U

#define MAX_FUNCID_MASK 0xF000U
#define MAX_FUNCID_HI_Z 0x0000U
#define MAX_FUNCID_GPI 0x1000U
#define MAX_FUNCID_GPO 0x3000U
#define MAX_FUNCID_DAC 0x5000U
#define MAX_FUNCID_ADC 0x7000U
#define MAX_FUNCID_ADC_DIFF_POS 0x8000U
#define MAX_FUNCID_ADC_DIFF_NEG 0x9000U

#define MAX_FUNCPRM_ASSOC_MASK 0x001FU
#define MAX_FUNCPRM_AVG 5U
#define MAX_FUNCPRM_AVG_MASK 0x00E0U
#define MAX_FUNCPRM_RANGE_MASK 0x0700U
#define MAX_FUNCPRM_AVR_MASK 0x0800U

#define MAX_ADC_RANGE_0_10 0x0100U
#define MAX_ADC_RANGE_5_5 0x0200U
#define MAX_ADC_RANGE_10_0 0x0300U
#define MAX_ADC_RANGE_0_2_5 0x0400U

#define MAX_DAC_RANGE_0_10 0x0100U
#define MAX_DAC_RANGE_5_5 0x0200U
#define MAX_DAC_RANGE_10_0 0x0300U

#define MAX_DACREF 6U
#define MAX_ADCCONV_MASK 0x0030U
#define MAX_DACCTL_MASK 0x000CU
#define MAX_DAC_SEQUENTIAL 0x0000U
#define MAX_DAC_IMMEDIATE 0x0004U
#define MAX_ADCCTL_MASK 0x0003U

#define MAX_RATE_200 0x0000U
#define MAX_RATE_250 0x0010U
#define MAX_RATE_333 0x0020U
#define MAX_RATE_400 0x0030U

#define MAX_ADC_IDLE 0x0000U
#define MAX_ADC_SINGLE_SWEEP 0x0001U
#define MAX_ADC_SINGLE_CONVERSION 0x0002U
#define MAX_ADC_CONTINUOUS 0x0003U

typedef enum {
  MAX_PIN_HIGH_Z = 0,
  MAX_PIN_ADC,
  MAX_PIN_DAC,
  MAX_PIN_ADC_DIFF_POS,
  MAX_PIN_ADC_DIFF_NEG,
} Max11300PinMode;

typedef enum {
  MAX_DAC_REF_EXTERNAL = 0,
  MAX_DAC_REF_INTERNAL = 1,
} Max11300DacRef;

typedef struct {
  SPI_HandleTypeDef *spi;
  GPIO_TypeDef *cs_port;
  uint16_t cs_pin;
  GPIO_TypeDef *cnvt_port;
  uint16_t cnvt_pin;
} Max11300;

typedef void (*Max11300DmaCallback)(bool ok, void *user);

void Max11300_Init(Max11300 *dev, SPI_HandleTypeDef *spi);
bool Max11300_Begin(Max11300 *dev);
bool Max11300_ReadRegisters(Max11300 *dev, uint8_t reg, uint16_t *values, uint8_t count);
bool Max11300_WriteRegisters(Max11300 *dev, uint8_t reg, const uint16_t *values, uint8_t count);
uint16_t Max11300_ReadRegister(Max11300 *dev, uint8_t reg);
bool Max11300_WriteRegister(Max11300 *dev, uint8_t reg, uint16_t value);
bool Max11300_ReadModifyWrite(Max11300 *dev, uint8_t reg, uint16_t mask, uint16_t value);
bool Max11300_SetPinMode(Max11300 *dev, uint8_t pin, Max11300PinMode mode, int8_t partner);
bool Max11300_SetPinAdcRange(Max11300 *dev, uint8_t pin, uint16_t range);
bool Max11300_SetPinDacRange(Max11300 *dev, uint8_t pin, uint16_t range);
bool Max11300_SetPinAveraging(Max11300 *dev, uint8_t pin, uint8_t samples);
bool Max11300_SetDacRef(Max11300 *dev, Max11300DacRef reference);
bool Max11300_SetDacMode(Max11300 *dev, uint16_t mode);
bool Max11300_SetConversionRate(Max11300 *dev, uint16_t rate);
bool Max11300_SetAdcMode(Max11300 *dev, uint16_t mode);
uint16_t Max11300_ReadAnalogPin(Max11300 *dev, uint8_t pin);
bool Max11300_WriteAnalogPin(Max11300 *dev, uint8_t pin, uint16_t value);
bool Max11300_BurstAnalogRead(Max11300 *dev, uint8_t start_pin, uint16_t *samples, uint8_t count);
bool Max11300_BurstAnalogWrite(Max11300 *dev, uint8_t start_pin, const uint16_t *samples, uint8_t count);
bool Max11300_IsDmaBusy(void);
bool Max11300_ReadRegistersDma(Max11300 *dev, uint8_t reg, uint16_t *values, uint8_t count, Max11300DmaCallback callback, void *user);
bool Max11300_WriteRegistersDma(Max11300 *dev, uint8_t reg, const uint16_t *values, uint8_t count, Max11300DmaCallback callback, void *user);

#endif
