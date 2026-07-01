"""
Serial protocol helpers for the haptic device.

Control traffic is newline-delimited ASCII. Real-time streams use a small
binary frame so the host can resynchronize after dropped or stray bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import List, Tuple, Union


SYNC = b"\xA5\x5A"
HEADER = struct.Struct("<2sBHH")
CRC = struct.Struct("<H")
HEADER_SIZE = HEADER.size
CRC_SIZE = CRC.size
MAX_PAYLOAD_SIZE = 256


class MessageType(IntEnum):
    SAMPLES = 0x01
    OUTPUT_BUFFER = 0x02
    ERROR = 0x03
    STATUS = 0x04
    LOOPBACK = 0x05
    IMU_SAMPLES = 0x06


IMU_SAMPLE = struct.Struct("<IBxhhhhhhhhhii")

# ADXL345 DATA_FORMAT is configured as 0x0B: full-resolution, +/-16 g.
# The datasheet specifies a nominal scale factor of 3.9 mg/LSB in this mode.
ADXL345_G_PER_LSB = 0.0039


@dataclass(frozen=True)
class Frame:
    """Decoded binary frame."""

    message_type: int
    sequence: int
    payload: bytes


@dataclass(frozen=True)
class TextLine:
    """Decoded text response."""

    text: str


ParsedItem = Union[Frame, TextLine]


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """Return CRC-16/CCITT-FALSE for *data*."""
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_frame(message_type: int, sequence: int, payload: bytes = b"") -> bytes:
    """Encode a binary protocol frame."""
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError(f"payload too large: {len(payload)} bytes")
    header = HEADER.pack(SYNC, int(message_type) & 0xFF, len(payload), sequence & 0xFFFF)
    body = header + payload
    return body + CRC.pack(crc16_ccitt(body))


class PacketParser:
    """Incremental parser for mixed text and binary serial traffic."""

    def __init__(self, max_payload_size: int = MAX_PAYLOAD_SIZE):
        self.buffer = bytearray()
        self.max_payload_size = max_payload_size
        self.crc_failures = 0
        self.resync_count = 0

    def feed(self, data: bytes) -> List[ParsedItem]:
        """Feed bytes and return every complete text line or frame."""
        if data:
            self.buffer.extend(data)

        parsed: List[ParsedItem] = []
        while self.buffer:
            if self.buffer.startswith(SYNC):
                frame = self._try_parse_frame()
                if frame is None:
                    break
                parsed.append(frame)
                continue

            sync_index = self.buffer.find(SYNC)
            line_index = self.buffer.find(b"\n")

            if line_index == -1 and sync_index == -1:
                break

            if line_index != -1 and (sync_index == -1 or line_index < sync_index):
                raw = bytes(self.buffer[:line_index])
                del self.buffer[: line_index + 1]
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    parsed.append(TextLine(text))
                continue

            if sync_index > 0:
                del self.buffer[:sync_index]
                self.resync_count += 1
                continue

            break

        return parsed

    def _try_parse_frame(self) -> Frame | None:
        if len(self.buffer) < HEADER_SIZE:
            return None

        sync, message_type, length, sequence = HEADER.unpack(bytes(self.buffer[:HEADER_SIZE]))
        if sync != SYNC:
            del self.buffer[0]
            self.resync_count += 1
            return None
        if length > self.max_payload_size:
            del self.buffer[0]
            self.resync_count += 1
            return None

        frame_size = HEADER_SIZE + length + CRC_SIZE
        if len(self.buffer) < frame_size:
            return None

        raw = bytes(self.buffer[:frame_size])
        del self.buffer[:frame_size]
        expected_crc = CRC.unpack(raw[-CRC_SIZE:])[0]
        actual_crc = crc16_ccitt(raw[:-CRC_SIZE])
        if expected_crc != actual_crc:
            self.crc_failures += 1
            self.resync_count += 1
            return None

        return Frame(message_type=message_type, sequence=sequence, payload=raw[HEADER_SIZE:-CRC_SIZE])


def pack_i16_samples(samples) -> bytes:
    """Pack a numeric sample array as little-endian signed int16 payload."""
    import numpy as np

    clipped = np.clip(samples, -1.0, 1.0)
    ints = np.asarray(clipped * 32767.0, dtype="<i2")
    return ints.tobytes()


def unpack_i16_samples(payload: bytes, channels: int = 1):
    """Unpack little-endian signed int16 samples to float32 [-1, 1]."""
    import numpy as np

    if channels < 1:
        channels = 1
    samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32767.0
    usable = (len(samples) // channels) * channels
    samples = samples[:usable]
    if channels == 1:
        return samples
    return samples.reshape((-1, channels))


def unpack_imu_sample(payload: bytes) -> dict:
    """Unpack one IMU stream sample record."""
    if len(payload) < IMU_SAMPLE.size:
        raise ValueError(f"IMU payload too short: {len(payload)} bytes")
    (
        timestamp_us,
        flags,
        ax,
        ay,
        az,
        gx,
        gy,
        gz,
        mx,
        my,
        mz,
        bmp_pressure_raw,
        bmp_temperature_raw,
    ) = IMU_SAMPLE.unpack(payload[: IMU_SAMPLE.size])
    accel_raw = [ax, ay, az]
    return {
        "timestamp_us": timestamp_us,
        "ok": bool(flags & 0x01),
        "accel_ok": bool(flags & 0x02),
        "gyro_ok": bool(flags & 0x04),
        "mag_ok": bool(flags & 0x08),
        "bmp_ok": bool(flags & 0x10),
        "accel": [value * ADXL345_G_PER_LSB for value in accel_raw],
        "accel_raw": accel_raw,
        "accel_unit": "g",
        "gyro": [gx, gy, gz],
        "mag": [mx, my, mz],
        "bmp_pressure_raw": bmp_pressure_raw,
        "bmp_temperature_raw": bmp_temperature_raw,
    }


def convert_imu_accel_to_g(sample: dict) -> dict:
    """Convert an IMU JSON response containing ADXL345 counts to g."""
    converted = dict(sample)
    accel_raw = list(sample.get("accel_raw", sample.get("accel", [0, 0, 0])))
    converted["accel_raw"] = accel_raw
    converted["accel"] = [float(value) * ADXL345_G_PER_LSB for value in accel_raw]
    converted["accel_unit"] = "g"
    return converted


def unpack_imu_samples(payload: bytes) -> list[dict]:
    """Unpack every IMU stream sample record in one binary frame."""
    if len(payload) % IMU_SAMPLE.size != 0:
        raise ValueError(f"IMU payload has partial sample: {len(payload)} bytes")
    return [
        unpack_imu_sample(payload[offset : offset + IMU_SAMPLE.size])
        for offset in range(0, len(payload), IMU_SAMPLE.size)
    ]


def command(name: str, *args) -> bytes:
    """Build a newline text command."""
    parts = [name.upper(), *(str(arg) for arg in args)]
    return (" ".join(parts) + "\n").encode("ascii")
