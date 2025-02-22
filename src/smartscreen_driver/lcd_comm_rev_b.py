# turing-smart-screen-python - a Python system monitor and library for USB-C displays like Turing Smart Screen or XuanFang
# https://github.com/mathoudebine/turing-smart-screen-python/

# Copyright (C) 2021-2023  Matthieu Houdebine (mathoudebine)
# Copyright (C) 2022-2023  Charles Ferguson (gerph)
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

import logging
from typing import Optional, Tuple
import queue
from enum import IntEnum

from serial.tools.list_ports import comports
from PIL import Image

from .lcd_comm import LcdComm, Orientation
from .serialize import image_to_rgb565, chunked

logger = logging.getLogger(__name__)


class Command(IntEnum):
    HELLO = 0xCA  # Establish communication before driving the screen
    SET_ORIENTATION = 0xCB  # Sets the screen orientation
    DISPLAY_BITMAP = 0xCC  # Displays an image on the screen
    SET_LIGHTING = 0xCD  # Sets the screen backplate RGB LED color
    SET_BRIGHTNESS = 0xCE  # Sets the screen brightness


# In revision B, basic orientations (portrait / landscape) are managed by the display
# The reverse orientations (reverse portrait / reverse landscape) are software-managed
class OrientationValueRevB(IntEnum):
    ORIENTATION_PORTRAIT = 0x0
    ORIENTATION_LANDSCAPE = 0x1


# HW revision B offers 4 sub-revisions to identify the HW capabilities
class SubRevision(IntEnum):
    A01 = 0xA01  # HW revision B - brightness 0/1
    A02 = 0xA02  # HW revision "flagship" - brightness 0/1
    A11 = 0xA11  # HW revision B - brightness 0-255
    A12 = 0xA12  # HW revision "flagship" - brightness 0-255


# This class is for XuanFang (rev. B & flagship) 3.5" screens
class LcdCommRevB(LcdComm):
    def __init__(
        self,
        com_port: str = "AUTO",
        display_width: int = 320,
        display_height: int = 480,
        update_queue: Optional[queue.Queue] = None,
    ):
        logger.debug("HW revision: B")
        LcdComm.__init__(self, com_port, display_width, display_height, update_queue)
        self.open_serial()
        self.sub_revision = (
            SubRevision.A01
        )  # Run a Hello command to detect correct sub-rev.

    def __del__(self):
        self.close_serial()

    def is_flagship(self):
        return (
            self.sub_revision == SubRevision.A02 or self.sub_revision == SubRevision.A12
        )

    def is_brightness_range(self):
        return (
            self.sub_revision == SubRevision.A11 or self.sub_revision == SubRevision.A12
        )

    @staticmethod
    def auto_detect_com_port() -> Optional[str]:
        com_ports = comports()
        auto_com_port = None

        for com_port in com_ports:
            if com_port.serial_number == "2017-2-25":
                auto_com_port = com_port.device
                break

        return auto_com_port

    def send_command(self, cmd: Command, payload=None, bypass_queue: bool = False):
        # New protocol (10 byte packets, framed with the command, 8 data bytes inside)
        if payload is None:
            payload = [0] * 8
        elif len(payload) < 8:
            payload = list(payload) + [0] * (8 - len(payload))

        byte_buffer = bytearray(10)
        byte_buffer[0] = cmd
        byte_buffer[1] = payload[0]
        byte_buffer[2] = payload[1]
        byte_buffer[3] = payload[2]
        byte_buffer[4] = payload[3]
        byte_buffer[5] = payload[4]
        byte_buffer[6] = payload[5]
        byte_buffer[7] = payload[6]
        byte_buffer[8] = payload[7]
        byte_buffer[9] = cmd

        # If no queue for async requests, or if asked explicitly to do the request sequentially: do request now
        if not self.update_queue or bypass_queue:
            self.write_data(byte_buffer)
        else:
            # Lock queue mutex then queue the request
            with self.update_queue_mutex:
                self.update_queue.put((self.write_data, [byte_buffer]))

    def _hello(self):
        hello = [ord("H"), ord("E"), ord("L"), ord("L"), ord("O")]

        # This command reads LCD answer on serial link, so it bypasses the queue
        self.send_command(Command.HELLO, payload=hello, bypass_queue=True)
        response = self.serial_read(10)
        self.serial_flush_input()

        if len(response) != 10:
            logger.warning("Device not recognised (short response to HELLO)")
        assert response, "Device did not return anything"
        if response[0] != Command.HELLO or response[-1] != Command.HELLO:
            logger.warning("Device not recognised (bad framing)")
        if [x for x in response[1:6]] != hello:
            logger.warning(
                "Device not recognised (No HELLO; got %r)" % (response[1:6],)
            )
        # The HELLO response here is followed by 2 bytes
        # This is the screen version (not like the revision which is B/flagship)
        # The version is used to determine what capabilities the screen offers (see SubRevision class above)
        if response[6] == 0xA:
            if response[7] == 0x01:
                self.sub_revision = SubRevision.A01
            elif response[7] == 0x02:
                self.sub_revision = SubRevision.A02
            elif response[7] == 0x11:
                self.sub_revision = SubRevision.A11
            elif response[7] == 0x12:
                self.sub_revision = SubRevision.A12
            else:
                logger.warning("Display returned unknown sub-revision on Hello answer")

        logger.debug("HW sub-revision: %s" % (str(self.sub_revision)))

    def initialize_comm(self):
        self._hello()

    def reset(self):
        # HW revision B does not implement a command to reset it: clear display instead
        self.clear()

    def clear(self):
        # HW revision B does not implement a Clear command: display a blank image on the whole screen
        # Force an orientation in case the screen is currently configured with one different from the theme
        backup_orientation = self.orientation
        self.set_orientation(orientation=Orientation.PORTRAIT)

        blank = Image.new("RGB", (self.width(), self.height()), (255, 255, 255))
        self.paint(blank)

        # Restore orientation
        self.set_orientation(orientation=backup_orientation)

    def screen_off(self):
        # HW revision B does not implement a "ScreenOff" native command: using SetBrightness(0) instead
        self.set_brightness(0)

    def screen_on(self):
        # HW revision B does not implement a "ScreenOn" native command: using SetBrightness() instead
        self.set_brightness()

    def set_brightness(self, level: int = 25):
        assert 0 <= level <= 100, "Brightness level must be [0-100]"

        if self.is_brightness_range():
            # Brightness scales from 0 to 255, with 255 being the brightest and 0 being the darkest.
            # Convert our brightness % to an absolute value.
            converted_level = int((level / 100) * 255)
        else:
            # Brightness is 1 (off) or 0 (full brightness)
            logger.info("Your display does not support custom brightness level")
            converted_level = 1 if level == 0 else 0

        self.send_command(Command.SET_BRIGHTNESS, payload=[converted_level])

    def set_backplate_led_color(
        self, led_color: Tuple[int, int, int] = (255, 255, 255)
    ):
        if self.is_flagship():
            self.send_command(Command.SET_LIGHTING, payload=list(led_color))
        else:
            logger.info(
                "Only HW revision 'flagship' supports backplate LED color setting"
            )

    def set_orientation(self, orientation: Orientation = Orientation.PORTRAIT):
        # In revision B, basic orientations (portrait / landscape) are managed by the display
        # The reverse orientations (reverse portrait / reverse landscape) are software-managed
        self.orientation = orientation
        if (
            self.orientation == Orientation.PORTRAIT
            or self.orientation == Orientation.REVERSE_PORTRAIT
        ):
            self.send_command(
                Command.SET_ORIENTATION,
                payload=[OrientationValueRevB.ORIENTATION_PORTRAIT],
            )
        else:
            self.send_command(
                Command.SET_ORIENTATION,
                payload=[OrientationValueRevB.ORIENTATION_LANDSCAPE],
            )

    def serialize_image(self, image: Image.Image, height: int, width: int) -> bytes:
        if image.width != width or image.height != height:
            image = image.crop((0, 0, width, height))
        if (
            self.orientation == Orientation.REVERSE_PORTRAIT
            or self.orientation == Orientation.REVERSE_LANDSCAPE
        ):
            image = image.rotate(180)
        return image_to_rgb565(image, "big")

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
            or self.orientation == Orientation.LANDSCAPE
        ):
            x0, y0 = x, y
            x1, y1 = x + image_width - 1, y + image_height - 1
        else:
            # Reverse landscape/portrait orientations are software-managed: get new coordinates
            x0, y0 = (
                self.width() - x - image_width,
                self.height() - y - image_height,
            )
            x1, y1 = self.width() - x - 1, self.height() - y - 1

        self.send_command(
            Command.DISPLAY_BITMAP,
            payload=[
                (x0 >> 8) & 255,
                x0 & 255,
                (y0 >> 8) & 255,
                y0 & 255,
                (x1 >> 8) & 255,
                x1 & 255,
                (y1 >> 8) & 255,
                y1 & 255,
            ],
        )

        rgb565be = self.serialize_image(image, image_height, image_width)

        # Lock queue mutex then queue all the requests for the image data
        with self.update_queue_mutex:
            # Send image data by multiple of "display width" bytes
            for chunk in chunked(rgb565be, self.width() * 8):
                self.send_line(chunk)
