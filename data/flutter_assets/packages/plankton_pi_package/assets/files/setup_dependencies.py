import subprocess
import sys
import time
import os
import json
import signal
from pathlib import Path
import importlib.util

def print_json(data):
    """Helper to print JSON and flush stdout"""
    print(json.dumps(data))
    sys.stdout.flush()

class DependencyInstaller:
    def __init__(self):
        self.apt_packages = [
            'python3-evdev',
            'python3-usb',
            'python3-pil',
            'python3-pip',
            'python3-full',
            'python3-setuptools',
            'libglib2.0-dev',
            'python3-dev'
        ]
        self.pip_packages = ['firebase-admin>=6.2.0', 'ping3']
        self.max_attempts = 5
        self.retry_delay = 2

    def run_command(self, command, check=True, retries=3):
        """Run a command with retries and proper error handling"""
        last_error = None
        for attempt in range(retries):
            try:
                result = subprocess.run(
                    command,
                    check=check,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 or not check:
                    return result
                last_error = f"Command failed (code {result.returncode}): {result.stderr}"
            except Exception as e:
                last_error = str(e)
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
            print_json({"status": "error", "message": last_error})
            if attempt < retries - 1:
                time.sleep(self.retry_delay)
                continue
            raise Exception(last_error)

    def is_apt_package_installed(self, package):
        """Check if an apt package is already installed"""
        result = self.run_command(['dpkg', '-s', package], check=False)
        return result.returncode == 0

    def is_pip_package_installed(self, package_name):
        """Check if a pip package is already installed"""
        package_spec = importlib.util.find_spec(package_name)
        return package_spec is not None

    def install_apt_package(self, package):
        """Install a single apt package with robust error handling"""
        if self.is_apt_package_installed(package):
            print_json({"status": "progress", "message": f"{package} is already installed. Skipping."})
            return True

        print_json({"status": "progress", "message": f"Installing {package}..."})
        try:
            # Remove '--no-install-recommends' to allow full installation
            cmd = ['sudo', 'apt-get', 'install', '-y', package]
            result = self.run_command(cmd, check=False)

            if result.returncode == 0:
                return True

            # Clean system and retry if installation fails
            self.clean_system()
            self.update_package_lists()

            # Try installing again without '--no-install-recommends'
            result = self.run_command(cmd, check=True)
            return True

        except Exception as e:
            print_json({"status": "error", "message": f"Failed to install {package}: {str(e)}"})
            return False

    def install_ping3(self):
        """Install ping3 using pip with system packages flag"""
        if self.is_pip_package_installed("ping3"):
            print_json({"status": "progress", "message": "ping3 is already installed. Skipping."})
            return True

        print_json({"status": "progress", "message": "Installing ping3..."})
        try:
            cmd = [
                'sudo', 'pip3',
                'install',
                '--break-system-packages',
                'ping3'
            ]
            self.run_command(cmd)
            return True
        except Exception as e:
            print_json({"status": "error", "message": f"Failed to install ping3: {str(e)}"})
            return False

    def install_firebase(self):
        """Install Firebase using pip with system packages flag"""
        if self.is_pip_package_installed("firebase_admin"):
            print_json({"status": "progress", "message": "firebase-admin is already installed. Skipping."})
            return True

        print_json({"status": "progress", "message": "Installing firebase-admin..."})
        try:
            cmd = [
                'sudo', 'pip3',
                'install',
                '--break-system-packages',
                'firebase-admin>=6.2.0'
            ]
            self.run_command(cmd)
            return True
        except Exception as e:
            print_json({"status": "error", "message": f"Failed to install firebase-admin: {str(e)}"})
            return False

    def update_package_lists(self):
        """Update package lists with error handling"""
        print_json({"status": "progress", "message": "Updating package lists..."})
        try:
            result = self.run_command(['sudo', 'apt-get', 'update'], check=False)
            if result.returncode == 0:
                return True

            # Clean system if initial update fails
            self.clean_system()
            result = self.run_command(['sudo', 'apt-get', 'update'], check=True)
            return True

        except Exception as e:
            print_json({"status": "error", "message": f"Failed to update package lists: {str(e)}"})
            return False

    def clean_system(self):
        """Clean the system state"""
        commands = [
            ['sudo', 'dpkg', '--configure', '-a'],
            ['sudo', 'apt-get', 'clean'],
            ['sudo', 'apt-get', 'autoremove', '-y'],
            ['sudo', 'apt-get', 'autoclean'],
            ['sudo', 'sync']
        ]
        for cmd in commands:
            try:
                self.run_command(cmd, check=False)
            except:
                continue

    def setup(self):
        """Main setup procedure"""
        try:
            print_json({"status": "progress", "message": "Starting setup..."})

            self.clean_system()

            if not self.update_package_lists():
                return False

            for package in self.apt_packages:
                if not self.install_apt_package(package):
                    print_json({"status": "warning", "message": f"Continuing despite failure to install {package}."})

            if not self.install_firebase():
                print_json({"status": "warning", "message": "Continuing despite failure to install firebase-admin."})

            if not self.install_ping3():
                print_json({"status": "warning", "message": "Continuing despite failure to install ping3."})

            print_json({"status": "success", "message": "Setup completed successfully"})
            return True

        except Exception as e:
            error_msg = str(e)
            print_json({"status": "error", "message": f"Setup failed: {error_msg}"})
            return False

def main():
    def signal_handler(signum, frame):
        print_json({"status": "error", "message": "Setup interrupted"})
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if os.geteuid() != 0:
            print_json({
                "status": "error",
                "message": "This script must be run with sudo privileges"
            })
            sys.exit(1)

        installer = DependencyInstaller()
        success = installer.setup()
        sys.exit(0 if success else 1)
    except Exception as e:
        print_json({"status": "error", "message": f"Unexpected error: {str(e)}"})
        sys.exit(1)

if __name__ == "__main__":
    main()
