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

import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, Tuple
import queue
import threading
import logging

from PIL import Image

from .lcd_comm import LcdComm, Orientation

logger = logging.getLogger(__name__)

SCREENSHOT_FILE = "screencap.png"
WEBSERVER_PORT = 5678


# This webserver offer a blank page displaying simulated screen with auto-refresh
class SimulatedLcdWebServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                bytes('<img src="' + SCREENSHOT_FILE + '" id="myImage" />', "utf-8")
            )
            self.wfile.write(bytes("<script>", "utf-8"))
            self.wfile.write(bytes("setInterval(function() {", "utf-8"))
            self.wfile.write(
                bytes(
                    "    var myImageElement = document.getElementById('myImage');",
                    "utf-8",
                )
            )
            self.wfile.write(
                bytes(
                    "    myImageElement.src = '"
                    + SCREENSHOT_FILE
                    + "?rand=' + Math.random();",
                    "utf-8",
                )
            )
            self.wfile.write(bytes("}, 250);", "utf-8"))
            self.wfile.write(bytes("</script>", "utf-8"))
        elif self.path.startswith("/" + SCREENSHOT_FILE):
            imgfile = open(SCREENSHOT_FILE, "rb").read()
            mimetype = mimetypes.MimeTypes().guess_type(SCREENSHOT_FILE)[0]
            self.send_response(200)
            if mimetype is not None:
                self.send_header("Content-type", mimetype)
            self.end_headers()
            self.wfile.write(imgfile)


# Simulated display: write on a file instead of serial port
class LcdSimulated(LcdComm):
    def __init__(
        self,
        com_port: str = "AUTO",
        display_width: int = 320,
        display_height: int = 480,
        update_queue: Optional[queue.Queue] = None,
    ):
        LcdComm.__init__(self, com_port, display_width, display_height, update_queue)
        self.screen_image = Image.new(
            "RGB", (self.width(), self.height()), (255, 255, 255)
        )
        self.screen_image.save("tmp", "PNG")
        shutil.copyfile("tmp", SCREENSHOT_FILE)
        self.orientation = Orientation.PORTRAIT

        try:
            self.webServer = HTTPServer(
                ("localhost", WEBSERVER_PORT), SimulatedLcdWebServer
            )
            logger.debug(
                "To see your simulated screen, open http://%s:%d in a browser"
                % ("localhost", WEBSERVER_PORT)
            )
            threading.Thread(target=self.webServer.serve_forever).start()
        except OSError:
            logger.error(
                "Error starting webserver! An instance might already be running on port %d."
                % WEBSERVER_PORT
            )

    def __del__(self):
        self.close_serial()

    @staticmethod
    def auto_detect_com_port() -> Optional[str]:
        return None

    def close_serial(self):
        logger.debug("Shutting down web server")
        self.webServer.shutdown()

    def initialize_comm(self):
        pass

    def reset(self):
        pass

    def clear(self):
        self.set_orientation(self.orientation)

    def screen_off(self):
        pass

    def screen_on(self):
        pass

    def set_brightness(self, level: int = 25):
        pass

    def set_backplate_led_color(
        self, led_color: Tuple[int, int, int] = (255, 255, 255)
    ):
        pass

    def set_orientation(self, orientation: Orientation = Orientation.PORTRAIT):
        self.orientation = orientation
        # Just draw the screen again with the new width/height based on orientation
        with self.update_queue_mutex:
            self.screen_image = Image.new(
                "RGB", (self.width(), self.height()), (255, 255, 255)
            )
            self.screen_image.save("tmp", "PNG")
            shutil.copyfile("tmp", SCREENSHOT_FILE)

    def paint(
        self,
        image: Image.Image,
        pos: Tuple[int, int] = (0, 0),
    ):
        image = self._crop_to_display_bounds(image, pos)
        image_width, image_height = image.size[0], image.size[1]

        if image_height == 0 or image_width == 0:
            return

        with self.update_queue_mutex:
            self.screen_image.paste(image, pos)
            self.screen_image.save("tmp", "PNG")
            shutil.copyfile("tmp", SCREENSHOT_FILE)
