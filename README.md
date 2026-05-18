# EMG Mechanical Arm

A myoelectric prosthetic arm that uses surface EMG signals to detect muscle gestures and drive a mechanical arm via a DC motor. The system consists of a **MyoWare 2.0 EMG sensor**, an **RP2040 microcontroller**, and a **DC motor driver** to control a 3D-printed mechanical arm.

---

## How It Works

1. The **RP2040** reads raw ADC values from the EMG sensor and streams them over USB serial at 1000 samples/sec.
2. A **PC-side Python script** collects labeled EMG data (rest, flex, etc.) and trains a threshold model on your specific muscle signals.
3. The trained thresholds (`FLEX_ON`, `FLEX_OFF`, `FLEX_MAX`) are used by the RP2040 to control the motor driver and move the arm in real time.

---

## Repo Structure

```
EMG-Mechanical-Arm/
├── protomechanicalarm.py       # MicroPython code - Main product. Pre-tuned thresholds. Runs on RP2040 as main.py
├── learningarm.py              # MicroPython code - Optional. Adjusts thresholds automatically over time for better responsiveness
├── AITrainingCodeRP2040.py     # MicroPython code — runs on the RP2040 during AI data collection
├── AITrainingCodeComputer.py   # PC-side: collects data and trains the AI model
├── find_thresholds.py          # PC-side: finds ideal FLEX_ON / FLEX_OFF / FLEX_MAX thresholds
├── Doms PCB/                   # KiCad PCB design files
├── FinalPrint1/                # 3D print files (individual parts)
└── FULLPRINTFULLRightArm.3mf  # Full arm 3MF file for slicing
```

---

## Quickstart

You can choose to skip the AI thresholds and learning files as they work but are not needed for the product to run well. For the fastest and easiest approach plug in the PCB via USB to your computer.

1. **Download Thonny** and open `protomechanicalarm.py`
2. **Download MicroPython** onto the PCB through Thonny's interface at the bottom right — choose RP2040
3. **Save the file** by clicking File → Save As → MicroPython Device, and type `main.py`
4. The program will now always be stored on the chip and work as soon as plugged in

To change the trigger values of the sensor, simply change them in the code. The closer they are, the snappier they will be. Account for some amount of noise present. **14000 and 18000 are good starting numbers.**

---

## Optional: Learning Mode

If you want the arm to adapt and improve over time, use `learningarm.py` instead of `protomechanicalarm.py`. This version automatically adjusts the thresholds (`FLEX_ON`, `FLEX_OFF`, `FLEX_MAX`) based on your muscle signals during use. It learns from each flex/relax cycle and gets more responsive and personalized over time.

### How Learning Mode Works

- Tracks the peak muscle signal from each flex cycle
- Recalculates thresholds after each use based on a history of your last 10 peak signals
- Keeps thresholds within safe limits to prevent drift
- Prints threshold updates to the console so you can monitor adaptation

### When to Use Learning Mode

- You want the arm to automatically personalize to your muscle patterns
- You prefer not to manually tune threshold values
- You want the system to adapt to day-to-day variations in your signal

### Learning Mode Code

```python
from machine import Pin, ADC, PWM
import time

# --- Sensor ---
adc = ADC(Pin(27))

# --- H-Bridge pins ---
in1 = Pin(4, Pin.OUT); in2 = Pin(5, Pin.OUT)
en1 = PWM(Pin(8)); en1.freq(20000)

# --- LEDs ---
leds = [Pin(2, Pin.OUT), Pin(3, Pin.OUT), Pin(16, Pin.OUT), Pin(17, Pin.OUT)]

# --- Motor ---
def motor_forward(speed):
    in1.value(1); in2.value(0)
    en1.duty_u16(int(65535 * speed))
def motor_reverse(speed):
    in1.value(0); in2.value(1)
    en1.duty_u16(int(65535 * speed))
def motor_stop():
    in1.value(0); in2.value(0)
    en1.duty_u16(0)

# --- Rolling average ---
WINDOW = 20
readings = [0] * WINDOW
read_idx = 0
def smoothed_read():
    global read_idx
    val = adc.read_u16()
    readings[read_idx] = val
    read_idx = (read_idx + 1) % WINDOW
    return sum(readings) // WINDOW

# ============================================================
# --- Adaptive Smart Thresholds ---
# Tuned for: resting signal ~14500, peaks hitting 65535
#
# Signal zones:
#   ~14500  = fully relaxed (idle)
#   15200   = FLEX_OFF — just above idle, easy to drop below when relaxing
#   20971   = FLEX_ON  — clear activation point
#   60000+  = full flex
# ============================================================
FLEX_ON  = 20000
FLEX_OFF = 15200   # tight above idle ~14500 — relaxing easily clears this
FLEX_MAX = 60000

MIN_SPEED = 0.15
MAX_SPEED = 0.90

# Adaptive ratios
ON_RATIO       = 0.32
OFF_RATIO      = 0.24   # tracks just above idle fraction of avg peak
MAX_LEARN_RATE = 0.10

# Peak history
PEAK_HISTORY  = 10
best_peak     = FLEX_MAX
session_peaks = []

# Clamp limits — OFF kept tight above idle band
FLEX_ON_MIN  = 17000; FLEX_ON_MAX  = 40000
FLEX_OFF_MIN = 14800; FLEX_OFF_MAX = 18000  # never stray far from idle+700
FLEX_MAX_MIN = 40000; FLEX_MAX_MAX = 65000

flex_peak_this_rep = 0

def update_adaptive_thresholds(peak):
    global FLEX_ON, FLEX_OFF, FLEX_MAX, best_peak, session_peaks

    if peak < FLEX_ON:
        return  # ignore junk reps

    if peak > best_peak:
        best_peak = peak
        print("[Adaptive] New best peak: {}".format(best_peak))

    session_peaks.append(peak)
    if len(session_peaks) > PEAK_HISTORY:
        session_peaks.pop(0)

    avg_peak = sum(session_peaks) // len(session_peaks)

    new_on  = int(avg_peak * ON_RATIO)
    new_off = int(avg_peak * OFF_RATIO)
    new_max = int(FLEX_MAX + MAX_LEARN_RATE * (best_peak - FLEX_MAX))

    FLEX_ON  = max(FLEX_ON_MIN,  min(new_on,  FLEX_ON_MAX))
    FLEX_OFF = max(FLEX_OFF_MIN, min(new_off, FLEX_OFF_MAX))
    FLEX_MAX = max(FLEX_MAX_MIN, min(new_max, FLEX_MAX_MAX))

    # Enforce gap: OFF must always be below ON with room to spare
    if FLEX_OFF >= FLEX_ON - 2000:
        FLEX_OFF = FLEX_ON - 2500

    print("[Adaptive] ON:{} OFF:{} MAX:{} (avg_peak:{} best:{})".format(
        FLEX_ON, FLEX_OFF, FLEX_MAX, avg_peak, best_peak))

# ============================================================

# --- Timing ---
DEBOUNCE_MS = 150   # hold above FLEX_ON this long to activate
RELEASE_MS  = 120   # hold below FLEX_OFF this long to stop
GUARD_MS    = 500   # min gap between stop and next activation

# --- State ---
flex_above_since   = None
flex_below_since   = None
last_stop          = -9999
is_flexing         = False
direction          = "FORWARD"
current_speed      = 0.0
RAMP_STEP          = 0.03

def ramp_speed(target):
    global current_speed
    if target > current_speed:
        current_speed = min(current_speed + RAMP_STEP, target)
    else:
        current_speed = max(current_speed - RAMP_STEP, target)
    return current_speed

def muscle_to_speed(muscle):
    clamped = max(FLEX_ON, min(muscle, FLEX_MAX))
    t = (clamped - FLEX_ON) / max(1, (FLEX_MAX - FLEX_ON))
    return MIN_SPEED + t * (MAX_SPEED - MIN_SPEED)

# Seed rolling buffer
for _ in range(WINDOW):
    smoothed_read()

# --- LED ---
led_pattern   = [(1,0,0,0),(1,1,0,0),(1,1,1,0),(1,1,1,1),(0,0,0,0)]
led_step      = 0
led_interval  = 300
last_led_time = time.ticks_ms()

print_interval  = 200
last_print_time = time.ticks_ms()

print("Ready!")
print("Thresholds | ON:{} OFF:{} MAX:{}  DEBOUNCE:{}ms RELEASE:{}ms".format(
    FLEX_ON, FLEX_OFF, FLEX_MAX, DEBOUNCE_MS, RELEASE_MS))
print("Idle should read BELOW OFF:{}".format(FLEX_OFF))

while True:
    now    = time.ticks_ms()
    muscle = smoothed_read()

    # --- LED pattern ---
    if time.ticks_diff(now, last_led_time) >= led_interval:
        p = led_pattern[led_step]
        for i, led in enumerate(leds):
            led.value(p[i])
        led_step = (led_step + 1) % len(led_pattern)
        last_led_time = now

    # -------------------------------------------------------
    # NOT flexing — watch for activation
    # -------------------------------------------------------
    if not is_flexing:
        if muscle >= FLEX_ON:
            if flex_above_since is None:
                flex_above_since = now
            elif (time.ticks_diff(now, flex_above_since) >= DEBOUNCE_MS
                  and time.ticks_diff(now, last_stop) >= GUARD_MS):
                is_flexing         = True
                current_speed      = 0.0
                flex_peak_this_rep = muscle
                flex_above_since   = None
                flex_below_since   = None
                print("Flex -> {}".format(direction))
        else:
            flex_above_since = None

    # -------------------------------------------------------
    # IS flexing — drive motor, watch for release
    # -------------------------------------------------------
    if is_flexing:
        if muscle >= FLEX_OFF:
            # Signal healthy — keep driving, reset release timer
            flex_below_since = None

            if muscle > flex_peak_this_rep:
                flex_peak_this_rep = muscle

            speed = ramp_speed(muscle_to_speed(muscle))
            if direction == "FORWARD":
                motor_forward(speed)
            else:
                motor_reverse(speed)

        else:
            # Signal dropped below OFF — start release timer
            if flex_below_since is None:
                flex_below_since = now
            elif time.ticks_diff(now, flex_below_since) >= RELEASE_MS:
                # Held low long enough — genuine relax
                is_flexing    = False
                current_speed = 0.0
                motor_stop()
                last_stop        = now
                flex_below_since = None
                flex_above_since = None

                update_adaptive_thresholds(flex_peak_this_rep)
                flex_peak_this_rep = 0

                direction = "REVERSE" if direction == "FORWARD" else "FORWARD"
                print("Relax -> STOP  (next: {})".format(direction))

    # -------------------------------------------------------
    # Print
    # -------------------------------------------------------
    if time.ticks_diff(now, last_print_time) >= print_interval:
        if is_flexing:
            print("Sensor:{}  {}  speed:{:.0f}%  target:{:.0f}%  peak:{}  OFF:{}".format(
                muscle, direction,
                current_speed * 100,
                muscle_to_speed(muscle) * 100,
                flex_peak_this_rep,
                FLEX_OFF))
        else:
            print("Idle | sensor:{}  ON:{}  OFF:{}".format(muscle, FLEX_ON, FLEX_OFF))
        last_print_time = now
```

After each flex/relax cycle, you'll see output like:
```
[Adaptive] ON:19500 OFF:15100 MAX:58000 (avg_peak:60937 best:65535)
[Adaptive] ON:19200 OFF:15050 MAX:58500 (avg_peak:60200 best:65535)
```

The thresholds refine themselves based on your actual muscle patterns.

---

## Advanced: AI Training Mode

The AI training mode uses a Python script on your computer to collect muscle data and calculate optimal thresholds for you. This is optional and requires running Python scripts alongside the RP2040 code.

### Step 1 — Flash the RP2040 for Data Collection

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
| Power Supply | 12V DC (5A) + 5V DC dual output power bank | 1 | ColdBye Dual Source Power Bank 12V and 5V |
| Enclosure | Custom 3D-printed enclosure | 1 | Print files in repo |
| Straps | Adjustable straps for arm attachment | 2 | Generic |
| Bearing (small) | 0.315" ID × 0.866" OD × 0.276" W | 15 | DigiKey #1995-1010-ND (Mfg #608-2RS-W/CHEVRONSRI2) |
| Bearing (large) | 0.591" ID × 1.26" OD × 0.354" W | 5 | DigiKey #1995-1014-ND (Mfg #6002ZZ) |
| Thread Inserts | 0.28" Dia × 0.38" H heat-set inserts | 50 | DigiKey #5519-HI-132-WH-ND (Mfg #HI-132-WH) |
| Machine Screws | Pan Phillips #10-32 | 50 | DigiKey #36-9909-ND (Mfg #9909) |
| Switches | SPST-NO 0.001A 5V detect switch | 50 | DigiKey #450-3349-ND (Mfg #JJOV0UL650NONPRBK) |
| PCBs | Custom arm PCBs assembled by JLCPCB | 1 | JLCPCB |
| Miscellaneous | Wires, breadboard, connectors | — | Generic |

---

## Hardware Notes

- EMG sensor connects to **GP27 (ADC1)** on the RP2040
- Motor driver IN1/IN2 pins connect to RP2040 GPIO outputs
- 12V powers the motor; RP2040 runs on 3.3V/5V USB — do not cross-connect
- Electrode placement: two signal electrodes along the muscle belly, one reference on a bony landmark (e.g., elbow)

---

## 3D Printing

The full arm model is included as `FULLPRINTFULLRightArm.3mf`. Individual parts are in the `FinalPrint1/` folder. Recommended print settings: H2D Printer Size with PLA Component.

---

## Project Gallery

<div align="center">

https://github.com/user-attachments/assets/b0d67ed7-32eb-4f09-bf58-b973187cbe4e


</div>

<div align="center">

<img alt="Arm Assembly" src="https://github.com/user-attachments/assets/e13ed429-8436-43f8-8f4e-50e7ae09e667" width="600">

</div>

<div align="center">

<img alt="Full Arm Design" src="https://github.com/user-attachments/assets/dd11ffbc-0ded-4894-8a71-866aa3b3a3c3" width="500">

</div>

<div align="center">

<img alt="Mechanical Detail" src="https://github.com/user-attachments/assets/8d8da3b6-6381-4575-b110-fbb99e760b7e" width="500">

</div>

<div align="center">

<img alt="Circuit Diagram" src="https://github.com/user-attachments/assets/b9a14e70-0c84-4ab1-ae8f-1a413bc671ae" width="350">

</div>

<div align="center">

<img alt="System Overview" src="https://github.com/user-attachments/assets/b36c49d7-a5d8-47f0-86c6-bd991ada19fa" width="600">

</div>

---

## License

### Custom License — EMG Mechanical Arm

**Copyright © 2026 Dominic Morris** — All Rights Reserved (unless specified below)

This project is shared under a **modified open-source license** with the following terms:

#### Permitted Uses:
- **Personal & Educational Use:** You may freely use, study, modify, and build upon this work for personal, non-commercial, and educational purposes.
- **Open Source Contributions:** You may fork, modify, and improve this project for non-commercial use.

#### Requirements:
- **Attribution Required:** You must credit Dominic Morris and link to this repository in any public use, distribution, or derived work.
- **Share Modifications:** Any modifications, improvements, or derivative works must be publicly shared (open-sourced) and made available to the community with attribution.
- **No Commercial Resale Without Permission:** You may NOT sell, commercialize, or profit from this work or any derivative without explicit written permission and a commercial licensing agreement.

#### Commercial Use:
- If you wish to commercialize this work (sell it as a product, include it in a commercial offering, or generate profit):
  1. You **must obtain explicit written permission** from Dominic Morris
  2. Dominic Morris **must receive credit** as the original creator
  3. Dominic Morris **must receive a fair share of profit** (terms to be negotiated)
  4. A formal licensing agreement must be established before commercialization

#### Disclaimer:
THIS PROJECT IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. THE AUTHOR IS NOT LIABLE FOR ANY DAMAGES, INJURIES, OR LOSSES RESULTING FROM USE OF THIS PROJECT.

---

**For inquiries regarding commercial licensing, collaborations, or permission requests, please contact Dominic Morris.**
