import sys
import json
import logging
import usb.core
import usb.util
import base64
from PIL import Image, ImageOps
from io import BytesIO
import time
import os
import traceback

log_dir = os.path.expanduser('~/plankton_logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, 'Print.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

VENDOR_ID = 0x4b43
PRODUCT_ID = 0x3830

class Printer:
    def __init__(self, vendor_id, product_id, max_retries=5, retry_delay=2):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.device = None
        self.ep_out = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.initialize_device()

    def initialize_device(self):
        logging.debug("Starting printer initialization.")
        for attempt in range(self.max_retries):
            logging.debug(f"Attempt {attempt + 1} to initialize the printer.")
            try:
                self.device = self.find_device()
                if self.device:
                    self.ep_out = self.find_endpoint()
                    if self.ep_out:
                        logging.info("Printer initialized successfully.")
                        return
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed: {str(e)}")
                logging.exception(e)

            time.sleep(self.retry_delay)

        logging.error("Failed to initialize printer after multiple attempts.")
        raise Exception("Printer initialization failed")

    def find_device(self):
        logging.debug(f"Searching for device with Vendor ID: {hex(self.vendor_id)}, Product ID: {hex(self.product_id)}")
        device = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if device is None:
            logging.error("Printer not found. Listing all connected USB devices:")
            # List all connected USB devices
            devices = usb.core.find(find_all=True)
            for dev in devices:
                logging.error(f"Device: idVendor={hex(dev.idVendor)}, idProduct={hex(dev.idProduct)}")
            raise ValueError("Printer not found")
        logging.debug(f"Printer found: idVendor={hex(device.idVendor)}, idProduct={hex(device.idProduct)}")
        try:
            if device.is_kernel_driver_active(0):
                logging.debug("Kernel driver is active. Detaching kernel driver.")
                device.detach_kernel_driver(0)
            else:
                logging.debug("No kernel driver active.")
        except usb.core.USBError as e:
            logging.error(f"Could not detach kernel driver: {e}")
            logging.exception(e)
            raise

        try:
            logging.debug("Setting device configuration.")
            device.set_configuration()
        except usb.core.USBError as e:
            logging.error(f"Failed to set device configuration: {e}")
            logging.exception(e)
            raise
        return device

    def find_endpoint(self):
        logging.debug("Finding the output endpoint.")
        cfg = self.device.get_active_configuration()
        logging.debug(f"Active configuration: {cfg}")
        intf = usb.util.find_descriptor(
            cfg,
            bInterfaceNumber=0,
            bAlternateSetting=0
        )
        logging.debug(f"Interface: {intf}")
        if intf is None:
            logging.error("Interface not found.")
            raise ValueError("Interface not found")

        endpoints = [ep.bEndpointAddress for ep in intf]
        logging.debug(f"Endpoints available: {endpoints}")

        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        if ep_out is None:
            logging.error("Output endpoint not found.")
            raise ValueError("Endpoint not found")
        logging.debug(f"Output endpoint: {ep_out}")
        return ep_out

    def write(self, data):
        if not self.ep_out:
            raise ValueError("Printer not properly initialized")
        try:
            self.ep_out.write(data)
        except usb.core.USBError as e:
            if e.errno == 19:  # No such device
                logging.error("Device disconnected. Attempting to reconnect.")
                self.initialize_device()
                if self.ep_out:
                    self.ep_out.write(data)
                else:
                    raise Exception("Failed to reinitialize device")
            else:
                logging.error(f"USBError during write: {e}")
                logging.exception(e)
                raise

def send_in_chunks(printer, data, chunk_size=4096):
    try:
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            printer.write(chunk)
    except usb.core.USBError as e:
        logging.error(f"USB Error during data transmission: {e}")
        logging.exception(e)
        raise

def print_text(printer, command):
    try:
        text = command.get('text', '')
        font_size = command.get('fontSize', 0)
        align = command.get('align', 'left')
        bold = command.get('bold', False)
        underline = command.get('underline', False)
        commands = [b'\x1B\x40']
        alignments = {'left': 0, 'center': 1, 'right': 2}
        commands.append(b'\x1B\x61' + bytes([alignments.get(align, 0)]))
        commands.append(b'\x1B\x45' + bytes([1 if bold else 0]))
        commands.append(b'\x1B\x2D' + bytes([1 if underline else 0]))
        if font_size == 2:
            commands.append(b'\x1D\x21\x11')
        elif font_size == 1:
            commands.append(b'\x1D\x21\x01')
        else:
            commands.append(b'\x1D\x21\x00')
        commands.append(text.encode('cp437', 'replace') + b'\n')
        commands.append(b'\x1B\x40')
        for cmd in commands:
            printer.write(cmd)
    except Exception as e:
        logging.error(f"Error printing text: {e}")
        logging.exception(e)
        raise

def print_image(printer, command):
    try:
        image_data_base64 = command.get('image', '')
        width = command.get('width', None)
        height = command.get('height', None)
        align = command.get('align', 'center')
        if not image_data_base64:
            raise ValueError("No image data provided")
        image_data = base64.b64decode(image_data_base64)
        image = Image.open(BytesIO(image_data)).convert('L')
        if width and height:
            image = image.resize((width, height))
        image = ImageOps.invert(image)
        image = image.convert('1')
        image_width = image.width
        image_height = image.height
        image_width_bytes = (image_width + 7) // 8
        image_data_bytes = bytearray()
        for y in range(image_height):
            for x in range(0, image_width, 8):
                byte = 0
                for bit in range(8):
                    if x + bit < image_width:
                        pixel = image.getpixel((x + bit, y))
                        if pixel == 0:
                            byte |= 1 << (7 - bit)
                image_data_bytes.append(byte)
        alignments = {'left': 0, 'center': 1, 'right': 2}
        alignment_cmd = b'\x1B\x61' + bytes([alignments.get(align, 1)])
        commands = [
            b'\x1B\x40',
            alignment_cmd,
            b'\x1D\x76\x30\x00',
            image_width_bytes.to_bytes(2, 'little'),
            image_height.to_bytes(2, 'little'),
        ]
        for cmd in commands:
            printer.write(cmd)
        send_in_chunks(printer, image_data_bytes)
    except Exception as e:
        logging.error(f"Error printing image: {e}")
        logging.exception(e)
        raise

def print_qr_code(printer, command):
    try:
        qr_data = command.get('qr', '')
        size = command.get('size', 4)
        align = command.get('align', 'center')
        if not qr_data:
            raise ValueError("No QR data provided")
        alignments = {'left': 0, 'center': 1, 'right': 2}
        alignment_cmd = b'\x1B\x61' + bytes([alignments.get(align, 1)])
        commands = [
            b'\x1B\x40',
            alignment_cmd,
            b'\x1D\x28\x6B\x03\x00\x31\x43' + bytes([size]),
            b'\x1D\x28\x6B\x03\x00\x31\x45\x30',
            ]
        data_length = len(qr_data) + 3
        pL = data_length % 256
        pH = data_length // 256
        commands.append(b'\x1D\x28\x6B' + bytes([pL, pH]) + b'\x31\x50\x30' + qr_data.encode('utf-8'))
        commands.append(b'\x1D\x28\x6B\x03\x00\x31\x51\x30')
        for cmd in commands:
            printer.write(cmd)
    except Exception as e:
        logging.error(f"Error printing QR code: {e}")
        logging.exception(e)
        raise

def feed_paper(printer, command):
    try:
        space = command.get('space', 1)
        printer.write(b'\n' * space)
    except Exception as e:
        logging.error(f"Error feeding paper: {e}")
        logging.exception(e)
        raise

def cut_paper(printer):
    try:
        printer.write(b'\x1D\x56\x00')
    except Exception as e:
        logging.error(f"Error cutting paper: {e}")
        logging.exception(e)
        raise

def main():
    try:
        logging.debug("Starting main function.")
        printer = Printer(VENDOR_ID, PRODUCT_ID)
        sys.stdout.write(json.dumps({"status": "ready"}) + '\n')
        sys.stdout.flush()

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                command = json.loads(line)
                logging.debug(f"Received command: {command}")
                try:
                    if 'text' in command:
                        print_text(printer, command)
                    elif 'image' in command:
                        print_image(printer, command)
                    elif 'qr' in command:
                        print_qr_code(printer, command)
                    elif 'space' in command:
                        feed_paper(printer, command)
                    elif 'cut' in command and command['cut']:
                        cut_paper(printer)
                    else:
                        raise ValueError("Unknown command")
                    sys.stdout.write(json.dumps({"status": "success"}) + '\n')
                    sys.stdout.flush()
                except Exception as e:
                    logging.error(f"Command execution error: {e}")
                    logging.exception(e)
                    sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
                    sys.stdout.flush()
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                logging.exception(e)
                sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
                sys.stdout.flush()
    except Exception as e:
        logging.error(f"Failed to initialize printer: {e}")
        logging.exception(e)
        sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
        sys.stdout.flush()

if __name__ == "__main__":
    main()
