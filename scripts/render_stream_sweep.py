"""
Sweep host-streamed DAC rendering with a generated sine.

This test exercises the normal host -> OUTPUT_BUFFER -> firmware render path,
not the firmware-local DAC_SINE_TEST path.

Example:
    python host/scripts/render_stream_sweep.py --port COM10 --pin 0
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import math
from pathlib import Path
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface


REFILL_INTERVAL_S = 0.003
SPIN_WAIT_S = 0.0005
PREFILL_SAMPLES = 128
TARGET_FILL_SAMPLES = 1024
MAX_FILL_SAMPLES = 2048
MAX_TOPUP_SAMPLES = 128


class WindowsTimerResolution:
    """Temporarily request 1 ms Windows scheduler timer resolution."""

    def __init__(self, milliseconds: int = 1):
        self.milliseconds = int(milliseconds)
        self._enabled = False
        self._winmm = None

    def __enter__(self):
        if sys.platform.startswith("win"):
            try:
                self._winmm = ctypes.WinDLL("winmm")
                if self._winmm.timeBeginPeriod(self.milliseconds) == 0:
                    self._enabled = True
            except Exception:
                self._enabled = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._enabled and self._winmm is not None:
            try:
                self._winmm.timeEndPeriod(self.milliseconds)
            except Exception:
                pass
        self._enabled = False


def precise_wait_until(deadline: float) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            return
        if remaining > SPIN_WAIT_S:
            time.sleep(max(0.0, remaining - SPIN_WAIT_S))
        else:
            time.sleep(0)


def generate_sine(frequency_hz: float, sample_rate: int, duration_s: float, amplitude: float) -> np.ndarray:
    count = max(1, int(round(sample_rate * duration_s)))
    t = np.arange(count, dtype=np.float32) / float(sample_rate)
    return (amplitude * np.sin(2.0 * math.pi * frequency_hz * t)).astype(np.float32)


def stream_for_duration(
    device: HapticDeviceInterface,
    signal: np.ndarray,
    sample_rate: int,
    duration_s: float,
    loop: bool,
    status_interval_s: float = 0.0,
) -> None:
    prefill = min(PREFILL_SAMPLES, len(signal) if not loop else PREFILL_SAMPLES)
    target_fill = min(TARGET_FILL_SAMPLES, len(signal) if not loop else TARGET_FILL_SAMPLES)
    max_fill = min(MAX_FILL_SAMPLES, len(signal) if not loop else MAX_FILL_SAMPLES)
    sent = 0

    def send_samples(sample_count: int) -> int:
        nonlocal sent
        written = 0
        while written < sample_count:
            absolute_position = sent + written
            block_start = absolute_position % len(signal)
            block_count = min(device._render_frame_samples, sample_count - written)
            block_end = block_start + block_count
            if block_end <= len(signal):
                block = signal[block_start:block_end]
            elif loop:
                wrap_count = block_end - len(signal)
                block = np.concatenate((signal[block_start:], signal[:wrap_count]))
            else:
                block = signal[block_start:]
            if len(block) == 0:
                break
            device.write_render_buffer(block)
            written += len(block)
            if not loop and absolute_position + len(block) >= len(signal):
                break
        sent += written
        return written

    send_samples(prefill)
    device.start_rendering()
    start = time.perf_counter()
    next_refill_time = start
    next_status_time = start + status_interval_s if status_interval_s > 0.0 else 0.0
    try:
        with WindowsTimerResolution(1):
            while time.perf_counter() - start < duration_s:
                now = time.perf_counter()
                elapsed = now - start
                target_sent = int(elapsed * sample_rate) + target_fill
                max_sent = int(elapsed * sample_rate) + max_fill
                if not loop:
                    target_sent = min(target_sent, len(signal))
                    max_sent = min(max_sent, len(signal))
                if target_sent > sent:
                    samples_to_send = min(MAX_TOPUP_SAMPLES, max_sent - sent)
                    if samples_to_send > 0:
                        send_samples(samples_to_send)
                if not loop and sent >= len(signal):
                    break
                if status_interval_s > 0.0 and now >= next_status_time:
                    try:
                        status = copy.copy(device.get_status())
                        print(
                            f"    live {elapsed:6.2f}s: rendering={status.rendering} "
                            f"fill={status.render_fill} samples={status.render_samples} "
                            f"underruns={status.underruns} "
                            f"startup_underruns={status.render_startup_underruns} "
                            f"overruns={status.render_overruns} late={status.render_late_ticks} "
                            f"due_max={status.render_due_max} tick_max_us={status.render_tick_max_us}"
                        )
                    except Exception as exc:
                        print(f"    live status failed: {exc}")
                    next_status_time = now + status_interval_s
                next_refill_time += REFILL_INTERVAL_S
                if next_refill_time < time.perf_counter():
                    next_refill_time = time.perf_counter() + REFILL_INTERVAL_S
                precise_wait_until(next_refill_time)
    finally:
        queued_samples = max(0, sent - int((time.perf_counter() - start) * sample_rate))
        drain_time = min(3.0, (queued_samples / max(1, sample_rate)) + 0.1)
        if drain_time > 0.0:
            precise_wait_until(time.perf_counter() + drain_time)
        device.stop_rendering(timeout=5.0)


def recover_device(device: HapticDeviceInterface) -> bool:
    """Best-effort return to idle between sweep points."""
    recovered = True
    try:
        device.stop_rendering(timeout=5.0)
    except Exception as exc:
        print(f"  warning: STOP_RENDER recovery failed: {exc}")
        recovered = False
    try:
        print(f"  recovery PING: {device.ping()}")
    except Exception as exc:
        print(f"  warning: PING recovery failed: {exc}")
        recovered = False
    if not recovered:
        errors = device.recent_errors()
        if errors:
            print(f"  recent device errors: {'; '.join(errors)}")
    return recovered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep host-streamed 200 Hz sine rendering from low to high sample rates."
    )
    parser.add_argument("--port", required=True, help="Serial port, for example COM10")
    parser.add_argument("--pin", type=int, default=0, help="Pixi output pin (default: 0)")
    parser.add_argument("--baudrate", type=int, default=921600)
    parser.add_argument("--freq", type=float, default=200.0, help="Sine frequency in Hz (default: 200)")
    parser.add_argument("--hold", type=float, default=10.0, help="Seconds to hold each sample rate (default: 10)")
    parser.add_argument("--start-rate", type=int, default=1000, help="First render sample rate in Hz")
    parser.add_argument("--stop-rate", type=int, default=20000, help="Last render sample rate in Hz")
    parser.add_argument("--step", type=int, default=1000, help="Sample-rate step in Hz")
    parser.add_argument("--frame-samples", type=int, default=128, help="Samples per render frame, max 128")
    parser.add_argument("--amplitude", type=float, default=0.5, help="Normalized sine amplitude (default: 0.5)")
    parser.add_argument(
        "--live-status",
        type=float,
        default=0.0,
        help="Print firmware status every N seconds during playback; useful for single-rate probing",
    )
    args = parser.parse_args()

    if not 0 <= args.pin < 20:
        parser.error("--pin must be between 0 and 19")
    if args.start_rate <= 0 or args.stop_rate < args.start_rate or args.step <= 0:
        parser.error("sample-rate sweep must satisfy 0 < start-rate <= stop-rate and step > 0")
    if args.hold <= 0:
        parser.error("--hold must be positive")
    if not 0.0 < args.amplitude <= 1.0:
        parser.error("--amplitude must be in (0, 1]")

    device = HapticDeviceInterface(
        port=args.port,
        baudrate=args.baudrate,
        command_timeout=5.0,
        render_frame_samples=args.frame_samples,
    )
    if not device.connect():
        details = "; ".join(device.recent_errors())
        raise SystemExit(f"Failed to connect to {args.port}: {details}")

    try:
        device.set_render_frame_samples(args.frame_samples)
        recover_device(device)
        device.configure_render_outputs([args.pin])
        print(
            f"Host-stream sweep on pin {args.pin}: {args.freq:g} Hz sine, "
            f"{args.hold:g}s per rate, frame_samples={device._render_frame_samples}, baud={args.baudrate}"
        )
        print("Probe DAC pin directly, DC-coupled, relative to analog ground.")
        print("")

        for sample_rate in range(args.start_rate, args.stop_rate + 1, args.step):
            recover_device(device)
            signal = generate_sine(args.freq, sample_rate, max(args.hold + 1.0, 2.0), args.amplitude)
            device.configure_render_timing(sample_rate)

            print(f"[{sample_rate:5d} Hz] streaming for {args.hold:g}s...")
            started = time.monotonic()
            stream_for_duration(device, signal, sample_rate, args.hold, loop=True, status_interval_s=args.live_status)
            elapsed = time.monotonic() - started
            try:
                print(f"  post-stream PING: {device.ping()}")
            except Exception as exc:
                print(f"  warning: post-stream PING failed: {exc}")
                errors = device.recent_errors()
                if errors:
                    print(f"  recent device errors: {'; '.join(errors)}")
            after = copy.copy(device.get_status())

            dropped = after.dropped_frames
            underruns = after.underruns
            startup_underruns = after.render_startup_underruns
            overruns = after.render_overruns
            overvolts = after.render_overvolts
            render_samples = after.render_samples
            bias_samples = after.render_bias_samples
            underrun_bias_samples = after.render_underrun_bias_samples
            late_ticks = after.render_late_ticks
            spi_failures = after.render_spi_failures

            print(
                f"  elapsed={elapsed:.2f}s "
                f"rendering={after.rendering} "
                f"dropped={dropped} underruns={underruns} "
                f"startup_underruns={startup_underruns} overruns={overruns} "
                f"overvolts={overvolts} "
                f"render_fill={after.render_fill} "
                f"render_samples={render_samples} "
                f"bias_samples={bias_samples} underrun_bias={underrun_bias_samples} "
                f"late_ticks={late_ticks} due_max={after.render_due_max} "
                f"spi_failures={spi_failures} tick_max_us={after.render_tick_max_us} "
                f"rx_queue={after.rx_queue_bytes} rx_queue_max={after.rx_queue_max}"
            )
    finally:
        try:
            device.stop_rendering()
        except Exception:
            pass
        device.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
