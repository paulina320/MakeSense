import argparse

from scripts.imu_flatline_sweep import (
    longest_repeated_run,
    parse_fields,
    sensor_tuple,
    timestamp_deltas_us,
)


def sample(timestamp_us: int, accel_x: int) -> dict:
    return {
        "timestamp_us": timestamp_us,
        "accel_raw": [accel_x, 0, 256],
        "gyro": [0, 0, 0],
        "mag": [10, 20, 30],
    }


def test_detects_repeated_sensor_run():
    samples = [
        sample(0, 1),
        sample(10_000, 2),
        sample(20_000, 2),
        sample(30_000, 2),
        sample(40_000, 3),
    ]
    deltas = timestamp_deltas_us(samples)

    repeated, longest_count, longest_duration_us = longest_repeated_run(samples, deltas)

    assert repeated == 2
    assert longest_count == 3
    assert longest_duration_us == 20_000


def test_timestamp_delta_handles_uint32_wrap():
    samples = [sample(0xFFFFFF00, 1), sample(0x00000100, 2)]
    assert timestamp_deltas_us(samples) == [512]


def test_field_parser_declares_required_accelerometer_inputs():
    assert parse_fields("accel_x, accel_y,accel_z") == [
        "accel_x",
        "accel_y",
        "accel_z",
    ]


def test_field_parser_rejects_unknown_input():
    try:
        parse_fields("accel_x,not_a_sensor")
    except argparse.ArgumentTypeError:
        return
    raise AssertionError("unknown IMU field was accepted")


def test_sensor_tuple_uses_only_requested_inputs():
    value = sample(100, 42)
    value["bmp_pressure_raw"] = 1234
    assert sensor_tuple(value, ["accel_x", "pressure"]) == (42, 1234)
