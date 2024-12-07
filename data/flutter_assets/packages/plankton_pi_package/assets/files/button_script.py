from gpiozero import Button
from signal import pause
import sys
import json
import time

def print_json(data):
    """Helper to print JSON and flush"""
    print(json.dumps(data))
    sys.stdout.flush()

button = Button(18, pull_up=True, bounce_time=0.05)

last_press_time = 0
debounce_time = 0.3

def button_callback():
    global last_press_time
    current_time = time.time()
    if current_time - last_press_time > debounce_time:
        print_json({"method": "buttonPressed", "timestamp": current_time})
        last_press_time = current_time

# Add both pressed handlers
button.when_pressed = button_callback

print_json({"method": "ready"})

try:
    # Add heartbeat to verify script is running
    while True:
        time.sleep(5)
        # print_json({"method": "heartbeat"})
        sys.stdout.flush()
except KeyboardInterrupt:
    print_json({"method": "terminated"})
finally:
    button.close()
