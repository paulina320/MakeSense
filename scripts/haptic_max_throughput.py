"""
Sweep serial haptic-device throughput and report max stable ksample/s.

Examples:
    python scripts/haptic_max_throughput.py --port COM10 --mode rx
    python scripts/haptic_max_throughput.py --port COM10 --mode tx
    python scripts/haptic_max_throughput.py --port COM10 --mode duplex
    python scripts/haptic_max_throughput.py --port COM10 --mode all
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hardware.haptic_device_interface import HapticDeviceInterface

REFILL_INTERVAL_S = 0.003
PREFILL_SAMPLES = 128
TARGET_FILL_SAMPLES = 1024
MAX_FILL_SAMPLES = 2048
MAX_TOPUP_SAMPLES = 128


@dataclass
class SweepResult:
    requested_sps: int
    rx_sps: float = 0.0
    active_rx_sps: float = 0.0
    tx_sps: float = 0.0
    render_sps: float = 0.0
    active_render_sps: float = 0.0
    crc_failures: int = 0
    dropped_frames: int = 0
    underruns: int = 0
    startup_underruns: int = 0
    overruns: int = 0
    new_errors: int = 0
    ok: bool = False
    note: str = ""

    @property
    def rx_ksps(self) -> float:
        return self.rx_sps / 1000.0

    @property
    def tx_ksps(self) -> float:
        return self.tx_sps / 1000.0

    @property
    def render_ksps(self) -> float:
        return self.render_sps / 1000.0

    @property
    def active_rx_ksps(self) -> float:
        return self.active_rx_sps / 1000.0

    @property
    def active_render_ksps(self) -> float:
        return self.active_render_sps / 1000.0


def requested_rates(start: int, stop: int, factor: float) -> list[int]:
    rates = []
    current = start
    while current <= stop:
        rates.append(current)
        next_rate = int(current * factor)
        current = next_rate if next_rate > current else current + 1
    return rates


def status_tuple(device: HapticDeviceInterface) -> tuple[int, int, int]:
    return device.diagnostic_counts()


def deltas(before: tuple[int, int, int], after: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(0, end - start) for start, end in zip(before, after))


def stable_rx(result: SweepResult, tolerance: float) -> bool:
    if result.crc_failures or result.dropped_frames or result.new_errors:
        return False
    return result.rx_sps >= result.requested_sps * tolerance


def stable_tx(result: SweepResult) -> bool:
    return not (
        result.crc_failures
        or result.dropped_frames
        or result.new_errors
        or "stop_error=" in result.note
        or "stop_render_error=" in result.note
        or "stop_acq_error=" in result.note
    )


def _signal_block(payload: np.ndarray, offset: int, count: int) -> np.ndarray:
    """Return exactly count repeating samples, preserving waveform phase."""
    indices = (np.arange(count) + offset) % len(payload)
    return payload[indices]


def _prefill_render(device: HapticDeviceInterface, payload: np.ndarray) -> int:
    device.write_render_buffer(_signal_block(payload, 0, PREFILL_SAMPLES))
    return PREFILL_SAMPLES


def _stream_render(
    device: HapticDeviceInterface,
    payload: np.ndarray,
    sample_rate: int,
    duration: float,
    sent_samples: int,
    receive=None,
) -> tuple[int, int]:
    """Maintain the same bounded render queue used by the playback sweep."""
    received_samples = 0
    render_started = time.monotonic()
    deadline = render_started + duration
    next_refill = render_started
    while time.monotonic() < deadline:
        now = time.monotonic()
        elapsed = now - render_started
        target_sent = int(elapsed * sample_rate) + TARGET_FILL_SAMPLES
        max_sent = int(elapsed * sample_rate) + MAX_FILL_SAMPLES
        if target_sent > sent_samples:
            count = min(MAX_TOPUP_SAMPLES, max_sent - sent_samples)
            if count > 0:
                device.write_render_buffer(_signal_block(payload, sent_samples, count))
                sent_samples += count
        if receive is not None:
            received_samples += int(receive())
        next_refill += REFILL_INTERVAL_S
        remaining = next_refill - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        else:
            next_refill = time.monotonic()
    return sent_samples, received_samples


def run_rx_trial(device: HapticDeviceInterface, sample_rate: int, duration: float) -> SweepResult:
    before = status_tuple(device)
    samples = 0
    frames = 0
    stop_note = ""
    try:
        device.configure_channel(0, role="input", stream_enabled=True)
        device.configure_channels([0], sample_rate)
        device.start_acquisition()
        started = time.monotonic()
        deadline = started + duration
        while time.monotonic() < deadline:
            chunk = device.read_available_data(512)
            if len(chunk):
                samples += len(chunk)
                frames += 1
            else:
                time.sleep(0.0005)
        drain_deadline = time.monotonic() + 0.2
        while time.monotonic() < drain_deadline:
            chunk = device.read_available_data(512)
            if not len(chunk):
                break
            samples += len(chunk)
            frames += 1
    finally:
        try:
            device.stop_acquisition()
        except Exception as exc:
            stop_note = f" stop_error={exc}"
    elapsed = max(1e-6, time.monotonic() - started)
    after = status_tuple(device)
    crc, dropped, errors = deltas(before, after)
    return SweepResult(
        requested_sps=sample_rate,
        rx_sps=samples / elapsed,
        crc_failures=crc,
        dropped_frames=dropped,
        new_errors=errors,
        ok=False,
        note=f"{frames} rx reads{stop_note}",
    )


def run_tx_trial(device: HapticDeviceInterface, sample_rate: int, duration: float, frame_samples: int) -> SweepResult:
    before = status_tuple(device)
    payload = np.sin(np.linspace(0, 2 * np.pi, frame_samples, dtype=np.float32))
    tx_samples = 0
    stop_note = ""
    operation_started = None
    try:
        device.configure_channel(1, role="output")
        device.send_command("CONFIG_STREAM", sample_rate, "")
        tx_samples = _prefill_render(device, payload)
        # Measure the rendering transaction itself, including START/STOP
        # command round trips but excluding one-time setup and prefill.
        operation_started = time.monotonic()
        device.start_rendering()
        tx_samples, _ = _stream_render(
            device,
            payload,
            sample_rate,
            duration,
            tx_samples,
        )
    finally:
        try:
            device.stop_rendering()
        except Exception as exc:
            stop_note = f" stop_error={exc}"
    elapsed = max(1e-6, time.monotonic() - (operation_started or time.monotonic()))
    status = device.get_status()
    useful_render_samples = max(0, status.render_samples - status.render_underrun_bias_samples)
    after = status_tuple(device)
    crc, dropped, errors = deltas(before, after)
    return SweepResult(
        requested_sps=sample_rate,
        tx_sps=tx_samples / elapsed,
        render_sps=useful_render_samples / elapsed,
        active_render_sps=useful_render_samples / max(1e-6, duration),
        crc_failures=crc,
        dropped_frames=dropped,
        underruns=status.underruns,
        startup_underruns=status.render_startup_underruns,
        overruns=status.render_overruns,
        new_errors=errors,
        ok=False,
        note=f"{frame_samples} samples/frame{stop_note}",
    )


def run_duplex_trial(device: HapticDeviceInterface, sample_rate: int, duration: float, frame_samples: int) -> SweepResult:
    before = status_tuple(device)
    payload = np.sin(np.linspace(0, 2 * np.pi, frame_samples, dtype=np.float32))
    tx_samples = 0
    rx_samples = 0
    stop_note = ""
    operation_started = None
    try:
        device.configure_channel(0, role="input", stream_enabled=True)
        device.configure_channel(1, role="output")
        device.configure_channels([0], sample_rate)
        tx_samples = _prefill_render(device, payload)
        # Include acquisition/render START and STOP round trips, but not
        # channel configuration or the render prefill.
        operation_started = time.monotonic()
        device.start_acquisition()
        device.start_rendering()
        tx_samples, rx_samples = _stream_render(
            device,
            payload,
            sample_rate,
            duration,
            tx_samples,
            receive=lambda: len(device.read_available_data(512)),
        )
    finally:
        try:
            device.stop_rendering()
        except Exception as exc:
            stop_note += f" stop_render_error={exc}"
        try:
            device.stop_acquisition()
        except Exception as exc:
            stop_note += f" stop_acq_error={exc}"
    while True:
        chunk = device.read_available_data(512)
        if not len(chunk):
            break
        rx_samples += len(chunk)
    elapsed = max(1e-6, time.monotonic() - (operation_started or time.monotonic()))
    status = device.get_status()
    useful_render_samples = max(0, status.render_samples - status.render_underrun_bias_samples)
    after = status_tuple(device)
    crc, dropped, errors = deltas(before, after)
    return SweepResult(
        requested_sps=sample_rate,
        rx_sps=rx_samples / elapsed,
        active_rx_sps=rx_samples / max(1e-6, duration),
        tx_sps=tx_samples / elapsed,
        render_sps=useful_render_samples / elapsed,
        active_render_sps=useful_render_samples / max(1e-6, duration),
        crc_failures=crc,
        dropped_frames=dropped,
        underruns=status.underruns,
        startup_underruns=status.render_startup_underruns,
        overruns=status.render_overruns,
        new_errors=errors,
        ok=False,
        note=f"{frame_samples} samples/frame{stop_note}",
    )


def print_result(mode: str, result: SweepResult) -> None:
    marker = "OK" if result.ok else "FAIL"
    print(
        f"{mode:6s} request={result.requested_sps:6d} sps "
        f"rx_e2e={result.rx_ksps:7.2f} ksps "
        f"render_e2e={result.render_ksps:7.2f} ksps "
        f"rx_active={result.active_rx_ksps:7.2f} ksps "
        f"render_active={result.active_render_ksps:7.2f} ksps "
        f"crc={result.crc_failures} drop={result.dropped_frames} "
        f"underrun={result.underruns} startup_underrun={result.startup_underruns} "
        f"overrun={result.overruns} "
        f"errors={result.new_errors} "
        f"{marker} {result.note}"
    )


def sweep_mode(
    device: HapticDeviceInterface,
    mode: str,
    rates: list[int],
    duration: float,
    frame_samples: int,
    tolerance: float,
) -> list[SweepResult]:
    results = []
    for rate in rates:
        if mode == "rx":
            result = run_rx_trial(device, rate, duration)
            result.ok = stable_rx(result, tolerance)
        elif mode == "tx":
            result = run_tx_trial(device, rate, duration, frame_samples)
            result.ok = stable_tx(result) and result.active_render_sps >= rate * tolerance
        elif mode == "duplex":
            result = run_duplex_trial(device, rate, duration, frame_samples)
            result.ok = (
                stable_tx(result)
                and result.active_rx_sps >= rate * tolerance
                and result.active_render_sps >= rate * tolerance
            )
        else:
            raise ValueError(mode)
        print_result(mode, result)
        results.append(result)
        if not result.ok:
            break
        time.sleep(0.2)
    return results


def summarize(mode: str, results: list[SweepResult]) -> None:
    stable = [result for result in results if result.ok]
    if not stable:
        print(f"{mode}: no stable rate found")
        return
    best = stable[-1]
    if mode == "rx":
        print(f"{mode}: max stable {best.rx_ksps:.2f} ksamples/s")
    elif mode == "tx":
        print(
            f"{mode}: max stable rendered_e2e={best.render_ksps:.2f} "
            f"rendered_active={best.active_render_ksps:.2f} ksamples/s"
        )
    else:
        print(
            f"{mode}: max stable rx_e2e={best.rx_ksps:.2f} "
            f"rendered_e2e={best.render_ksps:.2f} "
            f"rx_active={best.active_rx_ksps:.2f} "
            f"rendered_active={best.active_render_ksps:.2f} ksamples/s"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baudrate", type=int, default=921600)
    parser.add_argument("--mode", choices=["rx", "tx", "duplex", "all"], default="all")
    parser.add_argument("--start", type=int, default=500)
    parser.add_argument("--stop", type=int, default=20000)
    parser.add_argument("--factor", type=float, default=1.5)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--frame-samples", type=int, default=128)
    parser.add_argument("--tolerance", type=float, default=0.85)
    args = parser.parse_args()

    rates = requested_rates(args.start, args.stop, args.factor)
    modes = ["rx", "tx", "duplex"] if args.mode == "all" else [args.mode]

    device = HapticDeviceInterface(
        port=args.port,
        baudrate=args.baudrate,
        command_timeout=5.0,
        frame_queue_size=512,
        render_frame_samples=args.frame_samples,
    )
    if not device.connect():
        raise SystemExit(f"failed to connect to {args.port}: {device.recent_errors()}")

    try:
        print(f"rates: {rates}")
        print(f"frame_samples: {args.frame_samples}")
        for mode in modes:
            print("")
            results = sweep_mode(device, mode, rates, args.duration, args.frame_samples, args.tolerance)
            summarize(mode, results)
    finally:
        device.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
