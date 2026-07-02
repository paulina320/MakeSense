"""
Sweep IMU stream rates and detect delivery stalls or repeated sensor values.

Move or gently shake the device during the test. A motionless accelerometer can
legitimately repeat the same integer counts, so packet timing is reported
separately from value flatlining.

Example:
    python host/scripts/imu_flatline_sweep.py --port COM10
    python host/scripts/imu_flatline_sweep.py --port COM10 --rates 50,100,200,400,800,1000,1600,3200 --duration 15
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface
from hardware.imu_config import FIELD_SENSOR_MASK


@dataclass
class RateResult:
    requested_hz: int
    reported_hz: int
    samples: int
    effective_hz: float
    median_interval_ms: float
    maximum_interval_ms: float
    tail_silence_ms: float
    repeated_samples: int
    longest_repeat_run: int
    longest_repeat_ms: float
    crc_failures: int
    parser_resyncs: int
    rx_thread_alive: bool
    delivery_ok: bool
    stream_stalled: bool
    flatline: bool


def sensor_tuple(sample: dict, imu_fields: list[str] | None = None) -> tuple[int, ...]:
    """Return raw integer sensor fields so conversion rounding is irrelevant."""
    if imu_fields:
        field_values = {
            "accel_x": sample.get("accel_raw", sample.get("accel", [0, 0, 0]))[0],
            "accel_y": sample.get("accel_raw", sample.get("accel", [0, 0, 0]))[1],
            "accel_z": sample.get("accel_raw", sample.get("accel", [0, 0, 0]))[2],
            "gyro_x": sample.get("gyro", [0, 0, 0])[0],
            "gyro_y": sample.get("gyro", [0, 0, 0])[1],
            "gyro_z": sample.get("gyro", [0, 0, 0])[2],
            "mag_x": sample.get("mag", [0, 0, 0])[0],
            "mag_y": sample.get("mag", [0, 0, 0])[1],
            "mag_z": sample.get("mag", [0, 0, 0])[2],
            "pressure": sample.get("bmp_pressure_raw", 0),
            "temperature": sample.get("bmp_temperature_raw", 0),
        }
        return tuple(int(field_values[field]) for field in imu_fields)

    values = []
    values.extend(sample.get("accel_raw", sample.get("accel", [0, 0, 0])))
    values.extend(sample.get("gyro", [0, 0, 0]))
    values.extend(sample.get("mag", [0, 0, 0]))
    return tuple(int(value) for value in values)


def timestamp_deltas_us(samples: list[dict]) -> list[int]:
    """Calculate wrap-safe deltas for the firmware's uint32 microsecond clock."""
    return [
        (int(current.get("timestamp_us", 0)) - int(previous.get("timestamp_us", 0))) & 0xFFFFFFFF
        for previous, current in zip(samples, samples[1:])
    ]


def longest_repeated_run(
    samples: list[dict],
    deltas_us: list[int],
    imu_fields: list[str] | None = None,
) -> tuple[int, int, int]:
    if not samples:
        return 0, 0, 0

    longest_count = 1
    longest_duration_us = 0
    current_count = 1
    current_duration_us = 0
    repeated_samples = 0
    previous = sensor_tuple(samples[0], imu_fields)

    for index, sample in enumerate(samples[1:]):
        current = sensor_tuple(sample, imu_fields)
        if current == previous:
            repeated_samples += 1
            current_count += 1
            current_duration_us += deltas_us[index]
            if current_count > longest_count:
                longest_count = current_count
                longest_duration_us = current_duration_us
        else:
            current_count = 1
            current_duration_us = 0
        previous = current

    return repeated_samples, longest_count, longest_duration_us


def run_rate(
    device: HapticDeviceInterface,
    rate_hz: int,
    duration_s: float,
    flatline_s: float,
    minimum_delivery_ratio: float,
    imu_fields: list[str],
) -> RateResult:
    while device.read_available_imu(512):
        pass

    device.configure_imu_stream(rate_hz, True, imu_fields)
    reported_hz = int(asdict(device.get_status()).get("imu_rate", rate_hz))
    crc_failures_before = device._parser.crc_failures
    resyncs_before = device._parser.resync_count
    device.start_acquisition()
    samples = []
    last_arrival = time.monotonic()
    started = last_arrival
    deadline = started + duration_s
    capture_finished = started

    try:
        while time.monotonic() < deadline:
            chunk = device.read_available_imu(512)
            if chunk:
                samples.extend(chunk)
                last_arrival = time.monotonic()
            else:
                time.sleep(0.002)
    finally:
        # Capture timing must stop before the synchronous teardown commands;
        # otherwise command-response latency looks like an IMU delivery stall.
        capture_finished = time.monotonic()
        device.stop_acquisition()
        device.configure_imu_stream(rate_hz, False, imu_fields)

    deltas_us = timestamp_deltas_us(samples)
    valid_deltas = [delta for delta in deltas_us if 0 < delta < 10_000_000]
    effective_hz = len(samples) / max(capture_finished - started, 1e-9)
    repeated, longest_run, longest_repeat_us = longest_repeated_run(
        samples, deltas_us, imu_fields
    )
    delivery_ok = effective_hz >= reported_hz * minimum_delivery_ratio
    tail_silence_ms = (capture_finished - last_arrival) * 1000.0
    stream_stalled = tail_silence_ms >= flatline_s * 1000.0
    flatline = longest_repeat_us >= flatline_s * 1_000_000

    return RateResult(
        requested_hz=rate_hz,
        reported_hz=reported_hz,
        samples=len(samples),
        effective_hz=effective_hz,
        median_interval_ms=statistics.median(valid_deltas) / 1000.0 if valid_deltas else 0.0,
        maximum_interval_ms=max(valid_deltas) / 1000.0 if valid_deltas else 0.0,
        tail_silence_ms=tail_silence_ms,
        repeated_samples=repeated,
        longest_repeat_run=longest_run,
        longest_repeat_ms=longest_repeat_us / 1000.0,
        crc_failures=device._parser.crc_failures - crc_failures_before,
        parser_resyncs=device._parser.resync_count - resyncs_before,
        rx_thread_alive=bool(device._rx_thread and device._rx_thread.is_alive()),
        delivery_ok=delivery_ok,
        stream_stalled=stream_stalled,
        flatline=flatline,
    )


def format_result(result: RateResult) -> str:
    state = []
    if not result.delivery_ok:
        state.append("LOW DELIVERY")
    if result.stream_stalled:
        state.append("STREAM STALL")
    if result.flatline:
        state.append("FLATLINE")
    label = ", ".join(state) if state else "OK"
    return (
        f"{result.requested_hz:4d}->{result.reported_hz:4d} Hz | "
        f"{result.effective_hz:7.1f} samples/s | "
        f"median/max gap {result.median_interval_ms:7.2f}/{result.maximum_interval_ms:7.2f} ms | "
        f"repeat {result.longest_repeat_run:5d} samples ({result.longest_repeat_ms:7.1f} ms) | "
        f"tail {result.tail_silence_ms:6.1f} ms | "
        f"CRC/resync {result.crc_failures}/{result.parser_resyncs} | "
        f"RX {'up' if result.rx_thread_alive else 'DOWN'} | {label}"
    )


def print_result(result: RateResult) -> None:
    print(format_result(result))


def parse_rates(value: str) -> list[int]:
    rates = sorted({int(rate.strip()) for rate in value.split(",") if rate.strip()})
    if not rates or any(rate <= 0 for rate in rates):
        raise argparse.ArgumentTypeError("rates must be positive comma-separated integers")
    return rates


def parse_fields(value: str) -> list[str]:
    fields = [field.strip().lower() for field in value.split(",") if field.strip()]
    unknown = sorted(set(fields) - set(FIELD_SENSOR_MASK))
    if not fields or unknown:
        detail = f": {', '.join(unknown)}" if unknown else ""
        raise argparse.ArgumentTypeError(f"unknown or empty IMU fields{detail}")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, for example COM10")
    parser.add_argument("--baudrate", type=int, default=921600)
    parser.add_argument("--rates", type=parse_rates, default=parse_rates("25,50,100,200,400,800,1000,1600,3200"))
    parser.add_argument("--duration", type=float, default=10.0, help="Seconds tested at each rate")
    parser.add_argument(
        "--fields",
        type=parse_fields,
        default=parse_fields("accel_x,accel_y,accel_z"),
        help="Comma-separated fields to read (default: all accelerometer axes)",
    )
    parser.add_argument(
        "--flatline-seconds",
        type=float,
        default=0.5,
        help="Unchanged raw sensor duration considered a flatline",
    )
    parser.add_argument(
        "--minimum-delivery-ratio",
        type=float,
        default=0.8,
        help="Minimum received/requested sample-rate ratio",
    )
    parser.add_argument("--csv", type=Path, help="Optional output CSV path")
    args = parser.parse_args()

    if args.duration <= 0 or args.flatline_seconds <= 0:
        parser.error("duration and flatline-seconds must be positive")

    device = HapticDeviceInterface(
        port=args.port,
        baudrate=args.baudrate,
        timeout=0.1,
        command_timeout=2.0,
        frame_queue_size=4096,
    )
    if not device.connect():
        raise SystemExit(f"failed to connect to {args.port}")

    results = []
    try:
        print(f"Testing fields: {', '.join(args.fields)}")
        print("Keep the IMU moving throughout the sweep.\n")
        for rate in args.rates:
            result = run_rate(
                device,
                rate,
                args.duration,
                args.flatline_seconds,
                args.minimum_delivery_ratio,
                args.fields,
            )
            results.append(result)
            print_result(result)
            time.sleep(0.25)
    finally:
        if device.is_running():
            device.stop_acquisition()
        device.disconnect()

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=RateResult.__dataclass_fields__.keys())
            writer.writeheader()
            writer.writerows(asdict(result) for result in results)
        print(f"\nWrote {args.csv}")

    first_failure = next(
        (
            result
            for result in results
            if result.flatline or result.stream_stalled or not result.delivery_ok
        ),
        None,
    )
    if first_failure:
        print(f"\nFirst problematic requested rate: {first_failure.requested_hz} Hz")
        return 1

    print("\nNo flatline or delivery-rate failure detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
