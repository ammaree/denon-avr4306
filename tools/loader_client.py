#!/usr/bin/env python3
"""Read-only client for the AVR-4306 MAIN loader protocol.

Protocol decompiled from the 6.0.0.4 updater (docs/loader-interface.md §2.4–2.6):
TCP 5000 carries both control-protocol lines (`VI?`, `RBUPDATE`) and raw AA-framed loader
frames, bridged by the DM850 to MAIN; telnet TCP 23 also answers `VI?`. The vendor update
order (FUN_00407C60) is: 5000 `VI?` -> 5000 `RBUPDATE`/`RBSTART` -> wait 15 s -> 5000 `C`.
TCP 5001 is the DM850 bootloader channel; this tool refuses it.

  frame   = AA <type> <target> ... <ck>        ck = low byte of the sum of all prior bytes
  C       = AA 'C' tgt ck                       connect / target info (reply type 'C')
  S       = AA 'S' tgt sub start32 end32 ck     read memory (BE); reply ACK, then data
                                                frames. On the unit (MAIN 01.00, 2026-11-05)
                                                start/end are ignored: sub 0 streams flash
                                                0xF00000-0xFFBFFF, sub 1 streams RAM
                                                0x0400-0xC3FF. Blocks 0-2 are not reachable.
  data    = AA 'D'|'P' tgt status len16 addr32 payload ck
            status 0 = only, 1 = first, 2 = middle, 3 = last frame
  A / N   = AA 'A'|'N' tgt ck                   ACK / NACK from the PC after each data frame

SAFETY (docs/safety-plan.md): the read-only frame builder `frame()` can only produce C, S,
A and N frames. L (load/erase) and P (data) are built only by `write` (frame_l/frame_p),
which this module exposes as a separate, explicitly gated MAIN-only command (Option C,
docs/main-dump-patch.md §5). Nothing here sends DM850 loader commands, RBNORM, or any
state-changing control command, and every builder forces target 1 (MAIN). `S`/`L`/`P` are
sent only after the unit has answered RBUPDATE with RBSTART. Port 5001 (the DM850
bootloader channel) is refused. Every connection is opened one at a time, with a delay,
because the DM850 hangs under fast connection churn (docs/lan-access.md).

`write` enforces its own offline gate: the image must be one of two sha256-pinned files
(the DM-dump patch build, or vendor 01.00 for rollback), exactly 0xFC000 bytes, and
--confirm-write must be given after the docs/safety-plan.md per-write checklist is done.
Never run `write` against the real unit without that checklist.

Commands:
  loader_client.py version --ip IP               'VI?' on the control port (default 5000;
                                                 23 also works), normal mode, read-only
  loader_client.py check   --ip IP               'C' frame on port 5000. Answered only in
                                                 update mode: the vendor sends it only when
                                                 'VI?' fails. No reply in normal mode is
                                                 expected (seen on the unit 2026-11-05).
  loader_client.py read    --ip IP [--range A:B ...] --confirm-update-mode
        VI?, RBUPDATE -> RBSTART, wait 15 s, then C and one S per range on port 5000;
        saves what each S returns to dumps/, named by the addresses actually received,
        with a sha256. Default: --sub 1, range 0x0400:0x2701 (SSManage's settings read;
        returns all RAM, settings at 0x040C-0x2701). --sub 0 returns the application
        flash. --in-update-mode skips VI?/RBUPDATE for a unit not yet power-cycled.
        Afterwards the unit must be power-cycled (vendor procedure).
  loader_client.py dmdump  --ip IP [--range A:B]  normal mode; needs the DM patch in MAIN
        (docs/main-dump-patch.md). Sends 'DMaaaaaa?' per 32 bytes on the control port,
        default range 0xFFC000:0xFFFFFF (blocks 0-2). No update mode, no power cycle.
  loader_client.py write   --ip IP --image PATH --confirm-write
        MAIN-only firmware write (Option C, docs/main-dump-patch.md §5), the vendor L/P
        sequence copied from docs/loader-interface.md §2.8. Enters update mode (VI?,
        RBUPDATE/RBSTART, 15 s) unless --in-update-mode, sends L for 0xF00000-0xFFBFFF
        then 1008 P frames of 0x400 bytes, then reads the whole application flash back
        (S sub 0) and checks it byte-for-byte against the image. The image must be one of
        the two accepted files (sha256-pinned). Afterwards the unit must be power-cycled.

Run with python3 -I. --control-port / --loader-port exist for the local test peer
(sim/fake_unit.py).
"""
import argparse, datetime, hashlib, os, re, socket, sys, time

ALLOWED_TYPES = {b'C', b'S', b'A', b'N'}     # frames the read-only builder may send
REFUSED_PORTS = {5001}                       # DM850 bootloader commands (FUN_004090A0)
UPDATE_SETTLE = 15.0                         # vendor wait after RBSTART (0x408137)
MAX_READ = 0x400000
# SSManage's settings read S(1, 1, 0x0400, 0x2701) (update-tools.md §3a).
DEFAULT_RANGES = [(0x0400, 0x2701)]
DATA_TYPES = (ord('D'), ord('P'))

# ---- write side (MAIN only). Exactly the vendor L/P sequence (loader-interface §2.8). ----
MAIN_TARGET = 1
MAIN_START, MAIN_END = 0xF00000, 0xFFBFFF    # application range (blocks 3-20); image file
MAIN_SIZE = MAIN_END - MAIN_START + 1        # 0xFC000 = 1,032,192 B = 1008 x 0x400
MAIN_VERSION = 0x0100                        # 'L' version word for "01.00" (vendor value)
P_CHUNK = 0x400                              # MAIN payload per P frame (target 1)
L_ACK_SECS = 10.0                            # 'L' ACK timeout (FUN_0041a070 local_4 = 10)
P_ACK_FIRST_LAST = 60.0                      # first (erase) and last frame (0x3c)
P_ACK_MIDDLE = 6.0                           # middle frames
FRAME_RETRIES = 3                            # vendor: initial send + up to 3 retries
# Offline gate (safety-plan): the only images `write` may send to MAIN. sha256 -> label.
ACCEPTED_IMAGES = {
    '9470fa599734b8341cbfae37617702e7f17be8228e622f63a0b5ca5fc2f31a96':
        'MAIN 01.00 + read-only DM-dump patch (build/patch/MAIN_dm.flash.bin)',
    '0fcc83501f19dd4f4356ed2120eafaa82d83fc7e7628dab6625867e9e9922d6b':
        'MAIN 01.00 vendor, unpatched (rollback, build/images/MAIN_01.00.flash.bin)',
}


def ck(b):
    return sum(b) & 0xFF


def frame(ftype, tgt, body=b''):
    if ftype not in ALLOWED_TYPES:
        raise ValueError(f'refused: frame type {ftype!r} is not read-only')
    f = b'\xAA' + ftype + bytes([tgt]) + body
    return f + bytes([ck(f)])


def parse_range(s):
    start, end = (int(x, 0) for x in s.split(':'))
    return start, end


def frame_s(tgt, start, end, sub=0):
    # sub 0: MAIN 01.00's loader ignores start/end and streams 0xF00000-0xFFBFFF (unit,
    # 2026-11-05). sub 1: SSManage's settings read, S(1, 1, 0x0400, 0x2701).
    return frame(b'S', tgt, bytes([sub]) + start.to_bytes(4, 'big') + end.to_bytes(4, 'big'))


def frame_l(start, end, version=MAIN_VERSION, sub=0, tgt=MAIN_TARGET):
    """AA 4C 01 00 vh vl start32 end32 ck (15 B). FUN_0041a070. MAIN only."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: write frames are MAIN (target 1) only')
    f = (b'\xAA' + b'L' + bytes([tgt, sub]) + version.to_bytes(2, 'big')
         + start.to_bytes(4, 'big') + end.to_bytes(4, 'big'))
    return f + bytes([ck(f)])


def frame_p(status, addr, payload, tgt=MAIN_TARGET):
    """AA 50 01 status len16 addr32 payload ck. FUN_0041a7e0. MAIN only."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: write frames are MAIN (target 1) only')
    if len(payload) > P_CHUNK:
        raise ValueError('refused: P payload over 0x400 for MAIN')
    f = (b'\xAA' + b'P' + bytes([tgt, status]) + len(payload).to_bytes(2, 'big')
         + addr.to_bytes(4, 'big') + bytes(payload))
    return f + bytes([ck(f)])


def read_ack(link, secs):
    """Read one reply frame to an L/P write. Returns ('ack'|'nack'|'error'|'badck'|
    'timeout'|'other', frame). Mirrors the unit's A/N/E replies (FUN_0041aca0)."""
    f = link.read_frame(secs)
    if f is None:
        return 'timeout', None
    if ck(f[:-1]) != f[-1]:
        return 'badck', f
    return {ord('A'): 'ack', ord('N'): 'nack', ord('E'): 'error'}.get(f[1], 'other'), f


def send_with_retry(link, fr, secs, log, what):
    """Send one write frame and wait for ACK, retrying as the vendor does: initial send +
    up to FRAME_RETRIES retries on NACK/timeout/bad reply; an 'E' error frame aborts at
    once (vendor case 7). Returns True on ACK."""
    for attempt in range(FRAME_RETRIES + 1):
        link.send(fr)
        kind, f = read_ack(link, secs)
        log(f'< {what} reply: {kind} {desc(f)}')
        if kind == 'ack':
            return True
        if kind == 'error':
            print(f'{what}: unit returned E (error frame); aborting')
            return False
        if attempt < FRAME_RETRIES:
            log(f'  {what}: {kind}, retry {attempt + 1}/{FRAME_RETRIES}')
    print(f'{what}: no ACK after {FRAME_RETRIES} retries ({kind}); aborting')
    return False


class Link:
    """One TCP connection with a receive buffer and a transcript."""

    def __init__(self, ip, port, log, timeout=6.0):
        if port in REFUSED_PORTS:
            raise ValueError(f'refused: port {port} is the DM850 bootloader channel')
        self.log = log
        self.s = socket.create_connection((ip, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.buf = b''
        log(f'connect {ip}:{port}')

    def send(self, b):
        self.log(f'> {b.hex(" ")}' if b[:1] == b'\xAA' else f'> {b!r}')
        self.s.sendall(b)

    def fill(self, deadline):
        self.s.settimeout(max(0.05, deadline - time.time()))
        try:
            chunk = self.s.recv(4096)
        except socket.timeout:
            return False
        if not chunk:
            raise ConnectionError('peer closed the connection')
        self.buf += chunk
        return True

    def wait_text(self, token, secs):
        deadline = time.time() + secs
        while token not in self.buf and time.time() < deadline:
            self.fill(deadline)
        got, self.buf = self.buf, b''
        self.log(f'< {got!r}')
        return token in got, got

    def read_frame(self, secs):
        """Return one AA frame (bytes) or None on timeout. Bad checksums are returned too;
        the caller checks them."""
        deadline = time.time() + secs
        while True:
            i = self.buf.find(b'\xAA')
            if i > 0:
                self.buf = self.buf[i:]
            if len(self.buf) >= 4 and self.buf[:1] == b'\xAA':
                t = self.buf[1]
                if t in DATA_TYPES:
                    if len(self.buf) >= 6:
                        n = 11 + int.from_bytes(self.buf[4:6], 'big')
                        if len(self.buf) >= n:
                            f, self.buf = self.buf[:n], self.buf[n:]
                            return f
                elif t == ord('E'):
                    if len(self.buf) >= 5:
                        f, self.buf = self.buf[:5], self.buf[5:]
                        return f
                else:
                    f, self.buf = self.buf[:4], self.buf[4:]
                    return f
            if time.time() >= deadline:
                return None
            self.fill(deadline)

    def close(self):
        try:
            self.s.close()
        finally:
            self.log('close')


def desc(f):
    if f is None:
        return 'timeout'
    t = chr(f[1]) if 32 <= f[1] < 127 else '?'
    ok = 'ok' if ck(f[:-1]) == f[-1] else 'BAD-CK'
    return f'{t} tgt={f[2]} len={len(f)} {ok}'


def cmd_version(a, log):
    t = Link(a.ip, a.control_port, log)
    try:
        t.send(b'VI?\r')
        ok, got = t.wait_text(b'VI', 3.0)
        print('VI reply:', got.decode('latin1', 'replace').strip() if ok else '(none)')
        return ok
    finally:
        t.close()


def cmd_dmdump(a, log):
    """Normal mode, needs the DM patch in MAIN (docs/main-dump-patch.md): one
    'DMaaaaaa?' line per 32 bytes, reply 'DMaaaaaa' + 64 hex digits + CR."""
    start, end = a.range[0] if a.range else (0xFFC000, 0xFFFFFF)
    if start % 32 or (end + 1) % 32 or not 0xF00000 <= start <= end <= 0xFFFFFF:
        sys.exit('refused: range must be 32-byte aligned inside 0xF00000-0xFFFFFF')
    t = Link(a.ip, a.control_port, log)
    data = bytearray()
    try:
        for addr in range(start, end + 1, 32):
            want = f'DM{addr:06X}'.encode()
            for attempt in range(3):
                t.send(f'DM{addr:06X}?\r'.encode())
                deadline = time.time() + 3.0
                line = None
                while time.time() < deadline:
                    i = t.buf.find(want)
                    if i >= 0 and t.buf.find(b'\r', i) >= 0:
                        j = t.buf.find(b'\r', i)
                        line, t.buf = t.buf[i:j], t.buf[j + 1:]
                        break
                    t.fill(deadline)
                if line and len(line) == 72 and re.fullmatch(rb'[0-9A-F]{64}', line[8:]):
                    break
                log(f'  {addr:06X}: bad/missing reply {line!r}, retry')
            else:
                sys.exit(f'no valid reply for {addr:06X} after 3 tries; '
                         'is the DM patch installed?')
            data += bytes.fromhex(line[8:].decode())
            if addr % 0x400 == 0:
                print(f'  {addr:06X}', flush=True)
    finally:
        t.close()
    d = os.path.join('dumps', 'dm-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'main_{start:06X}_{end:06X}.bin')
    open(p, 'wb').write(data)
    print(f'{p}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}')
    return True


def connect_check(link, tgt, log, tries=1):
    # Vendor FUN_0041D270: send C, wait up to 6 s for the reply, up to 3 retries.
    for _ in range(tries):
        link.send(frame(b'C', tgt))
        f = link.read_frame(6.0)
        log(f'< C reply: {desc(f)}' + (f' {f.hex(" ")}' if f else ''))
        if f is not None and f[1] == ord('C') and ck(f[:-1]) == f[-1]:
            return True
    return False


def cmd_check(a, log):
    l = Link(a.ip, a.loader_port, log)
    try:
        ok = connect_check(l, a.target, log)
        print('Check communication:', 'OK' if ok else 'NG')
        return ok
    finally:
        l.close()


def read_range(link, tgt, start, end, log, sub=0):
    link.send(frame_s(tgt, start, end, sub))
    f = link.read_frame(6.0)
    log(f'< S reply: {desc(f)}')
    if f is None or f[1] != ord('A') or ck(f[:-1]) != f[-1]:
        print('S not acknowledged:', desc(f), '— loader refused or not in update mode')
        return None
    data, retries, expect, first = bytearray(), 0, start, None
    while True:
        f = link.read_frame(6.0)
        if f is None or f[1] not in DATA_TYPES or ck(f[:-1]) != f[-1]:
            log(f'< bad/missing data frame: {desc(f)}')
            if retries >= 3:
                print('giving up after 3 retries:', desc(f))
                return None
            retries += 1
            link.send(frame(b'N', tgt))
            continue
        status, n = f[3], int.from_bytes(f[4:6], 'big')
        addr = int.from_bytes(f[6:10], 'big')
        if addr != expect:
            log(f'  note: frame address {addr:#08x}, expected {expect:#08x}')
        if first is None:
            first = addr
        data += f[10:10 + n]
        expect = addr + n
        retries = 0
        link.send(frame(b'A', tgt))
        log(f'< data status={status} addr={addr:#08x} len={n}')
        if status in (0, 3):
            return first, bytes(data)
        if status not in (1, 2):
            print(f'unexpected status {status}; stopping')
            return first, bytes(data)
        if len(data) > MAX_READ:
            print('read exceeds 4 MB; stopping')
            return first, bytes(data)


def cmd_read(a, log):
    if not a.confirm_update_mode:
        sys.exit('refused: `read` puts the unit in update mode. Follow docs/safety-plan.md '
                 '(UPS, direct cable, nothing else on the LAN), then add --confirm-update-mode.')
    ranges = a.range or DEFAULT_RANGES
    for start, end in ranges:
        if end < start or end - start + 1 > MAX_READ:
            sys.exit('refused: each range must be 1 byte .. 4 MB')
    if a.in_update_mode:
        # Unit already in update mode from an earlier session (no power cycle since):
        # skip VI?/RBUPDATE; the C frame below confirms the loader is there.
        return read_ranges(a, log, ranges)
    # Same order as the vendor update (FUN_00407C60), all on the control port.
    # 1. Version request, normal mode (FUN_00407EA0).
    t = Link(a.ip, a.control_port, log)
    try:
        t.send(b'VI?\r')
        ok, got = t.wait_text(b'VI', 3.0)
    finally:
        t.close()
    if not ok:
        sys.exit('VI? not answered in normal mode; nothing changed on the unit.')
    print('VI reply:', got.decode('latin1', 'replace').strip())
    time.sleep(a.delay)
    # 2. Enter update mode (FUN_00408050): RBUPDATE, wait RBSTART, up to 3 tries.
    t = Link(a.ip, a.control_port, log)
    try:
        for attempt in range(3):
            t.send(b'RBUPDATE\r')
            ok, _ = t.wait_text(b'RBSTART', 5.0)
            if ok:
                break
        else:
            sys.exit('no RBSTART: the unit did not confirm update mode. Power-cycle it to be '
                     'sure it is back in normal mode.')
    finally:
        t.close()
    print(f'unit confirmed update mode (RBSTART); waiting {UPDATE_SETTLE:.0f} s as the '
          'vendor tool does')
    time.sleep(UPDATE_SETTLE)
    return read_ranges(a, log, ranges)


def read_ranges(a, log, ranges):
    # 3. Loader (FUN_00408170): C with 3 tries, then the reads in the order given, each
    #    saved as soon as it arrives.
    d = os.path.join('dumps', 'loader-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    good = 0
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, a.target, log, tries=3):
            print('loader did not answer C after RBSTART')
        else:
            for start, end in ranges:
                got = read_range(l, a.target, start, end, log, a.sub)
                if not got or not got[1]:
                    break
                first, data = got
                last = first + len(data) - 1
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, f'tgt{a.target:02X}_s{a.sub}_{first:06X}_{last:06X}.bin')
                open(p, 'wb').write(data)
                print(f'{p}: {len(data)} bytes, {first:#08x}-{last:#08x} '
                      f'(asked {start:#08x}-{end:#08x}), '
                      f'sha256 {hashlib.sha256(data).hexdigest()}')
                good += 1
                time.sleep(a.delay)
    finally:
        l.close()
    print('\nNOW: turn the unit off with its power switch, wait 10 s, turn it on '
          '(vendor manual 3.9-3). Then check the version screen and a VI? query.')
    return good == len(ranges)


CHECKLIST = """docs/safety-plan.md per-write checklist (confirm each before --confirm-write):
  [ ] Offline gate passed and recorded (commit hash, image sha256).
  [ ] Rollback image (vendor MAIN 01.00) packed, verified, on the PC.
  [ ] Unit + PC on a sine-wave UPS/inverter; no load-shedding or storm due within 2 h.
  [ ] PC wired directly to the unit (crossover / dedicated switch), static IPs, Wi-Fi off,
      nothing else talking to the unit.
  [ ] Settings backup (RAM 0x040C-0x2701 / a .bid) taken and copied off the PC.
  [ ] Unit AC power-cycled immediately before; DM850 answers ping.
  [ ] Image set contains only MAIN; no VME stage; no bootloader image.
During the write: do not touch the unit, cable, PC or mains; do not abort a write in
progress. This tool writes MAIN only and cannot reach SUB, DSP, the CPLDs or the DM850."""


def enter_update_mode(a, log):
    """Vendor order (FUN_00407C60): VI? in normal mode, then RBUPDATE -> RBSTART, then the
    15 s settle. Same as cmd_read uses. Returns True if the unit confirmed update mode."""
    t = Link(a.ip, a.control_port, log)
    try:
        t.send(b'VI?\r')
        ok, got = t.wait_text(b'VI', 3.0)
    finally:
        t.close()
    if not ok:
        print('VI? not answered in normal mode; nothing changed on the unit.')
        return False
    print('VI reply:', got.decode('latin1', 'replace').strip())
    time.sleep(a.delay)
    t = Link(a.ip, a.control_port, log)
    try:
        for _ in range(3):
            t.send(b'RBUPDATE\r')
            ok, _ = t.wait_text(b'RBSTART', 5.0)
            if ok:
                break
        else:
            print('no RBSTART: the unit did not confirm update mode. Power-cycle it.')
            return False
    finally:
        t.close()
    print(f'unit confirmed update mode (RBSTART); waiting {UPDATE_SETTLE:.0f} s as the '
          'vendor tool does')
    time.sleep(UPDATE_SETTLE)
    return True


def cmd_write(a, log):
    # --- offline gate (safety-plan): sha256-pinned image, exact size, explicit confirm ---
    img = open(a.image, 'rb').read()
    sha = hashlib.sha256(img).hexdigest()
    if sha not in ACCEPTED_IMAGES:
        sys.exit(f'refused: {a.image} (sha256 {sha}) is not an accepted MAIN image.\n'
                 'Only the DM-dump patch build or vendor 01.00 (rollback) may be written.')
    if len(img) != MAIN_SIZE:
        sys.exit(f'refused: image is {len(img)} bytes, expected {MAIN_SIZE} '
                 f'(0x{MAIN_SIZE:X}) for MAIN 0x{MAIN_START:06X}-0x{MAIN_END:06X}.')
    print(f'image: {a.image}')
    print(f'       {ACCEPTED_IMAGES[sha]}')
    print(f'       {len(img)} bytes, sha256 {sha}')
    log(f'write image {a.image} sha256 {sha} ({ACCEPTED_IMAGES[sha]})')
    if not a.confirm_write:
        print('\n' + CHECKLIST)
        sys.exit('\nrefused: add --confirm-write once the checklist above is done. '
                 'Never write the real unit without it.')
    # --- enter update mode (unless already there from a prior session) ---
    if not a.in_update_mode and not enter_update_mode(a, log):
        sys.exit('did not enter update mode; nothing written.')
    nframes = (len(img) + P_CHUNK - 1) // P_CHUNK
    print(f'\nwriting MAIN 0x{MAIN_START:06X}-0x{MAIN_END:06X}: 1 L frame + {nframes} '
          f'P frames of 0x{P_CHUNK:X}')
    l = Link(a.ip, a.loader_port, log)
    try:
        # Loader present? (FUN_00408170: C, up to 3 tries.)
        if not connect_check(l, MAIN_TARGET, log, tries=3):
            sys.exit('loader did not answer C after RBSTART; nothing written. Power-cycle '
                     'the unit and check the version screen.')
        # L: begin load / erase (FUN_0041a070). ACK within 10 s, 3 retries.
        if not send_with_retry(l, frame_l(MAIN_START, MAIN_END), L_ACK_SECS, log, 'L'):
            sys.exit('L not acknowledged; the loader did not start the write. The flash is '
                     'not yet erased. Power-cycle and check the version screen.')
        print('L acknowledged (load started).')
        # P: data (FUN_0041a7e0). First frame erases (60 s), middle 6 s, last 60 s.
        for i in range(nframes):
            off = i * P_CHUNK
            payload = img[off:off + P_CHUNK]
            status = 1 if i == 0 else 3 if i == nframes - 1 else 2
            secs = P_ACK_FIRST_LAST if status in (1, 3) else P_ACK_MIDDLE
            addr = MAIN_START + off
            if not send_with_retry(l, frame_p(status, addr, payload), secs, log,
                                   f'P[{i + 1}/{nframes}] {addr:#08x}'):
                sys.exit(f'\nWRITE FAILED at frame {i + 1}/{nframes} ({addr:#08x}). MAIN is '
                         'now partly written. DO NOT power off mid-thought: follow '
                         'safety-plan.md recovery (re-run with the rollback image if the '
                         'loader still answers C).')
            if status == 1:
                print('  frame 1 acknowledged (erase done).')
            elif (i + 1) % 64 == 0 or status == 3:
                print(f'  {i + 1}/{nframes} ({addr:#08x})', flush=True)
        print('all data frames acknowledged.')
    finally:
        l.close()
    # --- verify: full S sub-0 read-back, byte-for-byte (Option C / main-dump-patch §5) ---
    ok = a.no_verify or verify_readback(a, img, log)
    print('\nNOW: turn the unit off with its power switch, wait 10 s, turn it on '
          '(vendor manual 3.9-3). Then check the version screen and a VI? query.')
    if a.no_verify:
        print('verify skipped (--no-verify); read it back with `read --sub 0` after the '
              'power cycle.')
    return ok


def verify_readback(a, img, log):
    print('\nverify: reading the application flash back (S sub 0) and comparing...')
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, MAIN_TARGET, log, tries=3):
            print('verify: loader did not answer C; read it back manually after the power '
                  'cycle (`read --sub 0`).')
            return False
        got = read_range(l, MAIN_TARGET, MAIN_START, MAIN_END, log, sub=0)
    finally:
        l.close()
    if not got or not got[1]:
        print('verify: no data read back.')
        return False
    first, data = got
    if first == MAIN_START and data == img:
        print(f'verify OK: {len(data)} bytes read back equal the image '
              f'(sha256 {hashlib.sha256(data).hexdigest()}).')
        return True
    n = min(len(data), len(img))
    diff = next((MAIN_START + i for i in range(n) if data[i] != img[i]), None)
    print(f'verify FAILED: read {len(data)} bytes from {first:#08x}, image {len(img)} bytes '
          f'from {MAIN_START:#08x}; first difference '
          f'{"at %#08x" % diff if diff is not None else "beyond the shorter buffer"}.')
    return False


def main():
    ap = argparse.ArgumentParser(description='read-only AVR-4306 loader-protocol client')
    ap.add_argument('cmd', choices=['version', 'check', 'read', 'dmdump', 'write'])
    ap.add_argument('--ip', required=True)
    ap.add_argument('--control-port', type=int, default=5000,
                    help='port for VI?/RBUPDATE (vendor update uses 5000; 23 also answers VI?)')
    ap.add_argument('--loader-port', type=int, default=5000)
    ap.add_argument('--target', type=lambda x: int(x, 0), default=1, help='1 = MAIN')
    ap.add_argument('--range', action='append', type=parse_range, metavar='START:END',
                    help='inclusive address range, repeatable; default 0x0400:0x2701')
    ap.add_argument('--sub', type=lambda x: int(x, 0), default=1, choices=[0, 1],
                    help='S sub-byte: 0 = updater read, 1 = SSManage settings read')
    ap.add_argument('--in-update-mode', action='store_true',
                    help='unit is already in update mode: skip VI?/RBUPDATE')
    ap.add_argument('--delay', type=float, default=2.0, help='seconds between connections')
    ap.add_argument('--confirm-update-mode', action='store_true')
    ap.add_argument('--image', help='write: firmware image (must be an accepted MAIN image)')
    ap.add_argument('--confirm-write', action='store_true',
                    help='write: attest the safety-plan.md checklist is done')
    ap.add_argument('--no-verify', action='store_true',
                    help='write: skip the read-back verify (not recommended)')
    ap.add_argument('--log', default=None, help='transcript file (default dumps/loader.log)')
    a = ap.parse_args()
    if a.target != 1:
        sys.exit('refused: only target 1 (MAIN) is supported')
    if a.cmd == 'write' and not a.image:
        sys.exit('refused: write needs --image')
    os.makedirs('dumps', exist_ok=True)
    lf = open(a.log or os.path.join('dumps', 'loader.log'), 'a')

    def log(msg):
        lf.write(f'{datetime.datetime.now().isoformat(timespec="milliseconds")} {msg}\n')
        lf.flush()

    log(f'--- {a.cmd} {a.ip}')
    ok = {'version': cmd_version, 'check': cmd_check, 'read': cmd_read,
          'dmdump': cmd_dmdump, 'write': cmd_write}[a.cmd](a, log)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
