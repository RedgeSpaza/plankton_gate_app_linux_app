from gpiozero import Button
from signal import pause
import sys
import json
import time

button = Button(18, bounce_time=0.1)

last_press_time = 0
debounce_time = 0.3

def button_callback():
    global last_press_time
    current_time = time.time()
    if current_time - last_press_time > debounce_time:
        print(json.dumps({"method": "buttonPressed"}))
        sys.stdout.flush()
        last_press_time = current_time

button.when_pressed = button_callback

print(json.dumps({"method": "ready"}))
sys.stdout.flush()

try:
    pause()
except KeyboardInterrupt:
    print(json.dumps({"method": "terminated"}))
    sys.stdout.flush()
