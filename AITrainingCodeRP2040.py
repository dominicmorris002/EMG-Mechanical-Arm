from machine import ADC, Pin
import time

adc = ADC(Pin(27))  # GP26 = ADC0 on RP2040

while True:
    val = adc.read_u16()  # 0–65535
    print(val)
    time.sleep_ms(1)  # ~1000 samples/sec to match FS=1000
    
#Must Run on Rp2040 while Thonny Closed at Same Time Python Training Commands are Done