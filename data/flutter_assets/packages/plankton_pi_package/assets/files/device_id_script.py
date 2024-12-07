import re
import uuid
import json
import sys

def get_cpu_serial():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    return line.split(':')[-1].strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading CPU serial: {e}", file=sys.stderr)
        return None

def get_mac_address():
    try:
        with open('/sys/class/net/eth0/address', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading MAC address: {e}", file=sys.stderr)
        return None

def generate_device_id():
    cpu_serial = get_cpu_serial()
    mac_address = get_mac_address()

    if cpu_serial:
        return f"RPI-{cpu_serial}"
    elif mac_address:
        return f"RPI-{mac_address.replace(':', '')}"
    else:
        # Fallback to a random UUID if no hardware-specific info is available
        return f"RPI-{str(uuid.uuid4())[:8]}"

if __name__ == "__main__":
    device_id = generate_device_id()
    print(json.dumps({"method": "device_id", "id": device_id}))
    sys.stdout.flush()
