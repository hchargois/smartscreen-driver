# smartscreen-driver

This package contains drivers for low-cost serial-over-USB displays such as
the Turing Smart Screen.

This library is simply an extract of the driver code from the
[turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python)
project, removing all the sensors and UI code and dependencies, fixing coding
conventions violations (PEP8 et al) and adding proper Python packaging.

The usage is straightforward:

- you open the connection with the correct `LcdCommRevX` depending on your display
- you `paint()` (PIL) images to the display

See `hello_world.py` for an example.
