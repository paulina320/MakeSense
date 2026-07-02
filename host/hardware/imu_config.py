"""Shared IMU field selection and stream-rate limits."""

IMU_ACCEL = 0x01
IMU_GYRO = 0x02
IMU_MAG = 0x04
IMU_BMP = 0x08
IMU_ALL = IMU_ACCEL | IMU_GYRO | IMU_MAG | IMU_BMP

FIELD_SENSOR_MASK = {
    "accel_x": IMU_ACCEL, "accel_y": IMU_ACCEL, "accel_z": IMU_ACCEL,
    "gyro_x": IMU_GYRO, "gyro_y": IMU_GYRO, "gyro_z": IMU_GYRO,
    "mag_x": IMU_MAG, "mag_y": IMU_MAG, "mag_z": IMU_MAG,
    "pressure": IMU_BMP, "temperature": IMU_BMP,
}

# Conservative limits for the measured 400 kHz shared I2C bus.
MAX_RATE_BY_SENSOR_COUNT = {0: 3200, 1: 3200, 2: 1600, 3: 1000, 4: 800}


def sensor_mask_for_fields(fields) -> int:
    mask = 0
    for field in fields or []:
        mask |= FIELD_SENSOR_MASK.get(field, 0)
    return mask


def max_rate_for_fields(fields) -> int:
    return MAX_RATE_BY_SENSOR_COUNT[sensor_mask_for_fields(fields).bit_count()]
