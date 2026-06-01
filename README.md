# AEM_2026
Applied Experimental Methods 2026


## Setup - script

1. Install arduino-cli
2. Run:

Linux/macOS:
  ./setup.sh

Windows:
  powershell -ExecutionPolicy Bypass -File .\setup.ps1

## Setup - Manual
See `docs`


# Hardware Components

## Core Electronics

| Component       | Part Number         | Manufacturer   | Description                                     |
| --------------- | ------------------- | -------------- | ----------------------------------------------- |
| MCU             | STM32F411 BlackPill | DFRobot   | Main microcontroller platform                   |
| ADC/DAC         | PIXI Click          | Mikroe         | Analog-to-digital / digital-to-analog interface |
| Audio Amplifier | Audio Click 2       | Mikroe         | Audio and actuator drive amplifier              |
| IMU             | Fermion 10-DOF IMU  | DFRobot        | Motion and orientation sensing                  |

---

## Haptic Actuators

| Component                 | Part Number    | Manufacturer  | Description                                 |
| ------------------------- | -------------- | ------------- | ------------------------------------------- |
| Wide-Band Haptic Actuator | TH-D-952395-MF | Titan Haptics | High-performance wide-band tactile actuator |
| Circular LRA              | VG0832013D     | Vybronics     | Compact linear resonant actuator            |
| Wide-Band LRA             | VLV101040A     | Vybronics     | Wide-frequency-range LRA                    |
| Narrow-Band LRA           | VL120628H      | Vybronics     | Resonant narrow-band LRA                    |

---

## Thermal Feedback

| Component       | Part Number      | Manufacturer | Description                           |
| --------------- | ---------------- | ------------ | ------------------------------------- |
| Peltier Element | CP40236          | Same Sky     | Thermoelectric heating/cooling module |
| Thermistor      | 223FU3122-07U015 | Semitec      | Temperature sensing                   |

---

## Force & Pressure Sensing

| Component                | Part Number     | Manufacturer          | Description                       |
| ------------------------ | --------------- | --------------------- | --------------------------------- |
| Load Cell                | YZC-131 (1 kg)  | -               | Force measurement                 |
| Load Cell Amplifier      | AD620 Module    | -           | Signal conditioning for load cell |
| Force Sensitive Resistor | FSR402 Circular | Interlink Electronics | Pressure/force sensing            |

---

## Power

| Component                                     | Manufacturer | Description                  |
| --------------------------------------------- | ------------ | ---------------------------- |
| Breadboard Power Supply (3.3 V / 5 V, 500 mA) | - | Low-power prototyping supply |
| 12 V / 60 W Power Adapter                     | LattePanda   | Main external power source   |

---

## Prototyping Hardware

| Component                  | Part Number   | Manufacturer       |
| -------------------------- | ------------- | ------------------ |
| Perfboard                  | 8015          | - |
| Small Breadboard           | -    | -     |
| Female-Female Jumper Wires | 1950          | Adafruit           |
| Female-Male Jumper Wires   | 1954          | Adafruit           |
| Male-Male Jumper Wires     | 1957          | Adafruit           |
| Nylon Standoff Kit         | 3299          | Adafruit           |
| Rubber Feet (3 mm)         | SJ-5008-BLACK | 3M                 |
| Rubber Feet (5 mm)         | SJ-5018-BLACK | 3M                 |

---
