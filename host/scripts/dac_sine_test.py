"""
Run the firmware-local DAC_SINE_TEST command.

Example:
    python host/scripts/dac_sine_test.py --port COM10 --pin 0 --freq 200 --duration 2000
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a firmware-local sine on one MAX11300 DAC pin."
    )
    parser.add_argument("--port", required=True, help="Serial port, for example COM10")
    parser.add_argument("--pin", type=int, default=0, help="Pixi output pin (default: 0)")
    parser.add_argument("--freq", type=int, default=200, help="Sine frequency in Hz (default: 200)")
    parser.add_argument(
        "--duration",
        type=int,
        default=2000,
        help="Duration in milliseconds (default: 2000)",
    )
    parser.add_argument("--baudrate", type=int, default=921600)
    args = parser.parse_args()

    if not 0 <= args.pin < 20:
        parser.error("--pin must be between 0 and 19")
    if not 1 <= args.freq <= 1000:
        parser.error("--freq must be between 1 and 1000 Hz")
    if not 1 <= args.duration <= 30000:
        parser.error("--duration must be between 1 and 30000 ms")

    device = HapticDeviceInterface(
        port=args.port,
        baudrate=args.baudrate,
        command_timeout=max(1.0, args.duration / 1000.0 + 2.0),
    )
    if not device.connect():
        details = "; ".join(device.recent_errors())
        raise SystemExit(f"Failed to connect to {args.port}: {details}")

    try:
        print(
            f"Running firmware-local DAC sine test on Pixi pin {args.pin}: "
            f"{args.freq} Hz for {args.duration} ms."
        )
        print("Measure the DAC pin directly relative to analog ground, scope DC-coupled.")
        reply = device.send_command("DAC_SINE_TEST", args.pin, args.freq, args.duration)
        if not reply.startswith("OK DAC_SINE_TEST"):
            raise RuntimeError(reply)
        print(f"Firmware: {reply}")
    finally:
        device.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
