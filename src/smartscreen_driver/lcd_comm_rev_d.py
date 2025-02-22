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

from enum import Enum
import logging
from typing import Optional, Tuple
import queue

from serial.tools.list_ports import comports
from PIL import Image

from .lcd_comm import LcdComm, Orientation
from .serialize import image_to_rgb565, chunked

logger = logging.getLogger(__name__)


class Command(Enum):
    GETINFO = bytearray((71, 00, 00, 00))
    SETORG = bytearray((67, 72, 00, 00))  # Set portrait orientation
    SET180 = bytearray((67, 71, 00, 00))  # Set reverse portrait orientation
    SETHF = bytearray(
        (67, 68, 00, 00)
    )  # Set portrait orientation with horizontal mirroring
    SETVF = bytearray(
        (67, 70, 00, 00)
    )  # Set reverse portrait orientation with horizontal mirroring
    SETBL = bytearray((67, 67))  # Brightness setting
    DISPCOLOR = bytearray((67, 66))  # Display RGB565 color on whole screen
    BLOCKWRITE = bytearray((67, 65))  # Send bitmap size
    INTOPICMODE = bytearray((68, 00, 00, 00))  # Start bitmap transmission
    OUTPICMODE = bytearray((65, 00, 00, 00))  # End bitmap transmission


# This class is for Kipye Qiye Smart Display 3.5"
class LcdCommRevD(LcdComm):
    def __init__(
        self,
        com_port: str = "AUTO",
        display_width: int = 320,
        display_height: int = 480,
        update_queue: Optional[queue.Queue] = None,
    ):
        logger.debug("HW revision: D")
        LcdComm.__init__(self, com_port, display_width, display_height, update_queue)
        self.open_serial()

    def __del__(self):
        self.close_serial()

    @staticmethod
    def auto_detect_com_port() -> Optional[str]:
        com_ports = comports()
        auto_com_port = None

        for com_port in com_ports:
            if com_port.vid == 0x454D and com_port.pid == 0x4E41:
                auto_com_port = com_port.device
                break

        return auto_com_port

    def write_data(self, data: bytearray):
        LcdComm.write_data(self, data)

        # Empty the input buffer after each write: we don't process acknowledgements the screen sends back
        self.serial_flush_input()

    def send_command(
        self,
        cmd: Command,
        payload: Optional[bytearray] = None,
        bypass_queue: bool = False,
    ):
        message = bytearray(cmd.value)

        if payload:
            message.extend(payload)

        # If no queue for async requests, or if asked explicitly to do the request sequentially: do request now
        if not self.update_queue or bypass_queue:
            self.write_data(message)
        else:
            # Lock queue mutex then queue the request
            with self.update_queue_mutex:
                self.update_queue.put((self.write_data, [message]))

    def initialize_comm(self):
        pass

    def reset(self):
        # HW revision D does not implement a command to reset it: clear display instead
        self.clear()

    def clear(self):
        # HW revision D does not implement a Clear command: display a blank image on the whole screen
        color = 0xFFFF  # RGB565 White color
        color_bytes = bytearray(color.to_bytes(2, "big"))
        self.send_command(cmd=Command.DISPCOLOR, payload=color_bytes)

    def screen_off(self):
        # HW revision D does not implement a "ScreenOff" native command: using SetBrightness(0) instead
        self.set_brightness(0)

    def screen_on(self):
        # HW revision D does not implement a "ScreenOn" native command: using SetBrightness() instead
        self.set_brightness()

    def set_brightness(self, level: int = 25):
        assert 0 <= level <= 100, "Brightness level must be [0-100]"

        # Brightness scales from 0 to 500, with 500 being the brightest and 0 being the darkest.
        # Convert our brightness % to an absolute value.
        converted_level = level * 5

        level_bytes = bytearray(converted_level.to_bytes(2, "big"))

        # Send the command twice because sometimes it is not applied...
        self.send_command(cmd=Command.SETBL, payload=level_bytes)
        self.send_command(cmd=Command.SETBL, payload=level_bytes)

    def set_orientation(self, orientation: Orientation = Orientation.PORTRAIT):
        # In revision D, reverse orientations (reverse portrait / reverse landscape) are managed by the display
        # Basic orientations (portrait / landscape) are software-managed because screen commands only support portrait
        self.orientation = orientation

        if (
            self.orientation == Orientation.REVERSE_LANDSCAPE
            or self.orientation == Orientation.REVERSE_PORTRAIT
        ):
            self.send_command(cmd=Command.SET180)
        else:
            self.send_command(cmd=Command.SETORG)

    def paint(
        self,
        image: Image.Image,
        pos: Tuple[int, int] = (0, 0),
    ):
        image = self._crop_to_display_bounds(image, pos)
        image_width, image_height = image.size[0], image.size[1]

        if image_height == 0 or image_width == 0:
            return

        x, y = pos
        if (
            self.orientation == Orientation.PORTRAIT
            or self.orientation == Orientation.REVERSE_PORTRAIT
        ):
            (x0, y0) = (x, y)
            (x1, y1) = (x + image_width - 1, y + image_height - 1)
        else:
            # Landscape / reverse landscape orientations are software managed: rotate image -90° and get new coordinates
            image = image.rotate(270, expand=True)
            (x0, y0) = (self.display_width - y - image_height, x)
            (x1, y1) = (self.display_width - y - 1, x + image_width - 1)
            image_width, image_height = image_height, image_width

        # Send bitmap size
        image_data = bytearray()
        image_data += x0.to_bytes(2, "big")
        image_data += x1.to_bytes(2, "big")
        image_data += y0.to_bytes(2, "big")
        image_data += y1.to_bytes(2, "big")
        self.send_command(cmd=Command.BLOCKWRITE, payload=image_data)

        # Prepare bitmap data transmission
        self.send_command(Command.INTOPICMODE)

        rgb565be = image_to_rgb565(image, "big")

        # Lock queue mutex then queue all the requests for the image data
        with self.update_queue_mutex:
            for chunk in chunked(rgb565be, 63):
                self.send_line(b"\x50" + chunk)

        # Indicate the complete bitmap has been transmitted
        self.send_command(Command.OUTPICMODE)
