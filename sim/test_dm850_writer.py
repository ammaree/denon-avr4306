#!/usr/bin/env python3
"""Offline end-to-end test of the DM850I writer against the fake DM850 bootloader.

  python3 -I sim/test_dm850_writer.py

Drives the writer's TFTP server + port-5001 shell client against sim/fake_dm850.py: the fake
pulls the served image over TFTP and records the commands it saw. Asserts the image bytes
arrive intact, the right commands are sent in order, no forbidden command is ever sent, and
the command whitelist rejects a forbidden one. No real unit involved.
"""
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, HERE)
import dm850_writer as W
from fake_dm850 import FakeDm850


def wait(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def main():
    name = 'DM850I_0011.bcd'
    image = bytes(range(256)) * 9 + b'END'   # 2307 bytes -> 5 TFTP blocks (tests multi-block)

    # the writer's TFTP server, serving the image under `name`
    tftp = W.TftpServer(name, image, host='127.0.0.1')
    tftp.start()

    # the fake DM850 bootloader, which will pull from the writer's TFTP server
    fake = FakeDm850(tftp_server=('127.0.0.1', tftp.port), image_name=name)
    threading.Thread(target=fake.serve, args=('127.0.0.1', 0), daemon=True).start()
    assert wait(lambda: getattr(fake, 'port', None)), 'fake did not bind'

    # the writer's 5001 shell client talks to the fake
    sh = W.Shell('127.0.0.1', fake.port)

    # the command whitelist must refuse a forbidden command outright
    for bad in ('update bootloader', 'erase webpage', 'update webpage', 'erase image'):
        try:
            sh.send_cmd(bad)
            raise AssertionError(f'whitelist let {bad!r} through')
        except PermissionError:
            pass

    # the real orchestration: update image (fake pulls via TFTP) then start image
    sh.send_cmd('update image')
    assert wait(lambda: fake.received is not None), 'fake never pulled the image'
    sh.send_cmd('start image')
    sh.close()

    assert fake.received == image, 'TFTP-delivered image does not match'
    assert tftp.served, 'TFTP server did not serve'
    assert b'update image' in fake.commands and b'start image' in fake.commands, fake.commands
    assert fake.commands.index(b'update image') < fake.commands.index(b'start image'), 'order'
    assert fake.refused == [], f'a forbidden command reached the unit: {fake.refused}'
    assert fake.started_image

    # the served-image sha whitelist (reads the real build files if present)
    allowed = W.accepted_shas()
    tftp.stop()
    print(f'OK: image {len(image)} B delivered intact over TFTP; commands {fake.commands}; '
          f'whitelist refused all forbidden; {len(allowed)} accepted image sha(s)')


if __name__ == '__main__':
    main()
