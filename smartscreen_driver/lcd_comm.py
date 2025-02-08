# turing-smart-screen-python - a Python system monitor and library for USB-C displays like Turing Smart Screen or XuanFang
# https://github.com/mathoudebine/turing-smart-screen-python/

# Copyright (C) 2021-2023  Matthieu Houdebine (mathoudebine)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import queue
import sys
import threading
import time
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Tuple, Optional, Dict
import logging

import serial
from PIL import Image, ImageFont

logger = logging.getLogger(__name__)


class Orientation(IntEnum):
    PORTRAIT = 0
    LANDSCAPE = 2
    REVERSE_PORTRAIT = 1
    REVERSE_LANDSCAPE = 3


class LcdComm(ABC):
    def __init__(
        self,
        com_port: str = "AUTO",
        display_width: int = 320,
        display_height: int = 480,
        update_queue: Optional[queue.Queue] = None,
    ):
        self.lcd_serial = None

        # String containing absolute path to serial port e.g. "COM3", "/dev/ttyACM1" or "AUTO" for auto-discovery
        self.com_port = com_port

        # Display always start in portrait orientation by default
        self.orientation = Orientation.PORTRAIT
        # Display width in default orientation (portrait)
        self.display_width = display_width
        # Display height in default orientation (portrait)
        self.display_height = display_height

        # Queue containing the serial requests to send to the screen. An external thread should run to process requests
        # on the queue. If you want serial requests to be done in sequence, set it to None
        self.update_queue = update_queue

        # Mutex to protect the queue in case a thread want to add multiple requests (e.g. image data) that should not be
        # mixed with other requests in-between
        self.update_queue_mutex = threading.Lock()

    def get_width(self) -> int:
        if (
            self.orientation == Orientation.PORTRAIT
            or self.orientation == Orientation.REVERSE_PORTRAIT
        ):
            return self.display_width
        else:
            return self.display_height

    def get_height(self) -> int:
        if (
            self.orientation == Orientation.PORTRAIT
            or self.orientation == Orientation.REVERSE_PORTRAIT
        ):
            return self.display_height
        else:
            return self.display_width

    def open_serial(self):
        if self.com_port == "AUTO":
            self.com_port = self.auto_detect_com_port()
            if not self.com_port:
                logger.error(
                    "Cannot find COM port automatically, please run Configuration again and select COM port manually"
                )
                try:
                    sys.exit(0)
                except:
                    os._exit(0)
            else:
                logger.debug(f"Auto detected COM port: {self.com_port}")
        else:
            logger.debug(f"Static COM port: {self.com_port}")

        try:
            self.lcd_serial = serial.Serial(
                self.com_port, 115200, timeout=1, rtscts=True
            )
        except Exception as e:
            logger.error(f"Cannot open COM port {self.com_port}: {e}")
            try:
                sys.exit(0)
            except:
                os._exit(0)

    def close_serial(self):
        if self.lcd_serial is not None:
            self.lcd_serial.close()

    def serial_write(self, data: bytes):
        assert self.lcd_serial is not None
        self.lcd_serial.write(data)

    def serial_read(self, size: int) -> bytes:
        assert self.lcd_serial is not None
        return self.lcd_serial.read(size)

    def serial_flush_input(self):
        if self.lcd_serial is not None:
            self.lcd_serial.reset_input_buffer()

    def write_data(self, data: bytearray):
        self.write_line(bytes(data))

    def send_line(self, line: bytes):
        if self.update_queue:
            # Queue the request. Mutex is locked by caller to queue multiple lines
            self.update_queue.put((self.write_line, [line]))
        else:
            # If no queue for async requests: do request now
            self.write_line(line)

    def write_line(self, line: bytes):
        try:
            self.serial_write(line)
        except serial.SerialTimeoutException:
            # We timed-out trying to write to our device, slow things down.
            logger.warning("(Write line) Too fast! Slow down!")
        except serial.SerialException:
            # Error writing data to device: close and reopen serial port, try to write again
            logger.error(
                "SerialException: Failed to send serial data to device. Closing and reopening COM port before retrying once."
            )
            self.close_serial()
            time.sleep(1)
            self.open_serial()
            self.serial_write(line)

    def read_data(self, size: int):
        try:
            response = self.serial_read(size)
            # logger.debug("Received: [{}]".format(str(response, 'utf-8')))
            return response
        except serial.SerialTimeoutException:
            # We timed-out trying to read from our device, slow things down.
            logger.warning("(Read data) Too fast! Slow down!")
        except serial.SerialException:
            # Error writing data to device: close and reopen serial port, try to read again
            logger.error(
                "SerialException: Failed to read serial data from device. Closing and reopening COM port before retrying once."
            )
            self.close_serial()
            time.sleep(1)
            self.open_serial()
            return self.serial_read(size)

    @staticmethod
    @abstractmethod
    def auto_detect_com_port() -> Optional[str]:
        pass

    @abstractmethod
    def initialize_comm(self):
        pass

    @abstractmethod
    def reset(self):
        pass

    @abstractmethod
    def clear(self):
        pass

    @abstractmethod
    def screen_off(self):
        pass

    @abstractmethod
    def screen_on(self):
        pass

    @abstractmethod
    def set_brightness(self, level: int):
        pass

    def set_backplate_led_color(
        self, led_color: Tuple[int, int, int] = (255, 255, 255)
    ):
        pass

    @abstractmethod
    def set_orientation(self, orientation: Orientation):
        pass

    @abstractmethod
    def paint(
        self,
        image: Image.Image,
        x: int = 0,
        y: int = 0,
        image_width: int = 0,
        image_height: int = 0,
    ):
        pass
