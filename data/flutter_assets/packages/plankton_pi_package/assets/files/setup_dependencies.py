import subprocess
import sys
import time
import os

def check_system_package(package):
    try:
        subprocess.check_call(['dpkg', '-s', package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"System package {package} is installed.")
        return True
    except subprocess.CalledProcessError:
        print(f"System package {package} is not installed.")
        return False

def install_system_package(package):
    print(f"Attempting to install system package: {package}")
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            subprocess.check_call(['sudo', 'apt-get', 'update'])
            subprocess.check_call(['sudo', 'apt-get', 'install', '-y', package])
            print(f"Successfully installed {package}.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Attempt {attempt + 1} failed to install {package}: {e}")
            if attempt < max_attempts - 1:
                print("Waiting 10 seconds before retrying...")
                time.sleep(10)
            else:
                print(f"Failed to install system package: {package} after {max_attempts} attempts.")
                return False

def create_udev_rule():
    vendor_id = '4b43'
    product_id = '3830'
    rule_content = f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vendor_id}", ATTR{{idProduct}}=="{product_id}", MODE="0666", GROUP="plugdev"'
    rule_file = '/etc/udev/rules.d/99-usb.rules'

    print("Attempting to create udev rule for the printer...")

    try:
        # Use sudo to write the udev rule
        echo_command = f'echo \'{rule_content}\' | sudo tee {rule_file}'
        subprocess.check_call(echo_command, shell=True)
        print(f"Created udev rule in {rule_file}.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to create udev rule: {e}")
        return False

    # Reload udev rules
    try:
        subprocess.check_call(['sudo', 'udevadm', 'control', '--reload'])
        subprocess.check_call(['sudo', 'udevadm', 'trigger'])
        print("Reloaded udev rules.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to reload udev rules: {e}")
        return False

    # Add current user to 'plugdev' group
    current_user = os.environ.get('SUDO_USER') or os.environ.get('USER')
    if current_user:
        try:
            subprocess.check_call(['sudo', 'usermod', '-aG', 'plugdev', current_user])
            print(f"Added user '{current_user}' to 'plugdev' group.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to add user to plugdev group: {e}")
            return False
    else:
        print("Could not determine current user to add to 'plugdev' group.")
        return False

    return True

def main():
    packages = [
        'python3-evdev',
        'python3-usb',
        'python3-pil',
    ]

    all_installed = True
    manual_install_required = []

    for package in packages:
        if not check_system_package(package):
            if not install_system_package(package):
                all_installed = False
                manual_install_required.append(package)

    if all_installed:
        print("All dependencies are installed or available system-wide.")
    else:
        print("Some dependencies could not be installed automatically.")
        print("Please install the following packages manually:")
        for package in manual_install_required:
            print(f"sudo apt-get install {package}")
        sys.exit(1)

    # Create udev rule
    if create_udev_rule():
        print("Printer permissions have been set up successfully.")
        print("Please unplug and replug your printer for the changes to take effect.")
        sys.exit(0)
    else:
        print("Failed to set up printer permissions.")
        print("Please ensure you have sufficient permissions or run this script with sudo.")
        sys.exit(1)

if __name__ == "__main__":
    main()
