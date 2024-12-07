import sys
import time
import json
from gpiozero import Buzzer

def main():
    buzzer_pin = 16
    buzzer = Buzzer(buzzer_pin)
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
            buzzer.on()
            time.sleep(duration)
            buzzer.off()
            print(json.dumps({"method": "buzzComplete"}))
        except ValueError:
            print(json.dumps({"method": "error", "message": "Invalid duration"}))
    else:
        print(json.dumps({"method": "error", "message": "No duration provided"}))
    sys.stdout.flush()

if __name__ == "__main__":
    main()
