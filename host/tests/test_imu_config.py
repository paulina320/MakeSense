import unittest

from hardware.imu_config import (
    IMU_ACCEL,
    IMU_BMP,
    IMU_GYRO,
    max_rate_for_fields,
    sensor_mask_for_fields,
)


class ImuConfigTests(unittest.TestCase):
    def test_axes_on_same_chip_use_one_sensor(self):
        fields = ["accel_x", "accel_y", "accel_z"]
        self.assertEqual(sensor_mask_for_fields(fields), IMU_ACCEL)
        self.assertEqual(max_rate_for_fields(fields), 3200)

    def test_rate_reduces_with_selected_sensor_count(self):
        self.assertEqual(
            sensor_mask_for_fields(["accel_x", "gyro_z", "temperature"]),
            IMU_ACCEL | IMU_GYRO | IMU_BMP,
        )
        self.assertEqual(max_rate_for_fields(["accel_x", "gyro_z"]), 1600)
        self.assertEqual(
            max_rate_for_fields(["accel_x", "gyro_z", "mag_x"]), 1000
        )
        self.assertEqual(
            max_rate_for_fields(["accel_x", "gyro_z", "mag_x", "pressure"]),
            800,
        )


if __name__ == "__main__":
    unittest.main()
