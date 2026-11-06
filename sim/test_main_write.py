#!/usr/bin/env python3
"""Tests for the MAIN-only writer (tools/loader_client.py write) against sim/fake_unit.py.

Two parts:
  A. In-process frame checks: frame_l / frame_p build exactly the vendor L / P bytes
     (docs/loader-interface.md §2.8), refuse non-MAIN targets, and the offline gate is
     the two sha256-pinned images.
  B. Integration: start the fake unit, run `write` end to end, and check it writes every
     byte, the read-back verify passes, and the fake's dumped image equals the input.
     Also: write retries past NACKed frames; the full VI?/RBUPDATE update-mode entry;
     and the safety refusals (wrong image, no --confirm-write, non-MAIN target, port 5001).

  python3 -I sim/test_main_write.py \
      build/images/MAIN_01.00.flash.bin build/patch/MAIN_dm.flash.bin [--slow]

--slow adds the real update-mode-entry test (≈17 s: the vendor 15 s settle).
"""
import hashlib, importlib.util, os, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(ROOT, 'tools', 'loader_client.py')
FAKE = os.path.join(ROOT, 'sim', 'fake_unit.py')

spec = importlib.util.spec_from_file_location('loader_client', CLIENT)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

fails = 0


def check(name, ok, detail=''):
    global fails
    fails += not ok
    print(f'{"ok  " if ok else "FAIL"} {name}' + (f'   {detail}' if detail and not ok else ''))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- part A: frame bytes ---
def test_frames():
    f = lc.frame_l(0xF00000, 0xFFBFFF)
    want = bytes.fromhex('aa4c0100') + bytes.fromhex('0100') \
        + (0xF00000).to_bytes(4, 'big') + (0xFFBFFF).to_bytes(4, 'big')
    want += bytes([lc.ck(want)])
    check('L frame = AA 4C 01 00 0100 F00000 FFBFFF ck', f == want, f.hex())
    check('L frame is 15 bytes', len(f) == 15, str(len(f)))
    check('L checksum = low byte of sum of first 14', f[-1] == sum(f[:-1]) & 0xFF)

    payload = bytes(range(256)) * 4            # 0x400 bytes
    p = lc.frame_p(1, 0xF00000, payload)
    check('P header = AA 50 01 status len16 addr32',
          p[:10] == bytes([0xAA, 0x50, 0x01, 0x01]) + (0x400).to_bytes(2, 'big')
          + (0xF00000).to_bytes(4, 'big'), p[:10].hex())
    check('P frame length = payload + 11', len(p) == 0x400 + 11, str(len(p)))
    check('P payload intact', p[10:-1] == payload)
    check('P checksum = low byte of sum of all prior', p[-1] == sum(p[:-1]) & 0xFF)
    check('P status: first=1 middle=2 last=3',
          lc.frame_p(2, 0xF00400, payload)[3] == 2 and lc.frame_p(3, 0, payload)[3] == 3)

    for fn in (lambda: lc.frame_l(0xF00000, 0xFFBFFF, tgt=2),
               lambda: lc.frame_p(1, 0xF00000, payload, tgt=0x0A)):
        try:
            fn()
            check('non-MAIN target refused', False, 'no exception')
        except ValueError:
            check('non-MAIN target refused', True)

    try:
        lc.frame_p(1, 0, bytes(0x401))
        check('P payload over 0x400 refused', False)
    except ValueError:
        check('P payload over 0x400 refused', True)

    check('offline gate: exactly two accepted images', len(lc.ACCEPTED_IMAGES) == 2)
    check('read-only frame() still refuses L', _refuses(lambda: lc.frame(b'L', 1)))
    check('read-only frame() still refuses P', _refuses(lambda: lc.frame(b'P', 1)))


def _refuses(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


# --------------------------------------------------------------- part B: integration ---
class Fake:
    def __init__(self, image, **opts):
        self.port = free_port()
        self.telnet = free_port()
        self.write_out = opts.pop('write_out', None)
        cmd = [sys.executable, '-I', FAKE, '--image', image,
               '--loader-port', str(self.port), '--telnet-port', str(self.telnet)]
        for k, v in opts.items():
            flag = '--' + k.replace('_', '-')
            cmd += [flag] if v is True else [flag, str(v)]
        if self.write_out:
            cmd += ['--write-out', self.write_out]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):                   # wait for the listening banner
            line = self.p.stdout.readline()
            if b'fake unit on' in line:
                return
        raise RuntimeError('fake unit did not start')

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.p.terminate()
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.kill()


def run_write(fake, image, *extra, timeout=120):
    log = tempfile.NamedTemporaryFile(suffix='.log', delete=False).name
    cmd = [sys.executable, '-I', CLIENT, 'write', '--ip', '127.0.0.1',
           '--control-port', str(fake.port), '--loader-port', str(fake.port),
           '--image', image, '--delay', '0', '--log', log, *extra]
    r = subprocess.run(cmd, capture_output=True, cwd=tempfile.gettempdir(), timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode('latin1', 'replace')


def test_write(image, label):
    out = tempfile.NamedTemporaryFile(suffix='.bin', delete=False).name
    with Fake(image, start_update=True, write_out=out) as fk:
        rc, log = run_write(fk, image, '--in-update-mode', '--confirm-write')
    check(f'write {label}: exit 0', rc == 0, log[-400:])
    check(f'write {label}: verify OK reported', 'verify OK' in log, log[-400:])
    want = open(image, 'rb').read()
    got = open(out, 'rb').read() if os.path.exists(out) else b''
    check(f'write {label}: fake received the exact image', got == want,
          f'{len(got)} vs {len(want)} bytes')
    check(f'write {label}: sha256 of received == image',
          hashlib.sha256(got).hexdigest() == hashlib.sha256(want).hexdigest())


def test_retry(image):
    out = tempfile.NamedTemporaryFile(suffix='.bin', delete=False).name
    with Fake(image, start_update=True, nack=200, write_out=out) as fk:
        rc, log = run_write(fk, image, '--in-update-mode', '--confirm-write')
    check('write with NACKed frames: exit 0 (retries win)', rc == 0, log[-400:])
    check('write with NACKed frames: retry logged or verify OK',
          'verify OK' in log, log[-300:])
    check('write with NACKed frames: image still exact',
          os.path.exists(out) and open(out, 'rb').read() == open(image, 'rb').read())


def test_full_update_entry(image):
    # No --start-update on the fake, no --in-update-mode on the client: the client must
    # do VI? -> RBUPDATE -> RBSTART -> 15 s before writing.
    out = tempfile.NamedTemporaryFile(suffix='.bin', delete=False).name
    with Fake(image, write_out=out) as fk:
        rc, log = run_write(fk, image, '--confirm-write', timeout=60)
    check('full update-mode entry: exit 0', rc == 0, log[-400:])
    check('full update-mode entry: RBSTART seen', 'update mode' in log, log[-400:])
    check('full update-mode entry: verify OK', 'verify OK' in log, log[-300:])


def test_refusals(image):
    # wrong image (bad sha256)
    bad = tempfile.NamedTemporaryFile(suffix='.bin', delete=False).name
    open(bad, 'wb').write(os.urandom(lc.MAIN_SIZE))
    with Fake(image, start_update=True) as fk:
        rc, log = run_write(fk, bad, '--in-update-mode', '--confirm-write')
        check('refuse: unaccepted image', rc != 0 and 'not an accepted MAIN image' in log, log[-200:])
        # missing --confirm-write prints the checklist and refuses
        rc, log = run_write(fk, image, '--in-update-mode')
        check('refuse: no --confirm-write', rc != 0 and 'checklist' in log.lower(), log[-200:])
        # non-MAIN target
        rc, log = run_write(fk, image, '--in-update-mode', '--confirm-write', '--target', '2')
        check('refuse: target != 1', rc != 0 and 'only target 1' in log, log[-200:])
    # port 5001 is refused before any connection
    rc, log = run_write(type('F', (), {'port': 5001})(), image,
                        '--in-update-mode', '--confirm-write', '--loader-port', '5001')
    check('refuse: loader port 5001', rc != 0 and '5001' in log, log[-200:])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    slow = '--slow' in sys.argv
    vendor, patch = (args + [os.path.join(ROOT, 'build/images/MAIN_01.00.flash.bin'),
                             os.path.join(ROOT, 'build/patch/MAIN_dm.flash.bin')])[:2]
    vendor, patch = os.path.abspath(vendor), os.path.abspath(patch)
    for p in (vendor, patch):
        if not os.path.exists(p):
            sys.exit(f'missing image {p} (build it first; see docs/main-dump-patch.md)')

    print('== part A: frame bytes ==')
    test_frames()
    print('\n== part B: integration against the fake unit ==')
    test_write(patch, 'DM-patch image')
    test_write(vendor, 'vendor rollback image')
    test_retry(patch)
    test_refusals(patch)
    if slow:
        print('   (--slow) full update-mode entry, includes the vendor 15 s settle...')
        test_full_update_entry(patch)
    else:
        print('   (skipping the ~17 s full update-mode-entry test; pass --slow to run it)')

    print(f'\nFAILURES: {fails}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
