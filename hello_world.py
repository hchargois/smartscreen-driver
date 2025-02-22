#!/usr/bin/env python
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

# This file is a simple Python test program using the library code to display custom content on screen (see README)

import os
import signal
import sys
import time
import logging

from PIL import Image, ImageDraw

# Import only the modules for LCD communication
from smartscreen_driver.lcd_comm_rev_a import LcdCommRevA, Orientation
from smartscreen_driver.lcd_comm_rev_b import LcdCommRevB
from smartscreen_driver.lcd_comm_rev_c import LcdCommRevC
from smartscreen_driver.lcd_comm_rev_d import LcdCommRevD
from smartscreen_driver.lcd_simulated import LcdSimulated

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Set your COM port e.g. COM3 for Windows, /dev/ttyACM0 for Linux, etc. or "AUTO" for auto-discovery
# COM_PORT = "/dev/ttyACM0"
# COM_PORT = "COM5"
COM_PORT = "AUTO"

# Display revision:
# - A      for Turing 3.5" and UsbPCMonitor 3.5"/5"
# - B      for Xuanfang 3.5" (inc. flagship)
# - C      for Turing 5"
# - D      for Kipye Qiye Smart Display 3.5"
# - SIMU   for 3.5" simulated LCD (image written in screencap.png)
# - SIMU5  for 5" simulated LCD
# To identify your smart screen: https://github.com/mathoudebine/turing-smart-screen-python/wiki/Hardware-revisions
REVISION = "A"

stop = False


def sighandler(signum, frame):
    global stop
    stop = True


# Set the signal handlers, to send a complete frame to the LCD before exit
signal.signal(signal.SIGINT, sighandler)
signal.signal(signal.SIGTERM, sighandler)
is_posix = os.name == "posix"
if is_posix:
    signal.signal(signal.SIGQUIT, sighandler)

# Build your LcdComm object based on the HW revision
lcd_comm = None

try:
    if REVISION == "A":
        logger.info(
            'Selected Hardware Revision A (Turing Smart Screen 3.5" & UsbPCMonitor 3.5"/5")'
        )
        # NOTE: If you have UsbPCMonitor 5" you need to change the width/height to 480x800 below
        lcd_comm = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    elif REVISION == "B":
        logger.info(
            'Selected Hardware Revision B (XuanFang screen 3.5" version B / flagship)'
        )
        lcd_comm = LcdCommRevB(com_port=COM_PORT)
    elif REVISION == "C":
        logger.info('Selected Hardware Revision C (Turing Smart Screen 5")')
        lcd_comm = LcdCommRevC(com_port=COM_PORT)
    elif REVISION == "D":
        logger.info('Selected Hardware Revision D (Kipye Qiye Smart Display 3.5")')
        lcd_comm = LcdCommRevD(com_port=COM_PORT)
    elif REVISION == "SIMU":
        logger.info('Selected 3.5" Simulated LCD')
        lcd_comm = LcdSimulated(display_width=320, display_height=480)
    elif REVISION == "SIMU5":
        logger.info('Selected 5" Simulated LCD')
        lcd_comm = LcdSimulated(display_width=480, display_height=800)
    else:
        logger.error("Unknown revision")
        sys.exit(1)
except Exception as e:
    logger.error(f"Failed to initialize LCD: {e}")
    sys.exit(1)

# Reset screen in case it was in an unstable state (screen is also cleared)
lcd_comm.reset()

# Send initialization commands
lcd_comm.initialize_comm()

# Set brightness in % (warning: revision A display can get hot at high brightness! Keep value at 50% max for rev. A)
lcd_comm.set_brightness(level=10)

# Set backplate RGB LED color (for supported HW only)
lcd_comm.set_backplate_led_color(led_color=(255, 255, 255))

# Set orientation (screen starts in Portrait)
lcd_comm.set_orientation(orientation=Orientation.LANDSCAPE)

# Display sample text
img = Image.new("RGB", lcd_comm.size(), (0, 0, 0))
draw = ImageDraw.Draw(img)
draw.text((0, 0), "Hello world!", font_size=48, fill=(255, 255, 255))
lcd_comm.paint(img)

while not stop:
    time.sleep(1)

lcd_comm.screen_off()
lcd_comm.clear()

# Close serial connection at exit
lcd_comm.close_serial()
