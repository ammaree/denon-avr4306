#!/usr/bin/env python3
"""Offline end-to-end test of the push-based DM850I writer. No real unit.

  /usr/bin/python3 -I sim/test_dm850_writer.py

Checks, against sim/fake_dm850.py:
  1. TftpPush full write: the fake TFTP server receives the image intact via WRQ + DATA.
  2. TftpPush --probe-wrq: the fake sees the WRQ and ACKs block 0, but receives NO data
     (probe aborts with a TFTP ERROR). The writer reports ack0=True, complete=False.
  3. Shell: prompt `#` => mode 'boot'; erase image / update image / start tftp client each
     return `ok`; the command whitelist refuses every forbidden command before transmit, so
     the fake never sees one.
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, HERE)
import dm850_writer as W
from fake_dm850 import FakeTftpServer, FakeShell


def wait(cond, t=8.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_push_full():
    image = bytes(range(256)) * 9 + b'END'            # 2307 B -> 5 blocks (multi-block)
    srv = FakeTftpServer('127.0.0.1'); srv.start()
    res = W.TftpPush('127.0.0.1', 'DM850I_0011.bcd', image,
                     server_port=srv.port, src_ip='127.0.0.1').send(probe=False, log=lambda *a: None)
    assert wait(lambda: srv.received is not None), 'fake never stored a full image'
    assert srv.saw_wrq and srv.wrq_name == 'DM850I_0011.bcd', (srv.saw_wrq, srv.wrq_name)
    assert srv.received == image, 'pushed image mismatch'
    assert res['ack0'] and res['complete'], res
    return len(image), res['blocks_sent']


def test_push_probe():
    image = bytes(range(256)) * 9 + b'END'
    srv = FakeTftpServer('127.0.0.1'); srv.start()
    res = W.TftpPush('127.0.0.1', 'DM850I_0011.bcd', image,
                     server_port=srv.port, src_ip='127.0.0.1').send(probe=True, log=lambda *a: None)
    assert wait(lambda: srv.saw_wrq), 'fake never saw the WRQ'
    assert res['ack0'] is True, res
    assert res['complete'] is False, res
    assert srv.received is None, 'probe must write NO data'
    assert wait(lambda: srv.probe_abort), 'fake did not see the probe abort'


def test_shell_whitelist():
    fake = FakeShell()
    threading.Thread(target=fake.serve, args=('127.0.0.1', 0), daemon=True).start()
    assert wait(lambda: getattr(fake, 'port', None)), 'shell did not bind'
    sh = W.Shell('127.0.0.1', fake.port)
    assert sh.mode() == 'boot', (sh.prompt, sh.mode())
    for bad in ('update bootloader', 'erase webpage', 'update webpage'):
        try:
            sh.send_cmd(bad)
            raise AssertionError(f'whitelist let {bad!r} through')
        except PermissionError:
            pass
    for good in ('erase image', 'update image', 'start tftp client'):
        r = sh.send_cmd(good, expect=b'ok', timeout=5)
        assert b'ok' in r.lower(), (good, r)
    sh.close()
    assert fake.refused == [], f'a forbidden command reached the unit: {fake.refused}'
    assert [c for c in fake.commands] == [b'erase image', b'update image', b'start tftp client'], \
        fake.commands


def main():
    n, blocks = test_push_full()
    test_push_probe()
    test_shell_whitelist()
    allowed = W.accepted_shas()
    print(f'OK: push delivered {n} B in {blocks} blocks (WRQ+DATA); probe ACKed block 0 and '
          f'wrote nothing; shell `#`=boot, erase/update/start-tftp -> ok, whitelist refused all '
          f'forbidden; {len(allowed)} pinned image sha(s)')


if __name__ == '__main__':
    main()
