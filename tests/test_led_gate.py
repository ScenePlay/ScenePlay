"""lighting.ledPlayer.is_raspberry_pi: which boxes may launch led_Run.py.

Pi 3/4/Zero 2: the classic rpi_ws281x path, always allowed.
Pi 5: its RP1 chip killed that path; NeoPixels work only through the RP1 PIO
block (Adafruit's Blinka Pi 5 driver), which the kernel exposes as /dev/pio0
once the firmware is current. So a Pi 5 is allowed exactly when /dev/pio0
exists — and the refusal says why, so the DM knows which step is missing."""
import lighting.ledPlayer as lp


def _cpuinfo(tmp_path, model):
    p = tmp_path / 'cpuinfo'
    p.write_text(f'processor\t: 0\nModel\t\t: {model}\n')
    return p


def test_pi4_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.platform, 'machine', lambda: 'aarch64')
    assert lp.is_raspberry_pi(cpuinfo=_cpuinfo(tmp_path, 'Raspberry Pi 4 Model B Rev 1.4'),
                              pio_dev=tmp_path / 'missing-pio0') is True


def test_pi5_without_pio_is_refused_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.platform, 'machine', lambda: 'aarch64')
    cpu = _cpuinfo(tmp_path, 'Raspberry Pi 5 Model B Rev 1.0')
    assert lp.is_raspberry_pi(cpuinfo=cpu, pio_dev=tmp_path / 'missing-pio0') is False
    why = lp.led_unavailable_reason(cpuinfo=cpu, pio_dev=tmp_path / 'missing-pio0')
    assert '/dev/pio0' in why and 'apt full-upgrade' in why


def test_pi5_with_pio_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.platform, 'machine', lambda: 'aarch64')
    pio = tmp_path / 'pio0'; pio.write_text('')
    cpu = _cpuinfo(tmp_path, 'Raspberry Pi 5 Model B Rev 1.0')
    assert lp.is_raspberry_pi(cpuinfo=cpu, pio_dev=pio) is True
    assert lp.led_unavailable_reason(cpuinfo=cpu, pio_dev=pio) == ''


def test_non_pi_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.platform, 'machine', lambda: 'x86_64')
    assert lp.is_raspberry_pi(cpuinfo=_cpuinfo(tmp_path, 'Raspberry Pi 5 Model B'), pio_dev=tmp_path / 'pio0') is False
    assert lp.is_raspberry_pi(cpuinfo=tmp_path / 'no-such-file', pio_dev=tmp_path / 'pio0') is False


# --- Blinka 10 "Install them? [Y/n]" prompt ---------------------------------
# Blinka 10 stopped installing its Pi backends as dependencies; it checks for
# them when `board` is imported and, on a TTY, stops to ask. led_Run.py is a
# headless child of the app, so nothing may ever wait on that question.

def test_launcher_gives_led_run_no_stdin(monkeypatch):
    import subprocess
    calls = []

    class _Done:
        def poll(self):
            return 0

    def fake_popen(cmd, **kw):
        calls.append((cmd, kw))
        return _Done()

    monkeypatch.setattr(lp, 'led_unavailable_reason', lambda: '')
    monkeypatch.setattr(lp.subprocess, 'Popen', fake_popen)
    assert lp.threaderLED() is True
    cmd, kw = calls[-1]
    assert cmd[-1].endswith('led_Run.py')
    assert kw.get('stdin') is subprocess.DEVNULL


def test_led_run_disables_blinka_prompt_before_importing_board(monkeypatch):
    import os
    import sys
    import types

    import pytest

    import led_Run
    seen = {}

    class _BoardFinder:
        # Records the env var at the moment `import board` actually runs.
        def find_spec(self, name, path=None, target=None):
            if name == 'board':
                seen['skip'] = os.environ.get('BLINKA_SKIP_DEPENDENCY_CHECK')
            return None

    fake_neopixel = types.ModuleType('neopixel')
    monkeypatch.delenv('BLINKA_SKIP_DEPENDENCY_CHECK', raising=False)
    monkeypatch.delitem(sys.modules, 'board', raising=False)
    monkeypatch.setitem(sys.modules, 'neopixel', fake_neopixel)
    monkeypatch.setattr(sys, 'meta_path', [_BoardFinder()] + sys.meta_path)
    monkeypatch.setattr(led_Run, 'active_config', lambda: (18, 4, 0.1))
    with pytest.raises(ImportError):    # no real `board` off-Pi
        led_Run.main()
    assert seen['skip'] == '1'
