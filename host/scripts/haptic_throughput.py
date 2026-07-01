"""
Run serial throughput checks against the haptic firmware.

Examples:
    python scripts/haptic_throughput.py --port COM6 --mode loopback
    python scripts/haptic_throughput.py --port COM6 --mode rx
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface
from hardware.serial_protocol import MessageType, pack_i16_samples


def run_loopback(device: HapticDeviceInterface, duration: float, frame_samples: int) -> None:
    payload = pack_i16_samples(np.linspace(-1.0, 1.0, frame_samples, dtype=np.float32))
    while device.read_loopback_frame(timeout=0.01):
        pass
    deadline = time.monotonic() + duration
    frames_tx = 0
    frames_rx = 0
    timeouts = 0
    bytes_sent = 0
    while time.monotonic() < deadline:
        device._write_frame(MessageType.LOOPBACK, payload)
        frames_tx += 1
        bytes_sent += len(payload)
        echo = device.read_loopback_frame(timeout=1.0)
        if echo and echo.payload == payload:
            frames_rx += 1
        else:
            timeouts += 1
    elapsed = duration
    print(f"loopback tx: {bytes_sent / elapsed:.0f} bytes/s, {frames_tx / elapsed:.0f} frames/s")
    print(f"loopback rx: {frames_rx / elapsed:.0f} frames/s, timeouts: {timeouts}")


def run_rx(device: HapticDeviceInterface, duration: float, sample_rate: int) -> None:
    device.configure_channels([0], sample_rate)
    device.start_acquisition()
    deadline = time.monotonic() + duration
    samples = 0
    frames = 0
    while time.monotonic() < deadline:
        chunk = device.read_data(512)
        if len(chunk):
            samples += len(chunk)
            frames += 1
    device.stop_acquisition()
    print(f"rx: {samples / duration:.0f} samples/s, {frames / duration:.0f} frames/s")


def run_duplex(device: HapticDeviceInterface, duration: float, frame_samples: int, sample_rate: int) -> None:
    device.configure_channel(0, role="input", stream_enabled=True)
    device.configure_channel(1, role="output")
    device.configure_channels([0], sample_rate)
    device.start_acquisition()
    device.start_rendering()
    payload = np.sin(np.linspace(0, 2 * np.pi, frame_samples, dtype=np.float32))
    deadline = time.monotonic() + duration
    tx_samples = 0
    rx_samples = 0
    chunks_per_read = max(1, 128 // max(1, frame_samples))
    while time.monotonic() < deadline:
        for _ in range(chunks_per_read):
            device.write_render_buffer(payload)
            tx_samples += len(payload)
        chunk = device.read_data(128)
        rx_samples += len(chunk)
    device.stop_rendering()
    device.stop_acquisition()
    print(f"duplex tx: {tx_samples / duration:.0f} samples/s")
    print(f"duplex rx: {rx_samples / duration:.0f} samples/s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baudrate", type=int, default=921600)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--frame-samples", type=int, default=128)
    parser.add_argument("--sample-rate", type=int, default=1000)
    parser.add_argument("--mode", choices=["loopback", "rx", "duplex"], default="loopback")
    args = parser.parse_args()

    device = HapticDeviceInterface(port=args.port, baudrate=args.baudrate)
    if not device.connect():
        raise SystemExit(f"failed to connect to {args.port}")

    try:
        start = time.monotonic()
        if args.mode == "loopback":
            run_loopback(device, args.duration, args.frame_samples)
        elif args.mode == "rx":
            run_rx(device, args.duration, args.sample_rate)
        else:
            run_duplex(device, args.duration, args.frame_samples, args.sample_rate)
        status = device.get_status()
        elapsed = time.monotonic() - start
        print(f"elapsed: {elapsed:.2f}s")
        print(f"crc failures: {status.rx_crc_failures}")
        print(f"dropped frames: {status.dropped_frames}")
        print(f"underruns: {status.underruns}")
    finally:
        device.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
