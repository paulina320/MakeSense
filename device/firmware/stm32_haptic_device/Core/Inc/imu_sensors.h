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

void Imu_Init(void);
ImuStatus Imu_GetStatus(void);
bool Imu_SetAccelRate(uint32_t rate_hz);
bool Imu_Read(ImuSample *sample);

#endif
