#!/usr/bin/env python3
"""Tests for the added loader_client.py tools against sim/fake_unit.py:
status, settings-save, settings-restore, verify (flash + dm), rollback, and the session log.
The MAIN write path itself is covered by sim/test_main_write.py.

  python3 -I sim/test_tools.py \
      build/images/MAIN_01.00.flash.bin build/patch/MAIN_dm.flash.bin
"""
import hashlib, importlib.util, json, os, socket, subprocess, sys, tempfile

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


def ram_byte(addr):                 # the fake's seeded RAM pattern
    return (addr * 13 + 5) & 0xFF


SETTINGS = bytes(ram_byte(a) for a in range(lc.SETTINGS_START, lc.SETTINGS_END + 1))
DM_BLOCKS = bytes((x * 7 + 3) & 0xFF for x in range(0xFFC000, 0x1000000))  # fake DM pattern


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
        for _ in range(100):
            if b'fake unit on' in self.p.stdout.readline():
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


def run(fake, cmd, *extra, timeout=60):
    """Run one loader_client subcommand against the fake. Returns (rc, output, session_log)."""
    d = tempfile.mkdtemp()
    slog = os.path.join(d, 'session-log.jsonl')
    port = getattr(fake, 'port', 0)
    argv = [sys.executable, '-I', CLIENT, cmd, '--ip', '127.0.0.1',
            '--control-port', str(port), '--loader-port', str(port),
            '--delay', '0', '--log', os.path.join(d, 'loader.log'),
            '--session-log', slog, *extra]
    r = subprocess.run(argv, capture_output=True, cwd=d, timeout=timeout)
    events = []
    if os.path.exists(slog):
        events = [json.loads(x) for x in open(slog) if x.strip()]
    return r.returncode, (r.stdout + r.stderr).decode('latin1', 'replace'), events


def tmpfile(data=b''):
    p = tempfile.NamedTemporaryFile(suffix='.bin', delete=False).name
    open(p, 'wb').write(data)
    return p


# ---------------------------------------------------------------------------- tests ---
def test_status(image):
    with Fake(image) as fk:                           # normal mode (not update)
        rc, out, ev = run(fk, 'status', timeout=30)
    check('status: exit 0', rc == 0, out[-300:])
    check('status: shows parsed versions', 'versions:' in out and 'MAIN' in out, out[-300:])
    check('status: reports normal mode', 'normal' in out, out[-200:])
    check('status: session log has start+end',
          any(e['kind'] == 'start' for e in ev) and any(e['kind'] == 'end' for e in ev))


def test_settings_save(image):
    out_bin = tmpfile()
    with Fake(image, start_update=True) as fk:
        rc, out, ev = run(fk, 'settings-save', '--in-update-mode', '--confirm-update-mode',
                          '--out', out_bin)
    check('settings-save: exit 0', rc == 0, out[-300:])
    got = open(out_bin, 'rb').read()
    check('settings-save: size = 0x22F6 (8950)', len(got) == lc.SETTINGS_SIZE, str(len(got)))
    check('settings-save: body = RAM 0x040C-0x2701', got == SETTINGS)
    check('settings-save: X+RBNORM exit confirmed', 'RBNORM confirmed' in out, out[-200:])
    check('settings-save: session log records the artifact + sha',
          any(e['kind'] == 'settings-save' and e.get('sha256') == hashlib.sha256(got).hexdigest()
              for e in ev))


def test_settings_save_refusals(image):
    with Fake(image, start_update=True) as fk:
        rc, out, _ = run(fk, 'settings-save')          # no --confirm-update-mode
    check('settings-save: refused without --confirm-update-mode',
          rc != 0 and 'confirm-update-mode' in out, out[-200:])


def test_settings_restore_roundtrip(image):
    # A distinct settings body (not the seeded pattern) so the round-trip is meaningful.
    body = bytes((i * 7 + 1) & 0xFF for i in range(lc.SETTINGS_SIZE))
    src = tmpfile(body)
    got_bin = tmpfile()
    with Fake(image, start_update=True, write_out=got_bin) as fk:
        rc, out, ev = run(fk, 'settings-restore', '--image', src,
                          '--in-update-mode', '--confirm-restore')
    check('settings-restore: exit 0', rc == 0, out[-300:])
    got = open(got_bin, 'rb').read() if os.path.exists(got_bin) else b''
    check('settings-restore: RAM 0x040C-0x2701 received exactly', got == body,
          f'{len(got)} vs {len(body)}')
    check('settings-restore: model guard ran', '0x0011 confirmed' in out, out[-200:])
    check('settings-restore: data frames are D, not P',
          'D frames' in out and 'P frames' not in out, out[-300:])
    check('settings-restore: X acknowledged before RBNORM',
          'X(1,2,1) acknowledged' in out and 'RBNORM confirmed' in out, out[-300:])
    check('settings-restore: SSManage 5 s ACK and exit waits',
          lc.SETTINGS_ACK_SECS == 5.0 and lc.EXIT_WAIT == 5.0)
    check('settings-restore: logged start+done',
          any(e['kind'] == 'settings-restore-start' for e in ev)
          and any(e['kind'] == 'settings-restore-done' for e in ev))


def test_settings_restore_refusals(image):
    with Fake(image, start_update=True) as fk:
        rc, out, _ = run(fk, 'settings-restore', '--image', tmpfile(b'\x00' * 100),
                         '--in-update-mode', '--confirm-restore')
        check('settings-restore: wrong size refused', rc != 0 and '8950' in out, out[-200:])
        rc, out, _ = run(fk, 'settings-restore', '--image', tmpfile(SETTINGS),
                         '--in-update-mode')            # no --confirm-restore
        check('settings-restore: refused without --confirm-restore',
              rc != 0 and 'confirm-restore' in out, out[-200:])


def test_verify_flash(vendor, patch):
    with Fake(patch, start_update=True) as fk:
        rc, out, ev = run(fk, 'verify', '--against', patch, '--source', 'flash',
                          '--in-update-mode', '--confirm-update-mode')
    check('verify flash (match): exit 0', rc == 0, out[-300:])
    check('verify flash (match): MATCH', 'MATCH' in out and 'MISMATCH' not in out, out[-200:])
    check('verify flash: session log result=match',
          any(e['kind'] == 'verify' and e.get('result') == 'match' for e in ev))
    with Fake(patch, start_update=True) as fk:          # unit has patch, compare to vendor
        rc, out, ev = run(fk, 'verify', '--against', vendor, '--source', 'flash',
                          '--in-update-mode', '--confirm-update-mode')
    check('verify flash (mismatch): exit != 0', rc != 0, out[-200:])
    check('verify flash (mismatch): MISMATCH + first difference',
          'MISMATCH' in out and 'first difference' in out, out[-200:])


def test_verify_dm(image):
    ref = tmpfile(DM_BLOCKS)
    with Fake(image, dm=True) as fk:                    # normal mode, DM patch answers
        rc, out, ev = run(fk, 'verify', '--against', ref, '--source', 'dm',
                          '--range', '0xFFC000:0xFFFFFF', timeout=30)
    check('verify dm (match): exit 0', rc == 0, out[-300:])
    check('verify dm (match): MATCH', 'MATCH' in out and 'MISMATCH' not in out, out[-200:])


def test_rollback(vendor, patch):
    got_bin = tmpfile()
    with Fake(vendor, start_update=True, write_out=got_bin) as fk:
        rc, out, ev = run(fk, 'rollback', '--image', vendor,
                          '--in-update-mode', '--confirm-write', timeout=120)
    check('rollback (vendor image): exit 0', rc == 0, out[-300:])
    check('rollback: announced + verify OK', 'ROLLBACK' in out and 'verify OK' in out, out[-300:])
    check('rollback: fake received the vendor image byte-exact',
          os.path.exists(got_bin) and open(got_bin, 'rb').read() == open(vendor, 'rb').read())
    check('rollback: session log flagged the MAIN cycle',
          any(e['kind'] == 'flash-write-start' and 'MAIN flash cycle' in e.get('note', '')
              for e in ev))
    # rollback refuses the patch image (only the vendor image is a rollback)
    with Fake(patch, start_update=True) as fk:
        rc, out, _ = run(fk, 'rollback', '--image', patch,
                         '--in-update-mode', '--confirm-write')
    check('rollback: refuses the patch image',
          rc != 0 and 'not the vendor MAIN 01.00' in out, out[-200:])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    vendor, patch = (args + [os.path.join(ROOT, 'build/images/MAIN_01.00.flash.bin'),
                             os.path.join(ROOT, 'build/patch/MAIN_dm.flash.bin')])[:2]
    vendor, patch = os.path.abspath(vendor), os.path.abspath(patch)
    for p in (vendor, patch):
        if not os.path.exists(p):
            sys.exit(f'missing image {p} (build it first; see docs/main-dump-patch.md)')

    test_status(vendor)
    test_settings_save(vendor)
    test_settings_save_refusals(vendor)
    test_settings_restore_roundtrip(vendor)
    test_settings_restore_refusals(vendor)
    test_verify_flash(vendor, patch)
    test_verify_dm(patch)
    test_rollback(vendor, patch)

    print(f'\nFAILURES: {fails}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
