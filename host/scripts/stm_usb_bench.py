"""
Host runner for the STM32 USB CDC bare-metal benchmark.

Examples:
    python scripts/stm_usb_bench.py --port COM10 --mode all --duration 5
    python scripts/stm_usb_bench.py --port COM10 --mode duplex --payloads 32 64 128 256
    python scripts/stm_usb_bench.py --port COM10 --mode spi --spi-register 0x40 --spi-counts 1 4 20
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from typing import Iterable


RESULT_RE = re.compile(
    rb"RESULT mode=(?P<mode>\w+) elapsed_ms=(?P<elapsed>\d+) "
    rb"tx_bytes=(?P<tx>\d+) rx_bytes=(?P<rx>\d+) "
    rb"packets=(?P<packets>\d+) busy=(?P<busy>\d+)"
)


@dataclass
class BenchResult:
    mode: str
    payload_bytes: int
    duration_s: float
    device_elapsed_ms: int
    tx_bytes: int
    rx_bytes: int
    packets: int
    busy: int
    host_rx_bytes: int
    timeouts: int
    responsive: bool

    @property
    def tx_bytes_s(self) -> float:
        return self.tx_bytes / max(1e-6, self.device_elapsed_ms / 1000.0)

    @property
    def rx_bytes_s(self) -> float:
        return self.rx_bytes / max(1e-6, self.device_elapsed_ms / 1000.0)

    @property
    def tx_ksamples_s(self) -> float:
        return self.tx_bytes_s / 2.0 / 1000.0

    @property
    def rx_ksamples_s(self) -> float:
        return self.rx_bytes_s / 2.0 / 1000.0


def open_serial(port: str, baudrate: int):
    import serial

    return serial.Serial(port, baudrate=baudrate, timeout=0.02, write_timeout=1.0)


def read_for_result(serial_port, deadline: float) -> tuple[bytes, int]:
    buffer = bytearray()
    timeouts = 0
    while time.monotonic() < deadline:
        data = serial_port.read(4096)
        if data:
            buffer.extend(data)
            if RESULT_RE.search(buffer):
                return bytes(buffer), timeouts
        else:
            timeouts += 1
    return bytes(buffer), timeouts


def send_line(serial_port, text: str) -> None:
    serial_port.write(text.encode("ascii") + b"\n")


def hello(serial_port) -> bool:
    serial_port.reset_input_buffer()
    send_line(serial_port, "HELLO")
    deadline = time.monotonic() + 2.0
    buffer = bytearray()
    while time.monotonic() < deadline:
        data = serial_port.read(256)
        if data:
            buffer.extend(data)
            if b"OK HELLO" in buffer:
                return True
    return False


def parse_result(mode: str, payload_bytes: int, duration_s: float, raw: bytes, timeouts: int, responsive: bool) -> BenchResult:
    match = RESULT_RE.search(raw)
    if not match:
        return BenchResult(
            mode=mode,
            payload_bytes=payload_bytes,
            duration_s=duration_s,
            device_elapsed_ms=int(duration_s * 1000),
            tx_bytes=0,
            rx_bytes=0,
            packets=0,
            busy=0,
            host_rx_bytes=len(raw),
            timeouts=timeouts,
            responsive=responsive,
        )
    return BenchResult(
        mode=match.group("mode").decode("ascii"),
        payload_bytes=payload_bytes,
        duration_s=duration_s,
        device_elapsed_ms=int(match.group("elapsed")),
        tx_bytes=int(match.group("tx")),
        rx_bytes=int(match.group("rx")),
        packets=int(match.group("packets")),
        busy=int(match.group("busy")),
        host_rx_bytes=len(raw),
        timeouts=timeouts,
        responsive=responsive,
    )


def run_tx(serial_port, duration_s: float, payload_bytes: int) -> BenchResult:
    serial_port.reset_input_buffer()
    send_line(serial_port, f"TX {int(duration_s * 1000)} {payload_bytes}")
    raw, timeouts = read_for_result(serial_port, time.monotonic() + duration_s + 3.0)
    responsive = hello(serial_port)
    return parse_result("TX", payload_bytes, duration_s, raw, timeouts, responsive)


def run_rx(serial_port, duration_s: float, payload_bytes: int) -> BenchResult:
    serial_port.reset_input_buffer()
    send_line(serial_port, f"RX {int(duration_s * 1000)}")
    payload = bytes([0x33]) * payload_bytes
    deadline = time.monotonic() + duration_s
    host_tx_bytes = 0
    while time.monotonic() < deadline:
        serial_port.write(payload)
        host_tx_bytes += len(payload)
    raw, timeouts = read_for_result(serial_port, time.monotonic() + 3.0)
    responsive = hello(serial_port)
    result = parse_result("RX", payload_bytes, duration_s, raw, timeouts, responsive)
    if result.rx_bytes == 0:
        result.rx_bytes = host_tx_bytes
    return result


def run_duplex(serial_port, duration_s: float, payload_bytes: int) -> BenchResult:
    serial_port.reset_input_buffer()
    send_line(serial_port, f"DUPLEX {int(duration_s * 1000)} {payload_bytes}")
    payload = bytes([0x33]) * payload_bytes
    buffer = bytearray()
    timeouts = 0
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        serial_port.write(payload)
        data = serial_port.read(4096)
        if data:
            buffer.extend(data)
        else:
            timeouts += 1
    tail_deadline = time.monotonic() + 3.0
    tail, tail_timeouts = read_for_result(serial_port, tail_deadline)
    buffer.extend(tail)
    timeouts += tail_timeouts
    responsive = hello(serial_port)
    return parse_result("DUPLEX", payload_bytes, duration_s, bytes(buffer), timeouts, responsive)


def run_spi_read_max(serial_port, duration_s: float, register: int, count: int) -> BenchResult:
    serial_port.reset_input_buffer()
    send_line(serial_port, f"SPI_READ_MAX 0x{register:02X} {count} {int(duration_s * 1000)}")
    raw, timeouts = read_for_result(serial_port, time.monotonic() + duration_s + 3.0)
    responsive = hello(serial_port)
    return parse_result("SPI_READ_MAX", count * 2, duration_s, raw, timeouts, responsive)


def print_result(result: BenchResult) -> None:
    ok = "OK" if result.responsive and (result.tx_bytes or result.rx_bytes) else "FAIL"
    print(
        f"{result.mode:6s} payload={result.payload_bytes:4d} "
        f"tx={result.tx_bytes_s:10.0f} B/s ({result.tx_ksamples_s:7.2f} ksps) "
        f"rx={result.rx_bytes_s:10.0f} B/s ({result.rx_ksamples_s:7.2f} ksps) "
        f"packets={result.packets:7d} busy={result.busy:7d} "
        f"timeouts={result.timeouts:5d} responsive={result.responsive} {ok}"
    )


def print_spi_result(result: BenchResult, register: int, count: int) -> None:
    ok = "OK" if result.responsive and result.rx_bytes else "FAIL"
    print(
        f"{result.mode:12s} reg=0x{register:02X} count={count:3d} "
        f"read={result.rx_bytes_s:10.0f} B/s ({result.rx_ksamples_s:7.2f} ksps) "
        f"bursts={result.packets:7d} errors={result.busy:7d} "
        f"timeouts={result.timeouts:5d} responsive={result.responsive} {ok}"
    )


def run_modes(serial_port, modes: Iterable[str], duration_s: float, payloads: list[int]) -> list[BenchResult]:
    results: list[BenchResult] = []
    for payload in payloads:
        for mode in modes:
            if mode == "tx":
                result = run_tx(serial_port, duration_s, payload)
            elif mode == "rx":
                result = run_rx(serial_port, duration_s, payload)
            elif mode == "duplex":
                result = run_duplex(serial_port, duration_s, payload)
            else:
                raise ValueError(mode)
            print_result(result)
            results.append(result)
            time.sleep(0.25)
    return results


def run_spi_modes(serial_port, duration_s: float, register: int, counts: list[int]) -> list[BenchResult]:
    results: list[BenchResult] = []
    for count in counts:
        result = run_spi_read_max(serial_port, duration_s, register, count)
        print_spi_result(result, register, count)
        results.append(result)
        time.sleep(0.25)
    return results


def parse_int(text: str) -> int:
    return int(text, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM10")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--mode", choices=["tx", "rx", "duplex", "spi", "all"], default="all")
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--payloads", type=int, nargs="+", default=[32, 64, 128, 256])
    parser.add_argument("--spi-register", type=parse_int, default=0x40)
    parser.add_argument("--spi-counts", type=int, nargs="+", default=[1, 4, 8, 16, 20])
    args = parser.parse_args()

    modes = ["tx", "rx", "duplex"] if args.mode == "all" else [args.mode]
    with open_serial(args.port, args.baudrate) as serial_port:
        if not hello(serial_port):
            raise SystemExit(f"{args.port} did not answer HELLO")
        print(f"Connected to {args.port}")
        if args.mode == "spi":
            results = run_spi_modes(serial_port, args.duration, args.spi_register, args.spi_counts)
        else:
            results = run_modes(serial_port, modes, args.duration, args.payloads)

    print("")
    if args.mode == "spi":
        mode_results = [result for result in results if result.responsive]
        if not mode_results:
            print("spi: no responsive result")
        else:
            best = max(mode_results, key=lambda result: result.rx_bytes_s)
            print(
                f"spi best: {best.rx_ksamples_s:.2f} ksamples/s "
                f"at {best.payload_bytes // 2} registers per burst"
            )
        return 0

    for mode in modes:
        mode_results = [result for result in results if result.mode.lower() == mode and result.responsive]
        if not mode_results:
            print(f"{mode}: no responsive result")
            continue
        best_tx = max(mode_results, key=lambda result: result.tx_bytes_s)
        best_rx = max(mode_results, key=lambda result: result.rx_bytes_s)
        if mode == "tx":
            print(f"tx best: {best_tx.tx_ksamples_s:.2f} ksamples/s at payload {best_tx.payload_bytes}")
        elif mode == "rx":
            print(f"rx best: {best_rx.rx_ksamples_s:.2f} ksamples/s at payload {best_rx.payload_bytes}")
        else:
            print(
                f"duplex best: tx={best_tx.tx_ksamples_s:.2f} ksamples/s, "
                f"rx={best_rx.rx_ksamples_s:.2f} ksamples/s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
