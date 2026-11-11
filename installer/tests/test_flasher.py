#!/usr/bin/env python3
"""Offline FSM test: drive avrfix.flasher.Flasher.flash() against the coordinated fake unit and
assert it preserves the proven sequence (erase image -> update image -> start image), pushes the
image intact over TFTP, never sends a forbidden command, and that the shell whitelist refuses
forbidden commands before transmit. No real unit.

  /usr/bin/python3 -I installer/tests/test_flasher.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.dirname(HERE)
sys.path.insert(0, INSTALLER)
sys.path.insert(0, HERE)

from avrfix import shell                      # noqa: E402
from avrfix.flasher import Flasher            # noqa: E402
from fake_boot import FakeBootUnit            # noqa: E402


def test_flash_sequence():
    fake = FakeBootUnit().start()
    img = bytes(range(256)) * 20 + b"END"     # ~5 KB -> multiple TFTP blocks
    events = []
    fl = Flasher("127.0.0.1", img, src_ip="127.0.0.1",
                 tftp_port=fake.tftp_port, shell_port=fake.shell_port,
                 on_event=events.append)
    res = fl.flash()
    assert res.ok, f"flash failed: {res.detail}"
    assert fake.received == img, "pushed image mismatch"
    assert fake.commands == [b"erase image", b"update image", b"start image"], fake.commands
    assert fake.refused == [], f"a forbidden command reached the unit: {fake.refused}"
    assert fake.started_image
    return len(img), len(events)


def test_whitelist():
    fake = FakeBootUnit().start()
    sh = shell.Shell("127.0.0.1", fake.shell_port)
    assert sh.mode() == "boot", (sh.prompt, sh.mode())
    for bad in ("update bootloader", "erase webpage", "update webpage"):
        try:
            sh.send_cmd(bad)
            raise AssertionError(f"whitelist let {bad!r} through")
        except PermissionError:
            pass
    sh.close()
    assert fake.refused == [], f"a forbidden command reached the unit: {fake.refused}"


def main():
    n, nev = test_flash_sequence()
    test_whitelist()
    print(f"OK: flasher wrote {n} B in the correct erase->update->start sequence ({nev} events); "
          f"no forbidden command sent; shell whitelist refused all forbidden before transmit")


if __name__ == "__main__":
    main()
