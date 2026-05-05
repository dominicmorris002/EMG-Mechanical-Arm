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

# --- AI-optimized thresholds ---
FLEX_ON   = 18000  # when flex is detected
FLEX_OFF  = 14000  # when to stop
FLEX_MAX  = 40000  # full flex value
MIN_SPEED = 0.15
MAX_SPEED = 0.55

# --- Debounce ---
DEBOUNCE_MS = 80
flex_above_since = None

# --- Direction guard ---
GUARD_MS = 500
last_stop = -9999

# --- Speed ramping ---
current_speed = 0.0
RAMP_STEP = 0.03

def ramp_speed(target):
    global current_speed
    if target > current_speed:
        current_speed = min(current_speed + RAMP_STEP, target)
    else:
        current_speed = max(current_speed - RAMP_STEP, target)
    return current_speed

def muscle_to_speed(muscle):
    # clamp muscle to valid range
    clamped = max(FLEX_ON, min(muscle, FLEX_MAX))
    t = (clamped - FLEX_ON) / (FLEX_MAX - FLEX_ON)
    return MIN_SPEED + t * (MAX_SPEED - MIN_SPEED)

# --- State ---
is_flexing = False
direction = "FORWARD"

# Seed rolling buffer
for _ in range(WINDOW):
    smoothed_read()

# --- LED ---
led_pattern = [(1,0,0,0),(1,1,0,0),(1,1,1,0),(1,1,1,1),(0,0,0,0)]
led_step = 0
led_interval = 300
last_led_time = time.ticks_ms()

print_interval = 200
last_print_time = time.ticks_ms()

print("Ready! AI thresholds + debounced control")

while True:
    now = time.ticks_ms()
    muscle = smoothed_read()

    # LED pattern
    if time.ticks_diff(now, last_led_time) >= led_interval:
        p = led_pattern[led_step]
        for i, led in enumerate(leds):
            led.value(p[i])
        led_step = (led_step + 1) % len(led_pattern)
        last_led_time = now

    # Flex detection
    if not is_flexing:
        if muscle >= FLEX_ON:
            if flex_above_since is None:
                flex_above_since = now
            elif (time.ticks_diff(now, flex_above_since) >= DEBOUNCE_MS
                  and time.ticks_diff(now, last_stop) >= GUARD_MS):
                is_flexing = True
                current_speed = 0.0
                flex_above_since = None
                print("Flex -> {}".format(direction))
        else:
            flex_above_since = None

    # Ramp motor while flexing
    if is_flexing and muscle >= FLEX_OFF:
        speed = ramp_speed(muscle_to_speed(muscle))
        if direction == "FORWARD":
            motor_forward(speed)
        else:
            motor_reverse(speed)

    # Flex released
    elif is_flexing and muscle < FLEX_OFF:
        is_flexing = False
        current_speed = 0.0
        motor_stop()
        last_stop = now
        direction = "REVERSE" if direction == "FORWARD" else "FORWARD"
        print("Relax -> STOP  (next: {})".format(direction))

    # Print
    if time.ticks_diff(now, last_print_time) >= print_interval:
        if is_flexing:
            print("Sensor: {}  |  {}  speed: {:.0f}%  (target: {:.0f}%)".format(
                muscle, direction, current_speed*100, muscle_to_speed(muscle)*100))
        last_print_time = now