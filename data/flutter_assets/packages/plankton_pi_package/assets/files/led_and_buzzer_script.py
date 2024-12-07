import sys
import json
import time
from gpiozero import Buzzer
import spidev

class LedAndBuzzer:
    def __init__(self, led_spi_bus=0, led_spi_device=0, buzzer_pin=16, led_count=30, led_spi_speed=8000000):
        self.spi = spidev.SpiDev()
        self.spi.open(led_spi_bus, led_spi_device)
        self.spi.max_speed_hz = led_spi_speed
        self.led_count = led_count
        self.buzzer = Buzzer(buzzer_pin)

    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def encode_color_to_spi(self, r, g, b):
        return [
            0b11111100 if color & (1 << (7-i)) else 0b11000000
            for color in [g, r, b]
            for i in range(8)
        ]

    def update_pixels(self, colors):
        data = []
        for color in colors:
            data.extend(self.encode_color_to_spi(*color))
        self.spi.xfer2(data)

    def clear_led_strip(self):
        self.update_pixels([(0, 0, 0)] * self.led_count)

    def pulse_color(self, color, duration):
        rgb_color = self.hex_to_rgb(color)
        start_time = time.time()
        while time.time() - start_time < duration:
            for i in range(0, 256, 5):
                scaled_color = tuple(int(c * i / 255) for c in rgb_color)
                self.update_pixels([scaled_color] * self.led_count)
                time.sleep(0.01)
            for i in range(255, -1, -5):
                scaled_color = tuple(int(c * i / 255) for c in rgb_color)
                self.update_pixels([scaled_color] * self.led_count)
                time.sleep(0.01)
        self.clear_led_strip()

    def solid_color(self, color, duration):
        rgb_color = self.hex_to_rgb(color)
        self.update_pixels([rgb_color] * self.led_count)
        time.sleep(duration)
        self.clear_led_strip()

    def flash_color(self, color, duration, flash_duration=0.5):
        rgb_color = self.hex_to_rgb(color)
        end_time = time.time() + duration
        while time.time() < end_time:
            self.update_pixels([rgb_color] * self.led_count)
            time.sleep(flash_duration)
            self.clear_led_strip()
            time.sleep(flash_duration)

    def animate_up(self, color, duration):
        rgb_color = self.hex_to_rgb(color)
        start_time = time.time()
        while time.time() - start_time < duration:
            for i in range(self.led_count):
                pixels = [(0, 0, 0)] * self.led_count
                pixels[i] = rgb_color
                pixels[-(i + 1)] = rgb_color
                self.update_pixels(pixels)
                time.sleep(0.05)
            self.buzzer.on()
            time.sleep(0.1)
            self.buzzer.off()
        self.clear_led_strip()

    def animate_down(self, color, duration):
        rgb_color = self.hex_to_rgb(color)
        start_time = time.time()
        while time.time() - start_time < duration:
            for i in range(self.led_count // 2):
                pixels = [(0, 0, 0)] * self.led_count
                pixels[self.led_count // 2 - i] = rgb_color
                pixels[self.led_count // 2 + i] = rgb_color
                self.update_pixels(pixels)
                time.sleep(0.05)
            self.buzzer.on()
            time.sleep(0.1)
            self.buzzer.off()
        self.clear_led_strip()

    def run_effect(self, color, mode, duration):
        if mode == 'pulse':
            self.pulse_color(color, duration)
        elif mode == 'solid':
            self.solid_color(color, duration)
        elif mode == 'flash':
            self.flash_color(color, duration)
        elif mode == 'animate_up':
            self.animate_up(color, duration)
        elif mode == 'animate_down':
            self.animate_down(color, duration)
        else:
            print(json.dumps({"method": "error", "message": f"Unknown mode: {mode}"}))

def main():
    led_and_buzzer = LedAndBuzzer()
    print(json.dumps({"method": "ready"}))
    sys.stdout.flush()

    for line in sys.stdin:
        try:
            data = json.loads(line)
            if data["method"] == "effect":
                led_and_buzzer.run_effect(data["color"], data["mode"], data["duration"])
                print(json.dumps({"method": "effectComplete"}))
            elif data["method"] == "buzz":
                led_and_buzzer.buzzer.on()
                time.sleep(data["duration"])
                led_and_buzzer.buzzer.off()
                print(json.dumps({"method": "buzzComplete"}))
            sys.stdout.flush()
        except json.JSONDecodeError:
            print(json.dumps({"method": "error", "message": "Invalid JSON"}))
            sys.stdout.flush()
        except Exception as e:
            print(json.dumps({"method": "error", "message": str(e)}))
            sys.stdout.flush()

if __name__ == "__main__":
    main()
