import sys
import os
import json
import time
import logging
import subprocess
from pathlib import Path

CACHE_FILE = os.path.expanduser('~/plankton-logs/init_cache.json')
CACHE_VERSION = "1.0"  # Increment this when making changes to cache logic

def print_json(data):
    """Helper to print JSON and flush stdout"""
    print(json.dumps(data))
    sys.stdout.flush()

def load_cache():
    """Load the cache file if it exists"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                if cache.get('version') == CACHE_VERSION:
                    return cache
    except Exception:
        pass
    return {'version': CACHE_VERSION, 'udev_rules': False, 'pyusb_installed': False}

def save_cache(cache):
    """Save the cache file"""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception as e:
        logging.warning(f"Failed to save cache: {e}")

def check_root_privileges():
    """Check if the script is run with root privileges"""
    if os.geteuid() != 0:
        print_json({
            "status": "error",
            "message": "This script must be run as root. Please use 'sudo' to run it."
        })
        sys.exit(1)

def setup_udev_rules(cache):
    """Set up udev rules to allow USB device access without root privileges"""
    if cache.get('udev_rules'):
        print_json({"status": "progress", "message": "Using cached udev rules"})
        return True

    udev_rule = 'SUBSYSTEM=="usb", ATTRS{idVendor}=="4b43", ATTRS{idProduct}=="3830", MODE="0666"'
    rules_file = "/etc/udev/rules.d/99-printer.rules"

    try:
        if os.path.exists(rules_file):
            cache['udev_rules'] = True
            save_cache(cache)
            print_json({"status": "progress", "message": "udev rules already set"})
            return True

        print_json({"status": "progress", "message": "Setting up udev rules for USB access"})
        with open(rules_file, "w") as f:
            f.write(udev_rule)

        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger"], check=True)

        cache['udev_rules'] = True
        save_cache(cache)
        print_json({"status": "success", "message": "udev rules set for USB access"})
        return True
    except Exception as e:
        print_json({"status": "error", "message": f"Failed to set up udev rules: {str(e)}"})
        return False

def ensure_pyusb_installed(cache):
    """Ensure pyusb is installed system-wide using apt"""
    if cache.get('pyusb_installed'):
        print_json({"status": "progress", "message": "Using cached pyusb installation"})
        return True

    try:
        import usb.core
        import usb.util
        cache['pyusb_installed'] = True
        save_cache(cache)
        return True
    except ModuleNotFoundError:
        print_json({"status": "progress", "message": "Installing pyusb globally..."})
        try:
            result = subprocess.run(
                ["apt-get", "install", "-y", "python3-usb"],
                check=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                cache['pyusb_installed'] = True
                save_cache(cache)
                print_json({"status": "success", "message": "pyusb installed successfully"})
                return True
            return False
        except subprocess.CalledProcessError as e:
            print_json({"status": "error", "message": f"Failed to install pyusb: {str(e)}"})
            return False

class PrinterInitializer:
    def __init__(self):
        # Load cache
        self.cache = load_cache()

        # Check for root privileges before proceeding
        check_root_privileges()

        # Run udev setup function to ensure USB access permissions
        if not setup_udev_rules(self.cache):
            sys.exit(1)

        # Ensure pyusb is installed before any further code executes
        if not ensure_pyusb_installed(self.cache):
            sys.exit(1)

        # Now safely import usb after installation check
        import usb.core
        import usb.util
        self.usb = usb

        self.VENDOR_ID = 0x4b43
        self.PRODUCT_ID = 0x3830
        self.MAX_RETRIES = 3
        self.RETRY_DELAY = 2
        self.setup_logging()

    def setup_logging(self):
        """Configure logging"""
        try:
            log_dir = os.path.expanduser('~/plankton_logs')
            os.makedirs(log_dir, exist_ok=True)

            logging.basicConfig(
                filename=os.path.join(log_dir, 'printer_init.log'),
                level=logging.DEBUG,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )
            logging.info("Starting printer initialization")
        except Exception as e:
            print_json({"status": "error", "message": f"Failed to setup logging: {str(e)}"})

    def kill_competing_processes(self):
        """Kill any processes that might be using the printer"""
        try:
            subprocess.run("sudo lsof /dev/usb/lp* 2>/dev/null | awk '{print $2}' | grep -v PID | xargs -r kill -9",
                           shell=True, stderr=subprocess.DEVNULL)
            subprocess.run("sudo lsof /dev/bus/usb/*/* 2>/dev/null | grep USB | awk '{print $2}' | xargs -r kill -9",
                           shell=True, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            return True
        except Exception as e:
            logging.error(f"Error killing competing processes: {e}")
            return False

    def release_kernel_driver(self, device):
        """Release kernel driver if active"""
        try:
            for cfg in device:
                for intf in range(cfg.bNumInterfaces):
                    if device.is_kernel_driver_active(intf):
                        try:
                            device.detach_kernel_driver(intf)
                            logging.info(f"Detached kernel driver from interface {intf}")
                        except self.usb.core.USBError as e:
                            sys.exit(f"Could not detach kernel driver from interface({intf}): {e}")
            return True
        except Exception as e:
            logging.error(f"Error releasing kernel driver: {e}")
            return False

    def reset_device(self, device):
        """Reset USB device"""
        try:
            device.reset()
            time.sleep(0.5)
            return True
        except Exception as e:
            logging.error(f"Error resetting device: {e}")
            return False

    def find_printer(self):
        """Locate the printer device"""
        try:
            device = self.usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.PRODUCT_ID)

            if device is None:
                logging.warning("Printer not found")
                print_json({"status": "error", "message": "Printer not found. Please check connection."})
                return None

            logging.info(f"Found printer: {device}")
            return device

        except Exception as e:
            error_msg = f"Error finding printer: {str(e)}"
            logging.error(error_msg)
            print_json({"status": "error", "message": error_msg})
            return None

    def configure_printer(self, device):
        """Configure the printer device"""
        try:
            self.reset_device(device)
            self.kill_competing_processes()
            self.release_kernel_driver(device)

            try:
                device.set_configuration()
            except self.usb.core.USBError as e:
                if e.errno == 16:  # Resource busy
                    logging.warning("Resource busy, attempting to free...")
                    self.kill_competing_processes()
                    time.sleep(1)
                    device.set_configuration()
                else:
                    raise

            # Get configuration
            cfg = device.get_active_configuration()
            if not cfg:
                raise Exception("Could not get active configuration")

            # Get interface
            intf = cfg[(0,0)]
            if not intf:
                raise Exception("Could not get interface")

            # Find output endpoint
            ep_out = self.usb.util.find_descriptor(
                intf,
                custom_match=lambda e:
                self.usb.util.endpoint_direction(e.bEndpointAddress) ==
                self.usb.util.ENDPOINT_OUT
            )

            if not ep_out:
                raise Exception("Could not find output endpoint")

            # Claim interface
            self.usb.util.claim_interface(device, intf)

            # Store endpoints for later use
            device._ep_out = ep_out
            device._intf = intf

            logging.info("Printer configured successfully")
            print_json({"status": "success", "message": "Printer configured successfully"})
            return True

        except self.usb.core.USBError as e:
            if e.errno == 13:
                error_msg = "Permission denied. Please check device permissions."
            else:
                error_msg = f"USB Error: {str(e)}"
            logging.error(error_msg)
            print_json({"status": "error", "message": error_msg})
            return False

        except Exception as e:
            error_msg = f"Error configuring printer: {str(e)}"
            logging.error(error_msg)
            print_json({"status": "error", "message": error_msg})
            return False

    def initialize_printer(self):
        """Main printer initialization procedure"""
        attempt = 0
        while attempt < self.MAX_RETRIES:
            try:
                logging.info(f"Initialization attempt {attempt + 1}")
                print_json({
                    "status": "progress",
                    "message": f"Attempting printer initialization (attempt {attempt + 1}/{self.MAX_RETRIES})"
                })

                self.kill_competing_processes()

                device = self.find_printer()
                if device is None:
                    attempt += 1
                    continue

                if not self.configure_printer(device):
                    attempt += 1
                    continue

                print_json({"status": "success", "message": "Printer initialized successfully"})
                logging.info("Printer initialization completed successfully")
                return True

            except Exception as e:
                logging.error(f"Error during initialization attempt {attempt + 1}: {e}")
                print_json({"status": "error", "message": str(e)})

            attempt += 1
            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        logging.error("Printer initialization failed after all attempts")
        print_json({
            "status": "error",
            "message": f"Printer initialization failed after {self.MAX_RETRIES} attempts"
        })
        return False

def main():
    try:
        initializer = PrinterInitializer()
        success = initializer.initialize_printer()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_json({"status": "error", "message": "Initialization interrupted by user"})
        sys.exit(1)
    except Exception as e:
        print_json({"status": "error", "message": f"Unexpected error: {str(e)}"})
        sys.exit(1)

if __name__ == "__main__":
    main()
