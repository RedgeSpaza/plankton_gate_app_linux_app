import sys
import json
import time
import subprocess
import psutil
import requests

def get_cpu_temperature():
    try:
        temp = psutil.sensors_temperatures()['cpu_thermal'][0].current
        return round(temp, 1)
    except:
        return None

def check_internet():
    try:
        requests.get("http://www.google.com", timeout=3)
        return True
    except requests.ConnectionError:
        return False

def get_memory_usage():
    memory = psutil.virtual_memory()
    return {
        "total": memory.total,
        "available": memory.available,
        "percent": memory.percent
    }

def get_cpu_usage():
    return psutil.cpu_percent(interval=1)

def get_disk_usage():
    disk = psutil.disk_usage('/')
    return {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent
    }

def get_ip_address():
    try:
        ip = subprocess.check_output(['hostname', '-I']).decode('utf-8').strip()
        return ip
    except:
        return None

def main():
    print(json.dumps({"method": "ready"}))
    sys.stdout.flush()

    while True:
        stats = {
            "method": "stats",
            "connectedToInternet": check_internet(),
            "temperature": get_cpu_temperature(),
            "memoryUsage": get_memory_usage(),
            "cpuUsage": get_cpu_usage(),
            "diskUsage": get_disk_usage(),
            "ipAddress": get_ip_address()
        }
        print(json.dumps(stats))
        sys.stdout.flush()
        time.sleep(1)  # Update every second

if __name__ == "__main__":
    main()
