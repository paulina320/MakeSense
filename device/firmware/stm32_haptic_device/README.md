# STM32 Haptic Device Firmware

This is the STM32CubeIDE port of the Arduino haptic device firmware. It keeps
the same host-facing protocol used by `host/hardware/serial_protocol.py`:

- newline text commands: `HELLO`, `PING`, `STATUS`, `CONFIG_CHANNEL`,
  `CONFIG_STREAM`, `START_ACQ`, `STOP_ACQ`, `START_RENDER`, `STOP_RENDER`,
  `DAC_TEST`
- binary frames with sync `A5 5A`, message type, payload length, sequence, and
  CRC16/CCITT-FALSE
- sample frames, output-buffer frames, async error frames, and loopback frames

## Code Layout

- `Core/Src/haptic_app.c`: command handling, frame parser, acquisition/render
  scheduler, render ring buffer, loopback
- `Core/Src/haptic_protocol.c`: binary frame headers and CRC helpers
- `Core/Src/haptic_usb.c`: USB CDC receive ring and transmit helpers
- `Core/Src/max11300.c`: MAX11300 register and burst access over SPI
- generated Cube/HAL code stays in `Core`, `USB_DEVICE`, `Drivers`, and
  `Middlewares`

## CubeIDE Setup

Import this folder as an existing STM32CubeIDE project:

```text
device/firmware/stm32_haptic_device
```

The copied project is configured for the current STM32F411CEU6 Black Pill style
target with USB CDC and SPI1 enabled.

Important peripheral settings:

- USB FS device CDC on `PA11`/`PA12`
- SPI1 full-duplex master:
  - `PA5`: SCK
  - `PA6`: MISO
  - `PA7`: MOSI
  - mode 0, MSB first, software NSS
- MAX11300 control GPIO:
  - `PA4`: chip select, default high
  - `PB0`: CNVT, default high
- Clock:
  - SYSCLK/HCLK: 96 MHz
  - APB2: 96 MHz
  - SPI1 prescaler `/8`, giving 12 MHz SPI for first bring-up
  - USB clock: 48 MHz

## First Tests

After flashing, check the text protocol:

```powershell
python -c "import serial,time; s=serial.Serial('COM10',timeout=1); time.sleep(.2); s.write(b'HELLO\n'); print(s.read(200)); s.close()"
```

Then run the existing host diagnostics:

```powershell
python host\scripts\haptic_throughput.py --port COM10 --mode loopback
python host\scripts\haptic_throughput.py --port COM10 --mode rx
python host\scripts\haptic_throughput.py --port COM10 --mode duplex
```

If basic protocol works, use the GUI Device tab against `COM10`.

## DAC Output Test

`DAC_TEST` stops rendering, configures one MAX11300 pin for the unipolar
`0 V ... 10 V` DAC range, and holds a safe test voltage around the 2.5 V
render bias:

```text
DAC_TEST <pin> <2200|2500|2800>
```

For example, test pin 1 at the three expected DAC voltages:

```text
DAC_TEST 1 2200
DAC_TEST 1 2500
DAC_TEST 1 2800
```

The values are millivolts at the DAC pin, before the external amplifier.
Relative to the 2.5 V bias, and with 20 dB voltage gain, they correspond to
approximately -3 V, 0 V, and +3 V AC after the amplifier input coupling.
