import sys
import json
import time
import subprocess
import psutil
import requests
from ping3 import ping

cache = {
    "cpu_temperature": None,
    "internet_status": None,
    "memory_usage": None,
    "cpu_usage": None,
    "disk_usage": None,
    "ip_address": None
}

def get_cpu_temperature():
    try:
        temp = psutil.sensors_temperatures()['cpu_thermal'][0].current
        return round(temp, 1)
    except:
        return None

def check_internet():
    try:
        # First check: Ping Google's DNS with a retry
        for _ in range(3):  # Retry up to 3 times
            latency = ping('8.8.8.8', timeout=2)
            if latency is not None and latency < 1000:
                break  # Exit retry loop if successful
            time.sleep(1)  # Wait before retrying

        if latency is None or latency > 1000:
            return False

        # Second check: HTTP request (Only if ping was successful)
        start_time = time.time()
        response = requests.get("http://www.google.com", timeout=5)
        response_time = time.time() - start_time

        if response.status_code != 200 or response_time > 4:
            return False

        return True
    except (requests.ConnectionError, requests.Timeout):
        return False
    except Exception:
        return False


def get_memory_usage():
    memory = psutil.virtual_memory()
    return {
        "total": memory.total,
        "available": memory.available,
        "percent": memory.percent
    }

def get_cpu_usage():
    return psutil.cpu_percent(interval=0.5)

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

def update_cache():
    cache["cpu_temperature"] = get_cpu_temperature() or cache["cpu_temperature"]
    cache["internet_status"] = check_internet()
    cache["memory_usage"] = get_memory_usage() or cache["memory_usage"]
    cache["cpu_usage"] = get_cpu_usage() or cache["cpu_usage"]
    cache["disk_usage"] = get_disk_usage() or cache["disk_usage"]
    cache["ip_address"] = get_ip_address() or cache["ip_address"]

def main():
    print(json.dumps({"method": "ready"}))
    sys.stdout.flush()

    while True:
        update_cache()
        stats = {
            "method": "stats",
            "connectedToInternet": cache["internet_status"],
            "temperature": cache["cpu_temperature"],
            "memoryUsage": cache["memory_usage"],
            "cpuUsage": cache["cpu_usage"],
            "diskUsage": cache["disk_usage"],
            "ipAddress": cache["ip_address"]
        }
        print(json.dumps(stats))
        sys.stdout.flush()
        time.sleep(1)  # 500 ms interval

if __name__ == "__main__":
    main()
