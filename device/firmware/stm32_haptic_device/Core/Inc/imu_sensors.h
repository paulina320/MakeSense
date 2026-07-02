#ifndef IMU_SENSORS_H
#define IMU_SENSORS_H

#include "main.h"
#include <stdbool.h>
#include <stdint.h>

typedef struct {
  bool accel_ok;
  bool gyro_ok;
  bool mag_ok;
  bool bmp_ok;
  uint8_t bmp_addr;
} ImuStatus;

typedef struct {
  ImuStatus status;
  int16_t accel[3];
  int16_t gyro[3];
  int16_t mag[3];
  int32_t bmp_pressure_raw;
  int32_t bmp_temperature_raw;
} ImuSample;

#define IMU_SELECT_ACCEL 0x01U
#define IMU_SELECT_GYRO  0x02U
#define IMU_SELECT_MAG   0x04U
#define IMU_SELECT_BMP   0x08U
#define IMU_SELECT_ALL   0x0FU

void Imu_Init(void);
ImuStatus Imu_GetStatus(void);
bool Imu_SetAccelRate(uint32_t rate_hz);
bool Imu_Read(ImuSample *sample);
bool Imu_ReadSelected(ImuSample *sample, uint8_t sensor_mask);

#endif
