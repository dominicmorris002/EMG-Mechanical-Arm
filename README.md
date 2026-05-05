# EMG Mechanical Arm

A myoelectric prosthetic arm that uses surface EMG signals to detect muscle gestures and drive a mechanical arm via a DC motor. The system consists of a **MyoWare 2.0 EMG sensor**, an **RP2040 microcontroller**, and a PC-side AI training pipeline that learns your personal muscle thresholds.

---

## How It Works

1. The **RP2040** reads raw ADC values from the EMG sensor and streams them over USB serial at 1000 samples/sec.
2. A **PC-side Python script** collects labeled EMG data (rest, flex, etc.) and trains a threshold model on your specific muscle signals.
3. The trained thresholds (`FLEX_ON`, `FLEX_OFF`, `FLEX_MAX`) are used by the RP2040 to control the motor driver and move the arm in real time.

---

## Repo Structure

```
EMG-Mechanical-Arm/
├── AITrainingCodeRP2040.py     # MicroPython code — runs on the RP2040 during data collection
├── AITrainingCodeComputer.py   # PC-side: collects data and trains the AI model
├── find_thresholds.py          # PC-side: finds ideal FLEX_ON / FLEX_OFF / FLEX_MAX thresholds
├── learningarm.py              # Experimental / learning scripts
├── protomechanicalarm.py       # Prototype motor control logic
├── Doms PCB/                   # KiCad PCB design files
├── FinalPrint1/                # 3D print files (individual parts)
└── FULLPRINTFULLRightArm.3mf  # Full arm 3MF file for slicing
```

---

## Quickstart

### Step 1 — Flash the RP2040

Copy `AITrainingCodeRP2040.py` to your RP2040 as `main.py` using Thonny or `mpremote`. This streams raw ADC values over USB serial.

```python
# AITrainingCodeRP2040.py — runs on the RP2040
from machine import ADC, Pin
import time

adc = ADC(Pin(27))  # GP27 = ADC1

while True:
    val = adc.read_u16()  # 0–65535
    print(val)
    time.sleep_ms(1)      # ~1000 samples/sec
```

> **Important:** Close Thonny before running the PC training scripts. Both cannot hold the serial port at the same time.

---

### Step 2 — Install PC Dependencies

```bash
pip install numpy scipy pyserial tensorflow
```

---

### Step 3 — Collect EMG Data

```bash
python find_thresholds.py collect --label rest --port COM5 --seconds 20
python find_thresholds.py collect --label flex --port COM5 --seconds 20
```

Replace `COM5` with your actual serial port (`/dev/ttyACM0` on Linux/Mac).

---

### Step 4 — Process Windows

```bash
python find_thresholds.py windows
```

---

### Step 5 — Find Your Thresholds

```bash
python find_thresholds.py train_thresholds
```

This prints your personal `FLEX_ON`, `FLEX_OFF`, and `FLEX_MAX` values. Copy these into your motor control code on the RP2040.

---

## Bill of Materials (BOM)

> Costs omitted — use this as a copy-paste parts list for sourcing.

| Component | Description | Qty | Source / Part # |
|---|---|---|---|
| DC Motor | 12V High Torque Turbine Worm Geared Motor, 200 RPM, 8mm shaft | 1 | MECCANIXITY |
| Motor Driver | L298N Dual H-Bridge Motor Driver | 1 | Generic |
| EMG Sensor | MyoWare 2.0 compatible sensor cable | 1 | MyoWare |
| Electrode Pads | EMG Surface Electrodes, 6-pack | 3 packs | DigiKey #1528-2172-ND (Mfg #2773) |
| Microcontroller | RP2040 + PCB | 1 | Custom PCB via JLCPCB |
| Power Supply | 12V DC (5A) + 5V DC dual output power bank | 1 | Generic |
| Enclosure | Custom 3D-printed enclosure | 1 | Print files in repo |
| Straps | Adjustable straps for arm attachment | 2 | Generic |
| Bearing (small) | 0.315" ID × 0.866" OD × 0.276" W | 15 | DigiKey #1995-1010-ND (Mfg #608-2RS-W/CHEVRONSRI2) |
| Bearing (large) | 0.591" ID × 1.26" OD × 0.354" W | 5 | DigiKey #1995-1014-ND (Mfg #6002ZZ) |
| Thread Inserts | 0.28" Dia × 0.38" H heat-set inserts | 50 | DigiKey #5519-HI-132-WH-ND (Mfg #HI-132-WH) |
| Machine Screws | Pan Phillips #10-32 | 50 | DigiKey #36-9909-ND (Mfg #9909) |
| Switches | SPST-NO 0.001A 5V detect switch | 50 | DigiKey #450-3349-ND (Mfg #JJOV0UL650NONPRBK) |
| PCBs | Custom arm PCBs assembled by JLCPCB | 50 | JLCPCB |
| Miscellaneous | Wires, breadboard, connectors | — | Generic |

---

## Hardware Notes

- EMG sensor connects to **GP27 (ADC1)** on the RP2040
- Motor driver IN1/IN2 pins connect to RP2040 GPIO outputs
- 12V powers the motor; RP2040 runs on 3.3V/5V USB — do not cross-connect
- Electrode placement: two signal electrodes along the muscle belly, one reference on a bony landmark (e.g., elbow)

---

## 3D Printing

The full arm model is included as `FULLPRINTFULLRightArm.3mf`. Individual parts are in the `FinalPrint1/` folder. Recommended print settings: 0.2mm layer height, 40%+ infill for structural parts, PETG or PLA+.

---

## License

MIT — use freely, attribution appreciated.
