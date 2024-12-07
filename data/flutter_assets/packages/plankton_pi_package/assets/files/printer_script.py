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
import textwrap

# Define the cache file path
CACHE_FILE = os.path.expanduser('~/plankton-logs/printer_cache.json')

log_dir = os.path.expanduser('~/plankton_logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, 'Print.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True  # Ensure logging is configured properly
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
        self.cache = self.load_cache()
        self.initialize_device()

    def load_cache(self):
        """Load the cache file if it exists"""
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                    logging.debug("Cache loaded successfully.")
                    return cache
        except Exception as e:
            logging.warning(f"Failed to load cache: {e}")
        return {}

    def save_cache(self):
        """Save the cache file"""
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self.cache, f)
            logging.debug("Cache saved successfully.")
        except Exception as e:
            logging.warning(f"Failed to save cache: {e}")

    def initialize_device(self):
        logging.debug("Starting printer initialization.")
        print("Initializing printer...", file=sys.stderr)
        for attempt in range(self.max_retries):
            logging.debug(f"Attempt {attempt + 1} to initialize the printer.")
            print(f"Attempt {attempt + 1} to initialize the printer.", file=sys.stderr)
            try:
                self.device = self.find_device()
                if self.device:
                    self.ep_out = self.find_endpoint()
                    if self.ep_out:
                        logging.info("Printer initialized successfully.")
                        print("Printer initialized successfully.", file=sys.stderr)
                        self.cache['initialized'] = True
                        self.save_cache()
                        return
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed: {str(e)}")
                logging.exception(e)
                print(f"Attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(self.retry_delay)
        logging.error("Failed to initialize printer after multiple attempts.")
        print("Failed to initialize printer after multiple attempts.", file=sys.stderr)
        self.cache['initialized'] = False
        self.save_cache()
        raise Exception("Printer initialization failed")

    def find_device(self):
        logging.debug(f"Searching for device with Vendor ID: {hex(self.vendor_id)}, Product ID: {hex(self.product_id)}")
        device = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if device is None:
            logging.error("Printer not found. Listing all connected USB devices:")
            devices = usb.core.find(find_all=True)
            for dev in devices:
                logging.error(f"Device: idVendor={hex(dev.idVendor)}, idProduct={hex(dev.idProduct)}")
            raise ValueError("Printer not found")
        logging.debug(f"Printer found: idVendor={hex(device.idVendor)}, idProduct={hex(device.idProduct)}")
        try:
            # Detach kernel drivers
            for cfg in device:
                for intf in cfg:
                    if device.is_kernel_driver_active(intf.bInterfaceNumber):
                        try:
                            device.detach_kernel_driver(intf.bInterfaceNumber)
                            logging.debug(f"Kernel driver detached from interface {intf.bInterfaceNumber}")
                        except usb.core.USBError as e:
                            logging.error(f"Could not detach kernel driver from interface {intf.bInterfaceNumber}: {e}")
                            raise
            # Set configuration
            device.set_configuration()
            usb.util.claim_interface(device, 0)
        except usb.core.USBError as e:
            logging.error(f"USBError during device setup: {e}")
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
            if e.errno == 19:
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

def send_in_chunks(printer, data, chunk_size=1024):
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
        font_width = command.get('fontWidth', 1)
        font_height = command.get('fontHeight', 1)
        font_type = command.get('fontType', 'A')
        align = command.get('align', 'left')
        bold = command.get('bold', False)
        underline = command.get('underline', False)

        # Calculate max line length based on font_width
        # Assume default font allows 48 characters per line
        max_line_length = 64 // font_width

        if not (1 <= font_width <= 8) or not (1 <= font_height <= 8):
            raise ValueError("fontWidth and fontHeight must be between 1 and 8")

        printer.write(b'\x1B\x40')  # Initialize printer
        alignments = {'left': 0, 'center': 1, 'right': 2}
        printer.write(b'\x1B\x61' + bytes([alignments.get(align, 0)]))  # Alignment
        printer.write(b'\x1B\x45' + bytes([1 if bold else 0]))  # Bold
        printer.write(b'\x1B\x2D' + bytes([1 if underline else 0]))  # Underline

        if font_type.upper() == 'B':
            printer.write(b'\x1B\x4D\x01')  # Font B
        else:
            printer.write(b'\x1B\x4D\x00')  # Font A

        size_byte = ((font_width - 1) << 4) | (font_height - 1)
        printer.write(b'\x1D\x21' + bytes([size_byte]))  # Character size

        # Wrap the text
        wrapped_lines = textwrap.wrap(text, width=max_line_length)

        for line in wrapped_lines:
            data = line.encode('gb18030', 'replace') + b'\n'
            send_in_chunks(printer, data, chunk_size=1024)

        printer.write(b'\x1B\x40')  # Reset printer settings

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

        # Resize image to maximum width if necessary
        max_width_pixels = 576  # Adjust based on printer's specs
        if image.width > max_width_pixels:
            ratio = max_width_pixels / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width_pixels, new_height), Image.ANTIALIAS)

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
        printer.write(b'\n')
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
            b'\x1D\x28\x6B\x03\x00\x31\x43' + bytes([size]),  # Set QR code size
            b'\x1D\x28\x6B\x03\x00\x31\x45\x30',  # Set error correction level
        ]

        # Store the QR code data
        qr_data_bytes = qr_data.encode('utf-8')
        data_length = len(qr_data_bytes) + 3
        pL = data_length % 256
        pH = data_length // 256
        commands.append(b'\x1D\x28\x6B' + bytes([pL, pH]) + b'\x31\x50\x30' + qr_data_bytes)
        # Print the QR code
        commands.append(b'\x1D\x28\x6B\x03\x00\x31\x51\x30')

        for cmd in commands:
            printer.write(cmd)
        printer.write(b'\n')
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
        print("Starting main function", file=sys.stderr)
        logging.debug("Starting main function.")
        printer = Printer(VENDOR_ID, PRODUCT_ID)
        print("Printer initialized", file=sys.stderr)
        logging.info("Entering main loop to process commands.")
        try:
            sys.stdout.write(json.dumps({"status": "ready"}) + '\n')
            sys.stdout.flush()
        except BrokenPipeError as e:
            logging.error(f"BrokenPipeError when writing to stdout: {e}")
            return  # Exit if stdout is not available
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    logging.info("EOF reached on stdin. Exiting.")
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
                    try:
                        sys.stdout.write(json.dumps({"status": "success"}) + '\n')
                        sys.stdout.flush()
                    except BrokenPipeError as e:
                        logging.error(f"BrokenPipeError when writing to stdout: {e}")
                        break
                except Exception as e:
                    logging.error(f"Command execution error: {e}")
                    logging.exception(e)
                    try:
                        sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
                        sys.stdout.flush()
                    except BrokenPipeError as e:
                        logging.error(f"BrokenPipeError when writing to stdout: {e}")
                        break
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                logging.exception(e)
                # Optionally, send error back to Dart
                try:
                    sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
                    sys.stdout.flush()
                except BrokenPipeError as e:
                    logging.error(f"BrokenPipeError when writing to stdout: {e}")
                    break
    except Exception as e:
        print(f"Exception occurred in main: {e}", file=sys.stderr)
        logging.error(f"Failed to initialize printer: {e}")
        logging.exception(e)
        try:
            sys.stdout.write(json.dumps({"status": "error", "message": str(e)}) + '\n')
            sys.stdout.flush()
        except BrokenPipeError as e:
            logging.error(f"BrokenPipeError when writing to stdout during initialization: {e}")
            pass
    finally:
        logging.info("Shutting down logging.")
        logging.shutdown()

if __name__ == '__main__':
    main()
