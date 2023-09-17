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

import struct
from enum import Enum

from serial.tools.list_ports import comports
import numpy as np

from library.lcd.lcd_comm import *
from library.log import logger


class Command(Enum):
    # COMMANDS
    GetInfo = bytearray((71, 00, 00, 00))
    SetHf = bytearray((67, 68, 00, 00))
    SetVf = bytearray((67, 70, 00, 00))
    Set180 = bytearray((67, 71, 00, 00))
    SetOrg = bytearray((67, 72, 00, 00))
    SetBl = bytearray((67, 67, 00, 00))
    DispColor = bytearray((67, 66, 00, 00))
    BlockWrite = bytearray((67, 65))
    intopicMode = bytearray((68, 00, 00, 00))
    outpicMode = bytearray((65, 00, 00, 00))


# This class is for Kipye Qiye Smart Display 3.5"
class LcdCommRevD(LcdComm):
    def __init__(self, com_port: str = "AUTO", display_width: int = 320, display_height: int = 480,
                 update_queue: queue.Queue = None):
        logger.debug("HW revision: D")
        LcdComm.__init__(self, com_port, display_width, display_height, update_queue)
        self.openSerial()

    def __del__(self):
        self.closeSerial()

    @staticmethod
    def auto_detect_com_port():
        com_ports = comports()
        auto_com_port = None

        for com_port in com_ports:
            if com_port.vid == 0x454d and com_port.pid == 0x4e41:
                auto_com_port = com_port.device
                break

        return auto_com_port

    def WriteData(self, byteBuffer: bytearray):
        LcdComm.WriteData(self, byteBuffer)

        # Empty the input buffer after each writegitk: we don't process what the screen sends
        self.lcd_serial.reset_input_buffer()

    def SendCommand(self, cmd: Command, payload: bytearray = None, bypass_queue: bool = False):

        # Empty the input buffer regularly: we don't process what the screen sends here
        self.lcd_serial.reset_input_buffer()

        message = bytearray(cmd.value)

        if payload:
            message.extend(payload)

        # If no queue for async requests, or if asked explicitly to do the request sequentially: do request now
        if not self.update_queue or bypass_queue:
            self.WriteData(message)
        else:
            # Lock queue mutex then queue the request
            with self.update_queue_mutex:
                self.update_queue.put((self.WriteData, [message]))

    def InitializeComm(self):
        pass

    def Reset(self):
        pass

    def Clear(self):
        pass

    def ScreenOff(self):
        pass

    def ScreenOn(self):
        pass

    def SetBrightness(self, level: int = 25):
        pass

    def SetOrientation(self, orientation: Orientation = Orientation.PORTRAIT):
        pass

    def DisplayPILImage(
            self,
            image: Image,
            x: int = 0, y: int = 0,
            image_width: int = 0,
            image_height: int = 0
    ):
        width, height = self.get_width(), self.get_height()

        # If the image height/width isn't provided, use the native image size
        if not image_height:
            image_height = image.size[1]
        if not image_width:
            image_width = image.size[0]

        assert x <= width, 'Image X coordinate must be <= display width'
        assert y <= height, 'Image Y coordinate must be <= display height'
        assert image_height > 0, 'Image height must be > 0'
        assert image_width > 0, 'Image width must be > 0'

        # If our image size + the (x, y) position offsets are bigger than
        # our display, reduce the image size to fit our screen
        if x + image_width > width:
            image_width = width - x
        if y + image_height > height:
            image_height = height - y

        if image_width != image.size[0] or image_height != image.size[1]:
            image = image.crop((0, 0, image_width, image_height))

        (x0, y0) = (x, y)
        (x1, y1) = (x + image_width - 1, y + image_height - 1)

        # Send command BlockWrite with image size
        image_data = bytearray(x0.to_bytes(2))
        image_data += bytearray(x1.to_bytes(2))
        image_data += bytearray(y0.to_bytes(2))
        image_data += bytearray(y1.to_bytes(2))
        self.SendCommand(cmd=Command.BlockWrite, payload=image_data)

        # Send command intoPicMode to prepare bitmap data transmission
        self.SendCommand(Command.intopicMode)

        pix = image.load()
        line = bytes([80])

        # Lock queue mutex then queue all the requests for the image data
        with self.update_queue_mutex:
            for h in range(image_height):
                for w in range(image_width):
                    R = pix[w, h][0] >> 3
                    G = pix[w, h][1] >> 2
                    B = pix[w, h][2] >> 3

                    # Color information is 0bRRRRRGGGGGGBBBBB
                    # Revision A: Encode in Little-Endian (native x86/ARM encoding)
                    # Revition B: Encode in Big-Endian
                    rgb = (R << 11) | (G << 5) | B
                    line += struct.pack('>H', rgb)

                    # Send image data by multiple of 64 bytes + 1 command byte
                    if len(line) >= 65:
                        old_line = line[0:64]
                        self.SendLine(line[0:64])
                        line = bytes([80]) + line[64:]

            # Write last line if needed
            if len(line) > 0:
                self.SendLine(line)

        # Send command outpicMode to indicate the complete bitmap has been transmitted
        self.SendCommand(Command.outpicMode)
