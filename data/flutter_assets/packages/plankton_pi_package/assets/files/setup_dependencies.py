#!/usr/bin/env python3
import subprocess
import sys
import time
import os
import shutil
from pathlib import Path

class DependencyInstaller:
    def __init__(self):
        self.package_map = {
            'python3-evdev': 'apt',
            'python3-usb': 'apt',
            'python3-pil': 'apt',
            'nodejs': 'apt',
            'npm': 'apt',
            'firebase-admin': 'special'
        }
        self.max_attempts = 3
        self.manual_install_required = []

    def clean_apt_locks(self):
        """Clean up APT locks and corrupted states."""
        print("\nCleaning up package manager locks...")
        try:
            # Kill any running package manager processes
            subprocess.run(['sudo', 'killall', 'apt-get'], stderr=subprocess.DEVNULL)
            subprocess.run(['sudo', 'killall', 'dpkg'], stderr=subprocess.DEVNULL)
            subprocess.run(['sudo', 'killall', 'packagekitd'], stderr=subprocess.DEVNULL)

            # Remove lock files
            lock_files = [
                '/var/lib/apt/lists/lock',
                '/var/cache/apt/archives/lock',
                '/var/lib/dpkg/lock*'
            ]

            for lock_file in lock_files:
                try:
                    subprocess.run(['sudo', 'rm', '-f', lock_file], check=False)
                except Exception:
                    pass

            # Clean and update package cache
            subprocess.run(['sudo', 'apt-get', 'clean'], check=False)
            subprocess.run(['sudo', 'rm', '-rf', '/var/lib/apt/lists/*'], check=False)
            subprocess.run(['sudo', 'apt-get', 'update', '--fix-missing'], check=False)

            print("Package manager locks cleaned")
            return True
        except Exception as e:
            print(f"Warning: Error while cleaning locks: {e}")
            return False

    def install_firebase_admin(self):
        """Special handling for firebase-admin installation."""
        print("\nAttempting to install firebase-admin globally...")
        try:
            # Clean locks first
            self.clean_apt_locks()

            # Ensure pip is installed
            subprocess.check_call(['sudo', 'apt-get', 'install', '-y', 'python3-pip'])

            # Install firebase-admin
            subprocess.check_call(['sudo', 'pip3', 'install', 'firebase-admin', '--break-system-packages'])
            print("Successfully installed firebase-admin globally")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install firebase-admin: {e}")
            print("Please try installing manually with: sudo pip3 install firebase-admin --break-system-packages")
            return False

    def check_system_package(self, package):
        """Check if a package is installed."""
        try:
            if self.package_map[package] == 'special':
                # Check for firebase-admin using pip
                result = subprocess.run(['pip3', 'show', 'firebase-admin'],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                installed = result.returncode == 0
            else:
                result = subprocess.run(['dpkg', '-s', package],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                installed = result.returncode == 0

            print(f"Package {package} is {'installed' if installed else 'not installed'}.")
            return installed
        except Exception as e:
            print(f"Error checking package {package}: {e}")
            return False

    def install_package(self, package):
        """Install a package using the appropriate method."""
        print(f"\nAttempting to install package: {package}")

        # Clean locks before installation
        self.clean_apt_locks()

        if self.package_map[package] == 'special':
            return self.install_firebase_admin()
        else:
            for attempt in range(self.max_attempts):
                try:
                    subprocess.check_call(['sudo', 'apt-get', 'update', '-y'])
                    subprocess.check_call(['sudo', 'apt-get', 'install', '-y', package])
                    print(f"Successfully installed {package} via apt.")
                    return True
                except subprocess.CalledProcessError as e:
                    print(f"Attempt {attempt + 1} failed to install {package}: {e}")
                    if attempt < self.max_attempts - 1:
                        print("Waiting 10 seconds before retrying...")
                        time.sleep(10)
                        self.clean_apt_locks()  # Clean locks before retry
            return False

    def create_udev_rule(self):
        """Create udev rule for USB printer access."""
        vendor_id = '4b43'
        product_id = '3830'
        rule_content = f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vendor_id}", ATTR{{idProduct}}=="{product_id}", MODE="0666", GROUP="plugdev"'
        rule_file = '/etc/udev/rules.d/99-usb.rules'

        print("\nSetting up printer permissions...")
        print("Creating udev rule for the printer...")

        try:
            echo_command = f'echo \'{rule_content}\' | sudo tee {rule_file} > /dev/null'
            subprocess.check_call(echo_command, shell=True)
            print(f"Created udev rule in {rule_file}")

            subprocess.check_call(['sudo', 'udevadm', 'control', '--reload'])
            subprocess.check_call(['sudo', 'udevadm', 'trigger'])
            print("Reloaded udev rules")

            current_user = os.environ.get('SUDO_USER') or os.environ.get('USER')
            if current_user:
                subprocess.check_call(['sudo', 'usermod', '-aG', 'plugdev', current_user])
                print(f"Added user '{current_user}' to plugdev group")
            else:
                print("Warning: Could not determine current user")
                return False

            return True
        except subprocess.CalledProcessError as e:
            print(f"Error setting up printer permissions: {e}")
            return False

    def setup(self):
        """Main setup procedure."""
        print("Starting dependency installation...")

        # Clean locks before starting
        self.clean_apt_locks()

        all_installed = True
        for package in self.package_map.keys():
            if not self.check_system_package(package):
                if not self.install_package(package):
                    all_installed = False
                    self.manual_install_required.append(package)

        if all_installed:
            print("\nAll dependencies were installed successfully.")
        else:
            print("\nSome dependencies could not be installed automatically.")
            print("Please install the following packages manually:")
            for package in self.manual_install_required:
                if package == 'firebase-admin':
                    print("sudo pip3 install firebase-admin --break-system-packages")
                else:
                    print(f"sudo apt-get install {package}")
            sys.exit(1)

        if self.create_udev_rule():
            print("\nPrinter permissions have been set up successfully.")
            print("Please unplug and replug your printer for the changes to take effect.")
        else:
            print("\nFailed to set up printer permissions.")
            sys.exit(1)

        print("\nSetup completed successfully!")

if __name__ == "__main__":
    try:
        installer = DependencyInstaller()
        installer.setup()
    except KeyboardInterrupt:
        print("\nSetup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during setup: {e}")
        sys.exit(1)
