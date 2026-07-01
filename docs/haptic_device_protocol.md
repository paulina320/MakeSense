# Serial Haptic Device Protocol

The haptic device uses newline-delimited ASCII commands for control and binary
frames for real-time samples and render buffers.

## Text Commands

- `HELLO`
- `PING`
- `STATUS`
- `GET_CHANNELS`
- `CONFIG_CHANNEL <pin> <role> <partner|-> <adc_range> <dac_range> <reference> <averaging> <stream>`
- `CONFIG_STREAM <sample_rate_hz> <comma_separated_pins>`
- `CONFIG_IMU_STREAM <sample_rate_hz> <0|1>`
- `IMU_STATUS`
- `IMU_READ`
- `START_ACQ`
- `STOP_ACQ`
- `START_RENDER`
- `STOP_RENDER`

Replies are single text lines, usually `OK ...`, `ERR ...`, or `STATUS {...}`.

## Binary Frame

All multibyte values are little-endian.

| Field | Size |
| --- | --- |
| Sync bytes `0xA5 0x5A` | 2 |
| Message type | 1 |
| Payload length | 2 |
| Sequence number | 2 |
| Payload | N |
| CRC16/CCITT-FALSE over header + payload | 2 |

Message types:

- `0x01` samples from device to host
- `0x02` output buffer from host to device
- `0x03` async error from device to host
- `0x04` status snapshot
- `0x05` loopback/benchmark
- `0x06` IMU stream sample

Samples are signed little-endian int16 values. The host scales float samples in
`[-1, 1]` to int16 before transmit and scales received int16 values back to
float.

Acquisition frames may contain multiple consecutive samples. For multiple input
channels, samples are interleaved in configured channel order. The firmware
batches samples up to the binary payload limit or a short flush interval to
reduce per-sample USB and CRC overhead. Current experimental firmware accepts a
256-byte binary payload limit, but output/loopback testing showed that 256-byte
payloads can still wedge USB CDC. Host render buffers therefore default to 32
int16 samples per frame, a 64-byte payload, until the larger-output-frame path is
fixed.

IMU stream frames are emitted while acquisition is running and IMU streaming is
enabled with `CONFIG_IMU_STREAM`. Each frame contains one or more 32-byte IMU
sample records, batched up to the binary payload limit or a short flush
interval. Record layout is little-endian:

| Field | Type |
| --- | --- |
| Device timestamp | `uint32` microseconds |
| Flags | `uint8` bitfield: bit0 any ok, bit1 accel, bit2 gyro, bit3 mag, bit4 BMP |
| Reserved | `uint8` |
| Accel XYZ | 3 x `int16` raw ADXL345 |
| Gyro XYZ | 3 x `int16` raw ITG3200 |
| Mag XYZ | 3 x `int16` raw QMC/VCM5883 |
| BMP pressure raw | `int32` |
| BMP temperature raw | `int32` |

## Host Workflow

Install dependencies:

```bash
pip install -r requirements.txt
```

Use mock mode by default. To use the serial device, set:

```python
HAPTIC_DEVICE_CONFIG["backend"] = "haptic_device"
HAPTIC_DEVICE_CONFIG["default_port"] = "COM6"
```

Then run:

```bash
python main.py
```

Use the `Device` tab to connect, inspect status, and configure Pixi channels.

## Firmware Workflow

Open `device/firmware/haptic_device/haptic_device.ino` in the Arduino IDE or
STM32 Arduino build flow for the STM32F103 Black Pill. The sketch keeps local
copies of `MAX11300.cpp`, `MAX11300.h`, and `MAX11300registers.h` in the same
folder.

Expected Pixi wiring follows the examples:

- `MAX11300 pixi(&SPI, PB0, PA4)`
- `PB0` is CNVT
- `PA4` is chip select

## Diagnostics

Run protocol unit tests:

```bash
python -m unittest discover tests
```

Run throughput checks:

```bash
python scripts/haptic_throughput.py --port COM6 --mode loopback
python scripts/haptic_throughput.py --port COM6 --mode rx
python scripts/haptic_throughput.py --port COM6 --mode duplex
python scripts/haptic_max_throughput.py --port COM6 --mode all
```

Record bytes/s, frames/s, CRC failures, dropped frames, underruns, and command
latency while streaming.
