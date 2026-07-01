"""
Exercise the firmware DAC_TEST command around the 2.5 V unipolar DAC bias.

Example:
    python host/scripts/dac_output_test.py --port COM10 --pin 1
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface


TEST_MILLIVOLTS = (2200, 2500, 2800)
BIAS_MILLIVOLTS = 2500


def set_test_voltage(
    device: HapticDeviceInterface,
    pin: int,
    millivolts: int,
) -> None:
    reply = device.send_command("DAC_TEST", pin, millivolts)
    if not reply.startswith("OK DAC_TEST"):
        raise RuntimeError(reply)
    print(
        f"Pin {pin}: {millivolts:+d} mV at DAC "
        f"({millivolts - BIAS_MILLIVOLTS:+d} mV relative to 2.5 V bias, "
        f"approximately {(millivolts - BIAS_MILLIVOLTS) * 10 / 1000:+.1f} V AC after 20 dB gain)"
    )
    print(f"  Firmware: {reply}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step a MAX11300 output through safe fixed test voltages."
    )
    parser.add_argument("--port", required=True, help="Serial port, for example COM10")
    parser.add_argument("--pin", type=int, default=1, help="Pixi output pin (default: 1)")
    parser.add_argument(
        "--hold",
        type=float,
        default=3.0,
        help="Seconds to hold each voltage (default: 3)",
    )
    parser.add_argument("--baudrate", type=int, default=115200)
    args = parser.parse_args()

    if not 0 <= args.pin < 20:
        parser.error("--pin must be between 0 and 19")
    if not 0.0 <= args.hold <= 30.0:
        parser.error("--hold must be between 0 and 30 seconds")

    device = HapticDeviceInterface(port=args.port, baudrate=args.baudrate)
    if not device.connect():
        details = "; ".join(device.recent_errors())
        raise SystemExit(f"Failed to connect to {args.port}: {details}")

    try:
        print(
            f"Testing Pixi pin {args.pin}; measure the DAC pin relative to analog ground. "
            "Expected values are absolute DAC voltages in the 0 V to 10 V range."
        )
        for millivolts in TEST_MILLIVOLTS:
            set_test_voltage(device, args.pin, millivolts)
            time.sleep(args.hold)
    except KeyboardInterrupt:
        print("\nTest interrupted.")
    finally:
        try:
            set_test_voltage(device, args.pin, BIAS_MILLIVOLTS)
            print("Output returned to 2500 mV bias.")
        except Exception as exc:
            print(f"WARNING: could not return output to 2500 mV bias: {exc}", file=sys.stderr)
        device.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
