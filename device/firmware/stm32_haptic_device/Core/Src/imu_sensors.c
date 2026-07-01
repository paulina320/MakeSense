#include "imu_sensors.h"

#include <string.h>

#define IMU_TIMEOUT_MS 20U

#define ADXL345_ADDR 0x53U
#define ADXL345_REG_DEVID 0x00U
#define ADXL345_REG_BW_RATE 0x2CU
#define ADXL345_REG_POWER_CTL 0x2DU
#define ADXL345_REG_DATA_FORMAT 0x31U
#define ADXL345_REG_DATAX0 0x32U

#define ITG3200_ADDR 0x68U
#define ITG3200_REG_SMPLRT_DIV 0x15U
#define ITG3200_REG_DLPF_FS 0x16U
#define ITG3200_REG_GYRO_XOUT 0x1DU
#define ITG3200_REG_PWR_MGM 0x3EU

#define QMC5883_ADDR 0x0DU
#define QMC5883_REG_DATA 0x00U
#define QMC5883_REG_CONTROL 0x09U
#define QMC5883_REG_SET_RESET 0x0BU

#define BMP280_ADDR_LOW 0x76U
#define BMP280_ADDR_HIGH 0x77U
#define BMP280_REG_ID 0xD0U
#define BMP280_REG_RESET 0xE0U
#define BMP280_REG_CTRL_MEAS 0xF4U
#define BMP280_REG_CONFIG 0xF5U
#define BMP280_REG_PRESS_MSB 0xF7U

extern I2C_HandleTypeDef hi2c1;

static ImuStatus imu_status;

typedef struct {
  uint32_t milli_hz;
  uint8_t register_value;
} Adxl345Rate;

/* ADXL345 Table 7 output data rates, ordered from slowest to fastest. */
static const Adxl345Rate adxl345_rates[] = {
  {100U, 0x00U}, {200U, 0x01U}, {390U, 0x02U}, {780U, 0x03U},
  {1560U, 0x04U}, {3130U, 0x05U}, {6250U, 0x06U}, {12500U, 0x07U},
  {25000U, 0x08U}, {50000U, 0x09U}, {100000U, 0x0AU},
  {200000U, 0x0BU}, {400000U, 0x0CU}, {800000U, 0x0DU},
  {1600000U, 0x0EU}, {3200000U, 0x0FU}
};

static uint16_t dev_addr(uint8_t address) {
  return (uint16_t)(address << 1);
}

static bool i2c_write_reg(uint8_t address, uint8_t reg, uint8_t value) {
  return HAL_I2C_Mem_Write(
    &hi2c1,
    dev_addr(address),
    reg,
    I2C_MEMADD_SIZE_8BIT,
    &value,
    1U,
    IMU_TIMEOUT_MS
  ) == HAL_OK;
}

static bool i2c_read_reg(uint8_t address, uint8_t reg, uint8_t *buffer, uint16_t length) {
  if (buffer == NULL || length == 0U) {
    return false;
  }
  return HAL_I2C_Mem_Read(
    &hi2c1,
    dev_addr(address),
    reg,
    I2C_MEMADD_SIZE_8BIT,
    buffer,
    length,
    IMU_TIMEOUT_MS
  ) == HAL_OK;
}

static int16_t le_i16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

static int16_t be_i16(uint8_t hi, uint8_t lo) {
  return (int16_t)(((uint16_t)hi << 8) | lo);
}

static bool init_accel(void) {
  uint8_t id = 0;
  if (!i2c_read_reg(ADXL345_ADDR, ADXL345_REG_DEVID, &id, 1U) || id != 0xE5U) {
    return false;
  }
  return i2c_write_reg(ADXL345_ADDR, ADXL345_REG_BW_RATE, 0x0AU) &&
         i2c_write_reg(ADXL345_ADDR, ADXL345_REG_DATA_FORMAT, 0x0BU) &&
         i2c_write_reg(ADXL345_ADDR, ADXL345_REG_POWER_CTL, 0x08U);
}

static bool init_gyro(void) {
  return i2c_write_reg(ITG3200_ADDR, ITG3200_REG_PWR_MGM, 0x00U) &&
         i2c_write_reg(ITG3200_ADDR, ITG3200_REG_SMPLRT_DIV, 0x07U) &&
         i2c_write_reg(ITG3200_ADDR, ITG3200_REG_DLPF_FS, 0x1BU);
}

static bool init_mag(void) {
  return i2c_write_reg(QMC5883_ADDR, QMC5883_REG_SET_RESET, 0x01U) &&
         i2c_write_reg(QMC5883_ADDR, QMC5883_REG_CONTROL, 0x1DU);
}

static bool init_bmp_addr(uint8_t address) {
  uint8_t id = 0;
  if (!i2c_read_reg(address, BMP280_REG_ID, &id, 1U) || id != 0x58U) {
    return false;
  }
  (void)i2c_write_reg(address, BMP280_REG_RESET, 0xB6U);
  HAL_Delay(2U);
  return i2c_write_reg(address, BMP280_REG_CONFIG, 0xA0U) &&
         i2c_write_reg(address, BMP280_REG_CTRL_MEAS, 0x27U);
}

void Imu_Init(void) {
  memset(&imu_status, 0, sizeof(imu_status));

  if (HAL_I2C_GetState(&hi2c1) == HAL_I2C_STATE_RESET) {
    return;
  }

  imu_status.accel_ok = init_accel();
  imu_status.gyro_ok = init_gyro();
  imu_status.mag_ok = init_mag();
  if (init_bmp_addr(BMP280_ADDR_LOW)) {
    imu_status.bmp_ok = true;
    imu_status.bmp_addr = BMP280_ADDR_LOW;
  } else if (init_bmp_addr(BMP280_ADDR_HIGH)) {
    imu_status.bmp_ok = true;
    imu_status.bmp_addr = BMP280_ADDR_HIGH;
  }
}

ImuStatus Imu_GetStatus(void) {
  return imu_status;
}

bool Imu_SetAccelRate(uint32_t rate_hz) {
  if (!imu_status.accel_ok) {
    return false;
  }

  uint32_t requested_milli_hz = rate_hz * 1000U;
  uint8_t register_value = adxl345_rates[
    (sizeof(adxl345_rates) / sizeof(adxl345_rates[0])) - 1U
  ].register_value;

  for (uint32_t i = 0U; i < (sizeof(adxl345_rates) / sizeof(adxl345_rates[0])); i++) {
    if (requested_milli_hz <= adxl345_rates[i].milli_hz) {
      register_value = adxl345_rates[i].register_value;
      break;
    }
  }

  return i2c_write_reg(ADXL345_ADDR, ADXL345_REG_BW_RATE, register_value);
}

bool Imu_Read(ImuSample *sample) {
  if (sample == NULL) {
    return false;
  }
  memset(sample, 0, sizeof(*sample));
  sample->status = imu_status;
  bool any_ok = false;

  uint8_t raw[8];
  if (imu_status.accel_ok && i2c_read_reg(ADXL345_ADDR, ADXL345_REG_DATAX0, raw, 6U)) {
    sample->accel[0] = le_i16(raw[0], raw[1]);
    sample->accel[1] = le_i16(raw[2], raw[3]);
    sample->accel[2] = le_i16(raw[4], raw[5]);
    any_ok = true;
  } else {
    sample->status.accel_ok = false;
  }

  if (imu_status.gyro_ok && i2c_read_reg(ITG3200_ADDR, ITG3200_REG_GYRO_XOUT, raw, 6U)) {
    sample->gyro[0] = be_i16(raw[0], raw[1]);
    sample->gyro[1] = be_i16(raw[2], raw[3]);
    sample->gyro[2] = be_i16(raw[4], raw[5]);
    any_ok = true;
  } else {
    sample->status.gyro_ok = false;
  }

  if (imu_status.mag_ok && i2c_read_reg(QMC5883_ADDR, QMC5883_REG_DATA, raw, 6U)) {
    sample->mag[0] = le_i16(raw[0], raw[1]);
    sample->mag[1] = le_i16(raw[2], raw[3]);
    sample->mag[2] = le_i16(raw[4], raw[5]);
    any_ok = true;
  } else {
    sample->status.mag_ok = false;
  }

  if (imu_status.bmp_ok && i2c_read_reg(imu_status.bmp_addr, BMP280_REG_PRESS_MSB, raw, 6U)) {
    sample->bmp_pressure_raw = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) | ((int32_t)raw[2] >> 4);
    sample->bmp_temperature_raw = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | ((int32_t)raw[5] >> 4);
    any_ok = true;
  } else {
    sample->status.bmp_ok = false;
  }

  return any_ok;
}
