"""
Serial haptic device interface.

This module keeps pyserial and protocol details behind the existing DAQ-style
contract used by the PyQt application.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import queue
import threading
import time
from typing import Deque, Dict, List, Optional

import numpy as np

from .daq_interface import DAQInterface
from .serial_protocol import (
    Frame,
    MAX_PAYLOAD_SIZE,
    MessageType,
    PacketParser,
    TextLine,
    command,
    convert_imu_accel_to_g,
    encode_frame,
    pack_i16_samples,
    unpack_imu_samples,
    unpack_i16_samples,
)


@dataclass
class ChannelConfig:
    """Retained host-side view of one MAX11300/Pixi channel."""

    pin: int
    role: str = "high_z"
    differential_partner: Optional[int] = None
    adc_range: str = "0_2_5"
    dac_range: str = "0_10"
    reference: str = "internal"
    averaging: int = 1
    stream_enabled: bool = False


@dataclass
class DeviceStatus:
    connected: bool = False
    port: Optional[str] = None
    firmware: str = "unknown"
    pixi_ok: bool = False
    imu_ok: bool = False
    imu_stream: bool = False
    imu_rate: int = 0
    acquiring: bool = False
    rendering: bool = False
    sample_rate: int = 0
    dropped_frames: int = 0
    underruns: int = 0
    render_startup_underruns: int = 0
    render_overruns: int = 0
    render_overvolts: int = 0
    render_samples: int = 0
    render_bias_samples: int = 0
    render_underrun_bias_samples: int = 0
    render_late_ticks: int = 0
    render_due_max: int = 0
    render_spi_failures: int = 0
    render_tick_max_us: int = 0
    rx_queue_bytes: int = 0
    rx_queue_max: int = 0
    rx_crc_failures: int = 0
    rx_resyncs: int = 0
    render_fill: int = 0
    acquisition_fill: int = 0
    imu_fill: int = 0
    channels: List[ChannelConfig] = field(default_factory=list)
    raw: Dict = field(default_factory=dict)


class HapticDeviceInterface(DAQInterface):
    """High-level interface for the serial haptic device firmware."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 921600,
        timeout: float = 0.2,
        command_timeout: float = 1.0,
        frame_queue_size: int = 64,
        render_frame_samples: int = 128,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.command_timeout = command_timeout
        self._serial = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._io_lock = threading.RLock()
        self._parser = PacketParser()
        self._text_queue: "queue.Queue[str]" = queue.Queue()
        self._sample_frames: "queue.Queue[Frame]" = queue.Queue(maxsize=frame_queue_size)
        self._imu_frames: "queue.Queue[Dict]" = queue.Queue(maxsize=frame_queue_size)
        self._loopback_frames: "queue.Queue[Frame]" = queue.Queue(maxsize=frame_queue_size)
        self._error_log: Deque[str] = deque(maxlen=50)
        self._sequence = 0
        self._sample_rate = 44100
        self._channels = [0]
        self._render_frame_samples = render_frame_samples
        self._running = False
        self._rendering = False
        self._status = DeviceStatus(channels=[ChannelConfig(pin=i) for i in range(20)])

    def list_devices(self) -> List[Dict]:
        """Return available serial ports in a DAQ-like shape."""
        ports = self.get_available_ports()
        return [{"id": i, "name": port, "port": port, "channels": 20} for i, port in enumerate(ports)]

    def select_device(self, device_id: int) -> None:
        devices = self.list_devices()
        if device_id < 0 or device_id >= len(devices):
            raise ValueError(f"Unknown device id: {device_id}")
        self.port = devices[device_id]["port"]

    def configure_channels(self, channels: List[int], sample_rate: int) -> None:
        self._channels = channels or [0]
        self._sample_rate = sample_rate
        if self.is_connected():
            self.send_command("CONFIG_STREAM", sample_rate, ",".join(str(ch) for ch in self._channels))
            for channel in self._channels:
                self.configure_channel(channel, role="input", stream_enabled=True)

    def configure_render_outputs(self, channels: List[int]) -> None:
        """Configure one or more Pixi pins as render outputs."""
        output_channels = channels or [1]
        for channel in output_channels:
            self.configure_channel(
                channel,
                role="output",
                dac_range="0_10",
                stream_enabled=False,
            )

    def configure_render_timing(self, sample_rate: int) -> None:
        """Set the device timer rate used by render playback without enabling inputs."""
        self._sample_rate = int(sample_rate)
        if self.is_connected():
            self.send_command("CONFIG_STREAM", self._sample_rate, "")

    def configure_imu_stream(self, sample_rate: int = 100, enabled: bool = True) -> str:
        sample_rate = int(sample_rate)
        enabled = bool(enabled)
        if self.is_connected():
            reply = self.send_command("CONFIG_IMU_STREAM", sample_rate, int(enabled))
        else:
            reply = "OK offline"
        self._status.imu_rate = sample_rate
        self._status.imu_stream = enabled
        return reply

    def start_acquisition(self) -> None:
        self._clear_queue(self._sample_frames)
        self._clear_queue(self._imu_frames)
        if self.is_connected():
            self.send_command("START_ACQ")
        self._running = True

    def stop_acquisition(self) -> None:
        if self.is_connected():
            self.send_command("STOP_ACQ")
        self._running = False

    def read_data(self, num_samples: int) -> np.ndarray:
        if not self._running:
            raise RuntimeError("Acquisition not running")

        chunks = []
        deadline = time.monotonic() + self.command_timeout
        channels = max(1, len(self._channels))
        while sum(len(chunk) for chunk in chunks) < num_samples and time.monotonic() < deadline:
            try:
                frame = self._sample_frames.get(timeout=0.05)
            except queue.Empty:
                continue
            chunk = unpack_i16_samples(frame.payload, channels=channels)
            chunks.append(chunk)

        if not chunks:
            return np.zeros((0, channels)) if channels > 1 else np.zeros(0)

        data = np.concatenate(chunks, axis=0)
        return data[:num_samples]

    def read_available_data(self, max_samples: int) -> np.ndarray:
        """Return queued acquisition samples without waiting for new frames."""
        channels = max(1, len(self._channels))
        chunks = []
        samples = 0
        while samples < max_samples:
            try:
                frame = self._sample_frames.get_nowait()
            except queue.Empty:
                break
            chunk = unpack_i16_samples(frame.payload, channels=channels)
            chunks.append(chunk)
            samples += len(chunk)
        if not chunks:
            return np.zeros((0, channels)) if channels > 1 else np.zeros(0)
        data = np.concatenate(chunks, axis=0)
        return data[:max_samples]

    def read_available_imu(self, max_samples: int = 16) -> List[Dict]:
        """Return queued IMU stream samples without waiting for new frames."""
        samples = []
        while len(samples) < max_samples:
            try:
                samples.append(self._imu_frames.get_nowait())
            except queue.Empty:
                break
        return samples

    def is_running(self) -> bool:
        return self._running

    def is_rendering(self) -> bool:
        return self._rendering

    def connect(self, port: Optional[str] = None) -> bool:
        """Open serial connection and start the RX thread."""
        if self.is_connected():
            return True
        if port:
            self.port = port
        if not self.port:
            ports = self.get_available_ports()
            if not ports:
                return False
            self.port = ports[0]

        try:
            import serial

            self._serial = serial.Serial(self.port, baudrate=self.baudrate, timeout=self.timeout)
            self._stop_event.clear()
            self._rx_thread = threading.Thread(target=self._rx_loop, name="haptic-device-rx", daemon=True)
            self._rx_thread.start()
            self._status.connected = True
            self._status.port = self.port
            self.hello()
            return True
        except Exception as exc:
            self._error_log.append(f"connect failed: {exc}")
            self._serial = None
            self._status.connected = False
            return False

    def disconnect(self) -> None:
        if self._rendering and self.is_connected():
            try:
                self.stop_rendering()
            except Exception as exc:
                self._error_log.append(f"stop rendering during disconnect failed: {exc}")
        self._stop_event.set()
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.5)
        if self._serial:
            try:
                self._serial.close()
            finally:
                self._serial = None
        self._running = False
        self._rendering = False
        self._status.connected = False

    def is_connected(self) -> bool:
        return self._serial is not None and getattr(self._serial, "is_open", False)

    def get_available_ports(self) -> List[str]:
        try:
            import serial.tools.list_ports

            return [port.device for port in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def hello(self) -> str:
        return self.send_command("HELLO")

    def ping(self) -> str:
        return self.send_command("PING")

    def read_imu_status(self) -> Dict:
        reply = self.send_command("IMU_STATUS")
        return self._json_reply(reply, "OK IMU_STATUS ")

    def read_imu(self) -> Dict:
        reply = self.send_command("IMU_READ")
        return convert_imu_accel_to_g(self._json_reply(reply, "OK IMU_READ "))

    def get_status(self) -> DeviceStatus:
        if self.is_connected():
            try:
                reply = self.send_command("STATUS")
                self._merge_status_reply(reply)
            except Exception as exc:
                self._error_log.append(f"status failed: {exc}")
        self._status.rx_crc_failures = self._parser.crc_failures
        self._status.rx_resyncs = self._parser.resync_count
        self._status.acquisition_fill = self._sample_frames.qsize()
        self._status.imu_fill = self._imu_frames.qsize()
        return self._status

    def configure_channel(
        self,
        pin: int,
        role: str,
        differential_partner: Optional[int] = None,
        adc_range: str = "0_2_5",
        dac_range: str = "0_10",
        reference: str = "internal",
        averaging: int = 1,
        stream_enabled: bool = False,
    ) -> str:
        if pin < 0 or pin >= 20:
            raise ValueError("pin must be between 0 and 19")
        args = [
            pin,
            role,
            differential_partner if differential_partner is not None else "-",
            adc_range,
            dac_range,
            reference,
            averaging,
            int(stream_enabled),
        ]
        if self.is_connected():
            reply = self.send_command("CONFIG_CHANNEL", *args)
        else:
            reply = "OK offline"
        self._status.channels[pin] = ChannelConfig(
            pin=pin,
            role=role,
            differential_partner=differential_partner,
            adc_range=adc_range,
            dac_range=dac_range,
            reference=reference,
            averaging=averaging,
            stream_enabled=stream_enabled,
        )
        return reply

    def start_rendering(self) -> None:
        if self.is_connected():
            self.send_command("START_RENDER")
        self._rendering = True

    def stop_rendering(self, timeout: Optional[float] = None) -> None:
        if self.is_connected():
            previous_timeout = self.command_timeout
            if timeout is not None:
                self.command_timeout = float(timeout)
            try:
                try:
                    self.send_command("STOP_RENDER")
                except TimeoutError:
                    try:
                        status = self.get_status()
                    except Exception:
                        raise
                    if bool(getattr(status, "rendering", self._rendering)):
                        raise
            finally:
                self.command_timeout = previous_timeout
        self._rendering = False

    def write_render_buffer(self, signal: np.ndarray) -> None:
        """Send rendered samples to the device as one or more binary frames."""
        if signal is None:
            return
        if not self.is_connected():
            return
        flat = np.asarray(signal, dtype=np.float32).reshape(-1)
        samples_per_frame = min(self._render_frame_samples, MAX_PAYLOAD_SIZE // 2)
        for offset in range(0, len(flat), samples_per_frame):
            payload = pack_i16_samples(flat[offset : offset + samples_per_frame])
            self._write_frame(MessageType.OUTPUT_BUFFER, payload)

    def set_render_frame_samples(self, frame_samples: int) -> None:
        """Set the binary render payload chunk size used by write_render_buffer."""
        self._render_frame_samples = max(1, min(int(frame_samples), MAX_PAYLOAD_SIZE // 2))

    def set_frame_queue_size(self, frame_queue_size: int) -> None:
        """Resize diagnostic frame queues without reconnecting."""
        size = max(1, int(frame_queue_size))
        self._sample_frames = self._resized_queue(self._sample_frames, size)
        self._imu_frames = self._resized_queue(self._imu_frames, size)
        self._loopback_frames = self._resized_queue(self._loopback_frames, size)

    def record_response(
        self,
        excitation: np.ndarray,
        input_channels: Optional[List[int]] = None,
        output_channels: Optional[List[int]] = None,
        imu_fields: Optional[List[str]] = None,
        imu_sample_rate: int = 100,
    ) -> np.ndarray:
        """Play an excitation buffer and record the streamed response."""
        input_channels = input_channels if input_channels is not None else self._channels
        output_channels = output_channels if output_channels is not None else [1]
        imu_fields = imu_fields or []
        if input_channels:
            self.configure_channels(input_channels, self._sample_rate)
        elif self.is_connected():
            self.configure_render_timing(self._sample_rate)
            self._channels = []
        self.configure_render_outputs(output_channels)
        if imu_fields:
            self.configure_imu_stream(imu_sample_rate, True)
        self.start_acquisition()
        self.start_rendering()

        wanted = len(excitation)
        excitation = np.asarray(excitation, dtype=np.float32).reshape(-1)
        sent_samples = 0
        lead_samples = min(len(excitation), max(256, min(1024, self._sample_rate // 20)))
        render_start = time.monotonic()
        chunks = []
        imu_samples = []
        deadline = time.monotonic() + max(1.0, wanted / max(1, self._sample_rate) + self.command_timeout)
        while (
            (sum(len(chunk) for chunk in chunks) < wanted if input_channels else sent_samples < wanted)
            and time.monotonic() < deadline
        ):
            elapsed = time.monotonic() - render_start
            target_sent = min(wanted, int(elapsed * max(1, self._sample_rate)) + lead_samples)
            while sent_samples < target_sent:
                next_sent = min(wanted, sent_samples + self._render_frame_samples)
                self.write_render_buffer(excitation[sent_samples:next_sent])
                sent_samples = next_sent

            if input_channels:
                chunk = self.read_data(min(512, wanted - sum(len(part) for part in chunks)))
                if len(chunk):
                    chunks.append(chunk)
            if imu_fields:
                imu_samples.extend(self.read_available_imu(128))
            time.sleep(0.001 if input_channels else 0.005)

        self.stop_rendering()
        self.stop_acquisition()
        if imu_fields:
            try:
                self.configure_imu_stream(imu_sample_rate, False)
            except Exception:
                pass

        if chunks:
            response = np.concatenate(chunks, axis=0)
            if response.ndim > 1:
                response = response[:, 0]
        elif imu_fields and imu_samples:
            response = self._imu_field_to_signal(imu_samples, imu_fields[0], wanted)
        else:
            return np.zeros_like(excitation)
        if len(response) < wanted:
            response = np.pad(response, (0, wanted - len(response)))
        return response[:wanted]

    def _imu_field_to_signal(self, imu_samples: List[Dict], field: str, num_samples: int) -> np.ndarray:
        values = np.asarray([self._extract_imu_value(sample, field) for sample in imu_samples], dtype=np.float32)
        timestamps = np.asarray([sample.get("timestamp_us", 0) for sample in imu_samples], dtype=np.float64) / 1_000_000.0
        if len(values) == 0:
            return np.zeros(num_samples, dtype=np.float32)
        if len(values) == 1 or np.all(timestamps == timestamps[0]):
            return np.full(num_samples, values[-1], dtype=np.float32)
        timestamps -= timestamps[0]
        target_time = np.arange(num_samples, dtype=np.float64) / max(1, self._sample_rate)
        return np.interp(target_time, timestamps, values, left=values[0], right=values[-1]).astype(np.float32)

    @staticmethod
    def _extract_imu_value(sample: Dict, field: str) -> float:
        field_map = {
            "accel_x": ("accel", 0),
            "accel_y": ("accel", 1),
            "accel_z": ("accel", 2),
            "gyro_x": ("gyro", 0),
            "gyro_y": ("gyro", 1),
            "gyro_z": ("gyro", 2),
            "mag_x": ("mag", 0),
            "mag_y": ("mag", 1),
            "mag_z": ("mag", 2),
            "pressure": ("bmp_pressure_raw", None),
            "temperature": ("bmp_temperature_raw", None),
        }
        key, index = field_map.get(field, ("accel", 0))
        value = sample.get(key, 0)
        if index is None:
            return float(value)
        return float(value[index]) if len(value) > index else 0.0

    def recent_errors(self) -> List[str]:
        return list(self._error_log)

    def diagnostic_counts(self) -> tuple[int, int, int]:
        """Return host-side diagnostic counters without sending a STATUS command."""
        return self._parser.crc_failures, self._status.dropped_frames, len(self._error_log)

    def send_command(self, name: str, *args) -> str:
        if not self.is_connected():
            raise RuntimeError("Device is not connected")
        with self._io_lock:
            while True:
                try:
                    self._text_queue.get_nowait()
                except queue.Empty:
                    break
            command_name = name.upper()
            self._serial.write(command(name, *args))
            deadline = time.monotonic() + self.command_timeout
            while time.monotonic() < deadline:
                try:
                    line = self._text_queue.get(timeout=0.05)
                except queue.Empty:
                    pass
                else:
                    if line.startswith("READY"):
                        self._error_log.append(line)
                        continue
                    if line.startswith("ERR"):
                        return line
                    if command_name in ("STATUS", "GET_CHANNELS") and line.startswith("STATUS"):
                        return line
                    if command_name == "PING" and line.startswith("OK PONG"):
                        return line
                    if line.startswith(f"OK {command_name}"):
                        return line
                    self._error_log.append(f"unexpected response for {command_name}: {line}")
            raise TimeoutError(f"Timed out waiting for {name} response")

    def _write_frame(self, message_type: int, payload: bytes) -> None:
        frame = encode_frame(message_type, self._sequence, payload)
        self._sequence = (self._sequence + 1) & 0xFFFF
        with self._io_lock:
            self._serial.write(frame)

    def _rx_loop(self) -> None:
        while not self._stop_event.is_set() and self._serial:
            try:
                data = self._serial.read(512)
            except Exception as exc:
                self._error_log.append(f"rx failed: {exc}")
                break
            for item in self._parser.feed(data):
                if isinstance(item, TextLine):
                    self._text_queue.put(item.text)
                elif isinstance(item, Frame):
                    self._handle_frame(item)

    def _handle_frame(self, frame: Frame) -> None:
        if frame.message_type == MessageType.SAMPLES:
            try:
                self._sample_frames.put_nowait(frame)
            except queue.Full:
                self._status.dropped_frames += 1
        elif frame.message_type == MessageType.ERROR:
            self._error_log.append(frame.payload.decode("utf-8", errors="replace"))
        elif frame.message_type == MessageType.STATUS:
            self._merge_status_reply(frame.payload.decode("utf-8", errors="replace"))
        elif frame.message_type == MessageType.IMU_SAMPLES:
            try:
                for sample in unpack_imu_samples(frame.payload):
                    self._imu_frames.put_nowait(sample)
            except queue.Full:
                self._status.dropped_frames += 1
            except Exception as exc:
                self._error_log.append(f"imu frame failed: {exc}")
        elif frame.message_type == MessageType.LOOPBACK:
            try:
                self._loopback_frames.put_nowait(frame)
            except queue.Full:
                self._status.dropped_frames += 1

    def read_loopback_frame(self, timeout: float = 0.2) -> Optional[Frame]:
        """Read one echoed loopback frame for diagnostics."""
        try:
            return self._loopback_frames.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def _clear_queue(target_queue: queue.Queue) -> None:
        while True:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _resized_queue(source_queue: queue.Queue, maxsize: int) -> queue.Queue:
        items = []
        while True:
            try:
                items.append(source_queue.get_nowait())
            except queue.Empty:
                break
        resized: queue.Queue = queue.Queue(maxsize=maxsize)
        for item in items[-maxsize:]:
            try:
                resized.put_nowait(item)
            except queue.Full:
                break
        return resized

    def _merge_status_reply(self, reply: str) -> None:
        if not reply:
            return
        text = reply
        if text.startswith("STATUS "):
            text = text[len("STATUS ") :]
        if not text.startswith("{"):
            self._status.firmware = text
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._status.raw["text"] = reply
            return

        self._status.raw = data
        self._status.firmware = data.get("firmware", self._status.firmware)
        self._status.pixi_ok = bool(data.get("pixi_ok", self._status.pixi_ok))
        self._status.imu_ok = bool(data.get("imu_ok", self._status.imu_ok))
        self._status.imu_stream = bool(data.get("imu_stream", self._status.imu_stream))
        self._status.imu_rate = int(data.get("imu_rate", self._status.imu_rate))
        self._status.acquiring = bool(data.get("acquiring", self._running))
        self._status.rendering = bool(data.get("rendering", self._rendering))
        self._status.sample_rate = int(data.get("sample_rate", self._sample_rate))
        self._status.dropped_frames = int(data.get("dropped_frames", self._status.dropped_frames))
        self._status.underruns = int(data.get("underruns", self._status.underruns))
        self._status.render_startup_underruns = int(
            data.get("render_startup_underruns", self._status.render_startup_underruns)
        )
        self._status.render_overruns = int(data.get("render_overruns", self._status.render_overruns))
        self._status.render_overvolts = int(data.get("render_overvolts", self._status.render_overvolts))
        self._status.render_fill = int(data.get("render_fill", self._status.render_fill))
        self._status.render_samples = int(data.get("render_samples", self._status.render_samples))
        self._status.render_bias_samples = int(data.get("render_bias_samples", self._status.render_bias_samples))
        self._status.render_underrun_bias_samples = int(
            data.get("render_underrun_bias_samples", self._status.render_underrun_bias_samples)
        )
        self._status.render_late_ticks = int(data.get("render_late_ticks", self._status.render_late_ticks))
        self._status.render_due_max = int(data.get("render_due_max", self._status.render_due_max))
        self._status.render_spi_failures = int(data.get("render_spi_failures", self._status.render_spi_failures))
        self._status.render_tick_max_us = int(data.get("render_tick_max_us", self._status.render_tick_max_us))
        self._status.rx_queue_bytes = int(data.get("rx_queue_bytes", self._status.rx_queue_bytes))
        self._status.rx_queue_max = int(data.get("rx_queue_max", self._status.rx_queue_max))

    @staticmethod
    def _json_reply(reply: str, prefix: str) -> Dict:
        if not reply or not reply.startswith(prefix):
            return {"ok": False, "raw": reply}
        try:
            return json.loads(reply[len(prefix) :])
        except json.JSONDecodeError:
            return {"ok": False, "raw": reply}


def create_haptic_device_interface(settings: Optional[Dict] = None) -> HapticDeviceInterface:
    """Factory for the serial haptic device backend."""
    settings = settings or {}
    return HapticDeviceInterface(
        port=settings.get("default_port"),
        baudrate=settings.get("baudrate", 921600),
        timeout=settings.get("serial_timeout", 0.2),
        command_timeout=settings.get("command_timeout", 1.0),
        frame_queue_size=settings.get("frame_queue_size", 64),
        render_frame_samples=settings.get("render_frame_samples", 128),
    )
