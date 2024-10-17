import sys
import json
import evdev
from evdev import categorize, ecodes

def find_scanner():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    for device in devices:
        if "Opticon" in device.name:
            return device
    return None

def main():
    scanner = find_scanner()
    if not scanner:
        print(json.dumps({"method": "error", "message": "Barcode scanner not found"}))
        sys.stdout.flush()
        return

    print(json.dumps({"method": "ready"}))
    sys.stdout.flush()

    scanned_code = ""
    for event in scanner.read_loop():
        if event.type == ecodes.EV_KEY and event.value == 1:  # Key down event
            key_event = categorize(event)
            if key_event.keycode == "KEY_ENTER":
                print(json.dumps({"method": "scanned", "barcode": scanned_code}))
                sys.stdout.flush()
                scanned_code = ""
            elif key_event.keycode.startswith("KEY_"):
                char = key_event.keycode.split("_")[1]
                if len(char) == 1:
                    scanned_code += char
                elif char.isdigit():
                    scanned_code += char

if __name__ == "__main__":
    main()
