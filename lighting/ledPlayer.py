"""Local RPiLED playback: (re)launch led_Run.py for the payload waiting in
the tblLED mailbox. Pi-only — every other platform returns False and the
caller carries on (Remote boxes and the relay are pushed separately)."""
import os
import platform
import subprocess
import time
from pathlib import Path


CPUINFO = Path('/proc/cpuinfo')
PIO_DEV = Path('/dev/pio0')     # RP1 PIO block — the Pi 5's only NeoPixel route
PI5_FIRMWARE_HINT = ('LEDs are off on this Raspberry Pi 5: /dev/pio0 is missing. NeoPixels on a '
                     'Pi 5 run through the RP1 PIO block, which needs a current Raspberry Pi OS '
                     'kernel — run "sudo apt update && sudo apt full-upgrade -y" and reboot, then '
                     'check "ls -l /dev/pio0". (requirements.sh installs the Pi 5 driver itself.)')


def _model(cpuinfo: Path) -> str:
    try:
        return cpuinfo.read_text()
    except OSError:
        return ''


def led_unavailable_reason(cpuinfo: Path = CPUINFO, pio_dev: Path = PIO_DEV) -> str:
    """'' when this box can drive a NeoPixel strip, else one sentence saying why
    not. Pi 3/4/Zero 2 use the classic rpi_ws281x path. The Pi 5's RP1 chip
    broke that path; it drives the strip through RP1's PIO block (Adafruit's
    Blinka Pi 5 driver, same neopixel.NeoPixel() call), which the kernel
    exposes as /dev/pio0 only once the firmware is current."""
    info = _model(cpuinfo)
    if not info or platform.machine() not in ('armv7l', 'armv6l', 'aarch64'):
        return 'not a Raspberry Pi'
    if 'Raspberry Pi 5' in info and not pio_dev.exists():
        return PI5_FIRMWARE_HINT
    return ''


def is_raspberry_pi(cpuinfo: Path = CPUINFO, pio_dev: Path = PIO_DEV) -> bool:
    """True on a Pi that can drive a NeoPixel strip (see led_unavailable_reason)."""
    return led_unavailable_reason(cpuinfo, pio_dev) == ''


_warned = set()


def threaderLED():
    """Kill any running led_Run.py and start a fresh one on the mailbox
    payload. Returns True if a launch happened."""
    why = led_unavailable_reason()
    if why:
        if why != 'not a Raspberry Pi' and why not in _warned:
            _warned.add(why)            # once per process, not once per scene
            print('[led] ' + why)
        return False
    s = subprocess.Popen(['sudo', 'pkill', '-9', '-f', 'led_Run.py'])
    while s.poll() is None:
        time.sleep(1 / 100)
    import core.config as _config
    script = os.path.join(_config.ROOT, 'led_Run.py')
    subprocess.Popen(['sudo', 'python3', script])
    return True
