import sys
import json
import time
from gpiozero import OutputDevice

class RelayController:
    def __init__(self, relay_pins):
        self.relays = []
        for pin in relay_pins:
            self.relays.append(OutputDevice(pin, initial_value=True))

    def trigger_relays(self, channels):
        try:
            # Activate specified relays
            for idx, relay in enumerate(self.relays):
                if idx in channels:
                    relay.off()  # Relay is active low; off() activates it
                else:
                    relay.on()   # Deactivate other relays
            # Wait for 1 second
            time.sleep(1)
            # Reset all relays
            for relay in self.relays:
                relay.on()
            # Output success message
            print(json.dumps({'status': 'success', 'method': 'triggerComplete'}))
            sys.stdout.flush()
        except Exception as e:
            print(json.dumps({'status': 'error', 'message': str(e)}))
            sys.stdout.flush()

def main():
    # Initialize relay controller with GPIO pins (adjust pins as necessary)
    relay_pins = [26, 20, 21]  # GPIO pins connected to relays
    relay_controller = RelayController(relay_pins)

    # Read commands from stdin
    for line in sys.stdin:
        try:
            data = json.loads(line.strip())
            method = data.get('method')
            if method == 'trigger':
                channels = data.get('channels', [])
                relay_controller.trigger_relays(channels)
            else:
                # Unknown method
                print(json.dumps({'status': 'error', 'message': f'Unknown method {method}'}))
                sys.stdout.flush()
        except Exception as e:
            print(json.dumps({'status': 'error', 'message': str(e)}))
            sys.stdout.flush()

if __name__ == '__main__':
    main()
