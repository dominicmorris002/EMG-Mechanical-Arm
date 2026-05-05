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