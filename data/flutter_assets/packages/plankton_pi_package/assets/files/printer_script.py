import sys
import json
import logging
import usb.core
import usb.util
import base64
from PIL import Image, ImageOps, ImageEnhance
from io import BytesIO
import time
import os
import textwrap
import subprocess

# Printer configuration from manual
VENDOR_ID = 0x4b43  # Manual page 6
PRODUCT_ID = 0x3830  # Manual page 6
MAX_WIDTH = 576  # 72mm printable area * 8 dots/mm (203 DPI)
DOTS_PER_LINE = 384  # From manual specifications
MIN_DENSITY_CMD = b'\x1B\x37\x07\x50\x20'
LOCK_FILE = "/tmp/printer.lock"


def acquire_lock():
    """Acquire a lock file to ensure only one instance runs"""
    try:
        if os.path.exists(LOCK_FILE):
            # Check if the process holding the lock is still running
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Check if process is running
                return False  # Process is still running
            except OSError:
                # Process is not running, remove stale lock
                os.remove(LOCK_FILE)

        # Create new lock file
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        logging.error(f"Failed to acquire lock: {e}")
        return False


def release_lock():
    """Release the lock file"""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(LOCK_FILE)
    except Exception as e:
        logging.error(f"Failed to release lock: {e}")


class HSK33Printer:
    def __init__(self):
        self.device = None
        self.ep_out = None
        self._configure_logging()
        self._usb_cleanup()
        self._initialize()

    def _configure_logging(self):
        """Set up logging according to manual troubleshooting guidelines"""
        log_dir = os.path.expanduser('~/plankton_logs')
        os.makedirs(log_dir, exist_ok=True)

        logging.basicConfig(
            filename=os.path.join(log_dir, 'printer_debug.log'),
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            force=True
        )
        logging.info("HS-K33 Printer Handler Initializing")

    def _usb_cleanup(self):
        """Clean up USB interfaces based on manual's kernel module recommendations"""
        try:
            # Check if module is loaded first
            lsmod_result = subprocess.run(['lsmod'], capture_output=True, text=True)
            if 'usblp' in lsmod_result.stdout:
                subprocess.run(['sudo', 'rmmod', 'usblp'], check=False)
                time.sleep(0.1)

            # Only try to load the module if it's not already loaded
            lsmod_result = subprocess.run(['lsmod'], capture_output=True, text=True)
            if 'usblp' not in lsmod_result.stdout:
                subprocess.run(['sudo', 'modprobe', 'usblp'], check=False)
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"USB cleanup failed: {str(e)}")

    def _initialize(self):
        """Full initialization sequence from manual page 44"""
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            try:
                self.device = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
                if self.device is None:
                    raise ValueError("Printer not found - check USB connection")

                # Manual initialization sequence
                self.device.reset()
                time.sleep(0.1)

                if self.device.is_kernel_driver_active(0):
                    self.device.detach_kernel_driver(0)

                self.device.set_configuration()
                cfg = self.device.get_active_configuration()
                intf = cfg[(0, 0)]

                # Find endpoints
                def match_endpoint(e):
                    return usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT

                self.ep_out = usb.util.find_descriptor(
                    intf,
                    custom_match=match_endpoint
                )

                # Send hardware initialization commands from manual
                self._send([
                    b'\x1B\x40',  # Initialize printer (ESC @)
                    b'\x1B\x74\x00',  # Select character code table (ESC t 0)
                    MIN_DENSITY_CMD,  # Set print density and speed
                    b'\x1D\x21\x00',  # Set character size (GS ! 0)
                    b'\x1B\x33\x28',  # Set line spacing to 40 dots (ESC 3 n)
                    b'\x1B\x61\x00',  # Left alignment (ESC a 0)
                    b'\x1B\x44\x00',  # Clear tab stops (ESC D NUL)
                    b'\x1B\x32',  # Set line spacing to 1/6 inch (ESC 2)
                ])

                logging.info("Printer initialized successfully")
                return

            except usb.core.USBError as e:
                logging.error(f"USB Error: {str(e)}")
                self._handle_usb_error(e)
                attempts += 1
                time.sleep(0.2)

        raise RuntimeError("Failed to initialize printer after 3 attempts")

    def _handle_usb_error(self, error):
        """Handle common USB errors based on manual's status codes"""
        if error.errno == 19:  # Device disconnected
            logging.error("Printer disconnected - check physical connection")
        elif error.errno == 13:  # Permission error
            logging.error("USB permission denied - ensure udev rules are set")
        elif error.errno == 16:  # Resource busy
            logging.error("Resource busy - retrying initialization")
            self._usb_cleanup()
        else:
            logging.error("Unknown USB error")

    def _send(self, commands, retries=3):
        """Robust command sending with error recovery"""
        for cmd in commands:
            attempt = 0
            while attempt < retries:
                try:
                    if len(cmd) > 1024:
                        # Send large commands in chunks
                        for i in range(0, len(cmd), 1024):
                            chunk = cmd[i:i + 1024]
                            self.ep_out.write(chunk)
                            time.sleep(0.005)  # Slightly longer delay between chunks
                    else:
                        self.ep_out.write(cmd)
                        time.sleep(0.001)  # Small delay after each command

                    break  # Command sent successfully

                except usb.core.USBError as e:
                    logging.warning(f"Command failed (attempt {attempt + 1}/{retries}): {str(e)}")
                    attempt += 1
                    if attempt >= retries:
                        raise
                    self._initialize()
                    time.sleep(0.1)

    def _check_paper(self):
        """Paper status check using manual's real-time status command (Page 40)"""
        try:
            self._send([b'\x10\x04\x04'])  # DLE EOT 4
            status = self.device.read(0x81, 1, timeout=1000)[0]
            return (status & 0x60) == 0  # Paper OK mask
        except Exception as e:
            logging.error(f"Paper check failed: {str(e)}")
            return False

    def print_text(self, command):
        """Advanced text formatting with manual's character commands"""
        try:
            if not self._check_paper():
                raise RuntimeError("Paper out - unable to print")

            # Extract parameters
            text = command.get('text', '')
            align = command.get('align', 'left')
            bold = command.get('bold', False)
            underline = command.get('underline', False)
            font_width = command.get('fontWidth', 0)
            font_height = command.get('fontHeight', 0)
            font_type = command.get('fontType', 'A')  # A or B

            # Calculate maximum characters per line based on font type
            max_chars = {
                'A': 48,  # 12×24 font
                'B': 48,  # 9×17 font
                'C': 48,  # 9×24 font
                'D': 48   # 8×16 font
            }.get(font_type, 48)

            # Adjust max chars if font width is larger than 1
            if font_width > 1:
                max_chars = max_chars // font_width

            # Wrap text to fit the line width
            wrapped_text = textwrap.fill(text, width=max_chars, replace_whitespace=False)

            commands = []

            # Reset printer settings
            commands.append(b'\x1B\x40')

            # Set alignment (ESC a n)
            align_values = {'left': 0, 'center': 1, 'right': 2}
            commands.append(b'\x1B\x61' + bytes([align_values.get(align, 0)]))

            # Select font type (ESC M n)
            font_values = {
                'A': 0,  # Normal size (12×24)
                'B': 1,  # Smaller font (9×17)
                'C': 2,  # Condensed (9×24)
                'D': 3  # Smallest (8×16)
            }
            commands.append(b'\x1B\x4D' + bytes([font_values.get(font_type, 0)]))

            # Set character spacing
            commands.append(b'\x1B\x20\x00')  # ESC SP n - Set character spacing to 0

            # Set line spacing
            if font_type in ['B', 'D']:  # Smaller fonts need less line spacing
                commands.append(b'\x1B\x33\x10')  # ESC 3 n - Set line spacing to 16 dots
            else:
                commands.append(b'\x1B\x33\x16')  # ESC 3 n - Set line spacing to 22 dots

            # Set print mode
            mode = 0
            if bold:
                mode |= (1 << 3)  # Set bit 3 for emphasized
            if underline:
                mode |= (1 << 7)  # Set bit 7 for underline
            commands.append(b'\x1B\x21' + bytes([mode]))

            # Set character size (GS !)
            if font_width > 0 or font_height > 0:
                width = min(font_width, 8) if font_width > 0 else 1
                height = min(font_height, 8) if font_height > 0 else 1
                size = ((width - 1) << 4) | (height - 1)
                commands.append(b'\x1D\x21' + bytes([size]))

            # Encode and send wrapped text
            text_bytes = wrapped_text.encode('cp437', 'replace')
            commands.append(text_bytes + b'\n')

            # Send all commands
            self._send(commands)
            time.sleep(0.01)  # Small delay after printing

        except Exception as e:
            logging.error(f"Text print failed: {str(e)}")
            raise


    def print_image(self, command):
        """Bitmap printing using manual's raster command (Page 30)"""
        try:
            # Reset printer and clear buffer before image
            self._send([
                b'\x1B\x40',  # Initialize printer
                b'\x1B\x61\x01'  # Center alignment
            ])
            time.sleep(0.01)  # Wait for initialization

            # Get and validate image data
            image_data = command.get('image')
            if not image_data:
                raise ValueError("No image data provided")

            try:
                # Decode base64 data
                decoded_data = base64.b64decode(image_data)

                # Open image with PIL
                img = Image.open(BytesIO(decoded_data))

                # Force convert to RGB if image is RGBA (handles transparency)
                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                    img = background

                # Convert to grayscale
                img = img.convert('L')

                # Check if image should be inverted
                invert = command.get('invert', True)
                if invert:
                    img = ImageOps.invert(img)

                # Adjust contrast to improve black and white conversion
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.5)  # Increase contrast slightly

                # Convert to pure black and white (1-bit)
                threshold = 128
                img = img.point(lambda x: 0 if x < threshold else 255, '1')

                # Calculate dimensions
                max_width = 576  # 72mm * 8 dots/mm (203 DPI)
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                # Ensure width is a multiple of 8
                width = (img.width + 7) & ~7
                if width != img.width:
                    new_img = Image.new('1', (width, img.height), 1)
                    new_img.paste(img, (0, 0))
                    img = new_img

                # Set alignment before printing image
                align = command.get('align', 'center')
                align_cmd = b'\x1B\x61' + bytes([{'left': 0, 'center': 1, 'right': 2}[align]])
                self._send([align_cmd])
                time.sleep(0.05)

                # Calculate width in bytes
                width_bytes = img.width // 8

                # Prepare raster data with MSB (Most Significant Bit) first
                raster_data = bytearray()
                for y in range(img.height):
                    for x in range(0, img.width, 8):
                        byte = 0
                        for bit in range(8):
                            if x + bit < img.width:
                                if img.getpixel((x + bit, y)) == 0:  # Black pixel
                                    byte |= (0x80 >> bit)
                        raster_data.append(byte)

                # Send raster command header according to manual specifications
                header = [
                    b'\x1D\x76\x30\x00',  # GS v 0 m - Raster bit-image command
                    bytes([width_bytes & 0xFF, width_bytes >> 8]),  # xL xH - width bytes
                    bytes([img.height & 0xFF, img.height >> 8]),  # yL yH - height
                ]
                self._send(header)
                time.sleep(0.01)  # Wait for header processing

                # Send image data in smaller chunks
                CHUNK_SIZE = 128  # Smaller chunks for more reliable transmission
                for i in range(0, len(raster_data), CHUNK_SIZE):
                    chunk = raster_data[i:i + CHUNK_SIZE]
                    self._send([bytes(chunk)])
                    time.sleep(0.005)  # Small delay between chunks

                # Wait for image data to be processed
                time.sleep(0.01)

                # Feed paper and add spacing after image
                feed_commands = [
                    b'\x1B\x4A\x40',  # Feed 64 dots
                    b'\x1B\x64\x02'  # Feed 2 lines
                ]
                self._send(feed_commands)
                time.sleep(0.2)  # Wait for feeding to complete

            except Exception as e:
                logging.error(f"Image processing failed: {str(e)}")
                logging.exception(e)
                # Try to reset printer state
                self._initialize()
                raise ValueError(f"Failed to process image: {str(e)}")

        except Exception as e:
            logging.error(f"Image print failed: {str(e)}")
            logging.exception(e)
            # Try to reset printer state
            self._initialize()
            raise

    def _clear_buffer(self):
        """Clear printer buffer"""
        try:
            self._send([
                b'\x1B\x40',  # Initialize printer
                b'\x1B\x4A\x40',  # Feed some paper
            ])
            time.sleep(0.01)
        except Exception as e:
            logging.error(f"Failed to clear buffer: {str(e)}")

    def print_qr(self, command):
        """QR Code printing using manual's GS (k) commands (Page 38)"""
        try:
            data = command['qr'].encode('utf-8')
            size = min(max(command.get('size', 3), 1), 16)  # Changed default to 3 for better readability

            cmds = [
                b'\x1B\x40',  # Initialize printer
                b'\x1B\x61\x01',  # Center alignment (changed from 00 to 01)
                # Set QR Code model (model 2 recommended for better compatibility)
                b'\x1D\x28\x6B\x04\x00\x31\x41\x32\x00',
                # Function 67: Set QR code size (module size)
                b'\x1D\x28\x6B\x03\x00\x31\x43' + bytes([size]),
                # Function 69: Set error correction level (M=49 instead of L for better reliability)
                b'\x1D\x28\x6B\x03\x00\x31\x45\x31',
                # Function 80: Store QR code data
                b'\x1D\x28\x6B' + bytes([len(data) + 3, 0]) + b'\x31\x50\x30' + data,
                # Function 81: Print QR code
                b'\x1D\x28\x6B\x03\x00\x31\x51\x30',
                # Add some spacing after QR code
                b'\x1B\x4A\x40'  # Feed 64 dots
            ]

            self._send(cmds)
            time.sleep(0.01)  # Small delay after printing

        except Exception as e:
            logging.error(f"QR print failed: {str(e)}")
            logging.exception(e)  # Added more detailed error logging
            raise




    def paper_feed(self, command):
        """Paper feed using ESC J n (Page 12)"""
        try:
            lines = command.get('space', 1)
            lines = max(min(lines, 255), 1)

            # Convert lines to dots (1 line ≈ 24 dots at default line spacing)
            dots = lines * 24

            commands = [
                b'\x1B\x4A' + bytes([dots]),  # ESC J n - Feed paper n dots
                b'\x1B\x64' + bytes([lines])  # ESC d n - Feed n lines
            ]

            self._send(commands)
            time.sleep(0.01)  # Give printer time to feed

        except Exception as e:
            logging.error(f"Paper feed failed: {str(e)}")
            raise

    def cut_paper(self, command=None):
        """Cutting command with options from manual (Page 44)"""
        try:
            # First feed extra paper to ensure proper cutting position
            feed_commands = [
                b'\x1B\x64\x03',  # Feed 3 lines
                b'\x1B\x4A\x80',  # Feed 128 dots vertically
            ]
            self._send(feed_commands)
            time.sleep(0.01)  # Wait for feed

            # Send cut command
            # Using different cut command from manual
            if command and command.get('partial', False):
                cut_cmd = b'\x1D\x56\x01'  # Partial cut
            else:
                cut_cmd = b'\x1D\x56\x00'  # Full cut

            self._send([cut_cmd])
            time.sleep(0.2)  # Wait for cut to complete

        except Exception as e:
            logging.error(f"Cut failed: {str(e)}")
            logging.exception(e)
            raise


def main():
    """Main processing loop with enhanced error handling"""
    lock = acquire_lock()
    if not lock:
        print(json.dumps({"status": "error", "message": "Another instance running"}))
        return

    printer = None
    try:
        printer = HSK33Printer()
        print(json.dumps({"status": "ready"}))
        sys.stdout.flush()

        while True:
            line = sys.stdin.readline()
            if not line:
                break

            try:
                cmd = json.loads(line.strip())
                if 'text' in cmd:
                    printer.print_text(cmd)
                    time.sleep(0.01)
                elif 'image' in cmd:
                    printer._clear_buffer()
                    time.sleep(0.01)
                    printer.print_image(cmd)
                    time.sleep(0.2)
                elif 'qr' in cmd:
                    printer.print_qr(cmd)
                    time.sleep(0.01)
                elif 'space' in cmd:
                    printer.paper_feed(cmd)
                    time.sleep(0.01)
                elif 'cut' in cmd:
                    printer.paper_feed({'space': 1})
                    time.sleep(0.01)
                    printer.cut_paper(cmd)
                    time.sleep(0.2)

                print(json.dumps({"status": "success"}))
                sys.stdout.flush()


            except Exception as e:
                logging.error(f"Command failed: {str(e)}")
                print(json.dumps({"status": "error", "message": str(e)}))
                sys.stdout.flush()

    except Exception as e:
        logging.critical(f"Fatal error: {str(e)}")
        print(json.dumps({"status": "error", "message": "Printer system failure"}))
    finally:
        release_lock()
        if printer:
            try:
                # Final cut with extra feed
                printer.paper_feed({'space': 3})
                printer.cut_paper()
            except:
                pass


if __name__ == '__main__':
    main()
