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
A and N frames. I (target info), L (load/erase) and P (data) are built by `write`
(frame_i/frame_l/frame_p), the explicitly gated MAIN firmware command (Option C,
docs/main-dump-patch.md §5). Settings restore builds L and D (`frame_l` / `frame_d`);
D is the RAM-load data frame, and P is the flash-load data frame. I is read-only (it reports the
model code, checked before any erase). Nothing here sends DM850 loader commands.
`settings-save` and `settings-restore` send `RBNORM` on the way out of update mode; the
other commands do not. Every builder forces target 1 (MAIN). `S`/`L`/`P`/`D` are
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
  loader_client.py status  --ip IP               read-only: 'VI?' parsed into per-processor
                                                 versions, plus a C probe reporting normal
                                                 vs update mode. Changes nothing.
  loader_client.py settings-save --ip IP [--out F] --confirm-update-mode
                                                 SSManage save (update-tools.md §3a): update
                                                 mode, S sub 1, slice 0x040C-0x2701, write F,
                                                 exit X(1,2,1)+RBNORM. Read-only to flash.
  loader_client.py settings-restore --ip IP --image F --confirm-restore
                                                 SSManage load: update mode, I model guard,
                                                 L sub 1 + D of the 8,950-byte settings body
                                                 to RAM 0x040C-0x2701, exit X+RBNORM. Writes
                                                 parameter RAM, not flash; no MAIN wear.
  loader_client.py verify --ip IP --against F [--source flash|dm]
                                                 read-only: flash = S sub-0 read-back vs F
                                                 (update mode); dm = DM-patch dump vs F.
  loader_client.py rollback --ip IP --image F --confirm-write
                                                 `write` restricted to the vendor (unpatched)
                                                 MAIN 01.00 image. Counts as a MAIN write.
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
        RBUPDATE/RBSTART, 15 s) unless --in-update-mode; then C, an I (target information)
        frame whose model code must be 0x0011 (AVR-4306) or the run aborts before any
        erase, L for 0xF00000-0xFFBFFF, 1008 P frames of 0x400 bytes, then reads the whole
        application flash back (S sub 0) and checks it byte-for-byte against the image. The
        image must be one of the two accepted files (sha256-pinned). Power-cycle afterwards.

Run with python3 -I. --control-port / --loader-port exist for the local test peer
(sim/fake_unit.py).
"""
import argparse, datetime, hashlib, json, os, re, socket, sys, time

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
L_ACK_SECS = 6.0                             # 'L' ACK timeout, TCP path (FUN_0041d600: 6; COM path 10)
POST_WRITE_SETTLE = 5.0                      # vendor wait after the last P before verify (0x40876b)
P_ACK_FIRST_LAST = 60.0                      # first (erase) and last frame (0x3c)
P_ACK_MIDDLE = 6.0                           # middle frames
FRAME_RETRIES = 3                            # vendor: initial send + up to 3 retries
# 'I' target-information frame, sent between C and L (loader-interface §2.8 "Before L").
I_ACK_SECS = 10.0                            # FUN_0041d3f0 local_4 = 10 after the send
I_REPLY_LEN = 54                             # fixed 54-byte 'I' reply (FUN_0041b290)
MAIN_MODEL_CODE = 0x0011                     # I reply frame bytes 5-6 (BE); container "0011"
                                             # (FUN_00407C60 @ 0x407d81)
I_MODEL_OFFSET = 5                           # FUN_0041b290 dword = frame bytes 3-6 (buffer
                                             # 0xb71-0xb74, frame byte 0 at 0xb6e);
                                             # FUN_004081c0 @ 0x408235 keeps its low 16 bits
# Offline gate (safety-plan): the only images `write` may send to MAIN. sha256 -> label.
PATCH_IMAGE_SHA = '9470fa599734b8341cbfae37617702e7f17be8228e622f63a0b5ca5fc2f31a96'
VENDOR_IMAGE_SHA = '0fcc83501f19dd4f4356ed2120eafaa82d83fc7e7628dab6625867e9e9922d6b'
ACCEPTED_IMAGES = {
    PATCH_IMAGE_SHA: 'MAIN 01.00 + read-only DM-dump patch (build/patch/MAIN_dm.flash.bin)',
    VENDOR_IMAGE_SHA: 'MAIN 01.00 vendor, unpatched (rollback, build/images/MAIN_01.00.flash.bin)',
}

# ---- settings (SSManage save/restore, update-tools.md §3a). MAIN parameter RAM, NOT flash:
# a settings restore costs no MAIN flash cycle and cannot brick the unit. ----
SETTINGS_START, SETTINGS_END = 0x040C, 0x2701    # the .bid body range in MAIN RAM
SETTINGS_SIZE = SETTINGS_END - SETTINGS_START + 1  # 0x22F6 = 8,950 B
RAM_START, RAM_END = 0x0400, 0xC3FF              # what a sub-1 S read streams (range ignored)
SETTINGS_ACK_SECS = 5.0                          # L and D ACK: FUN_00403ed0(target, 5) = 5*100*10 ms
EXIT_WAIT = 5.0                                   # FUN_00402db0(5): five Sleep(1000) around X/RBNORM
DM_BLOCKS_RANGE = (0xFFC000, 0xFFFFFF)           # resident blocks 0-2 (DM-patch dump range)


SESSION = None       # set in main(): the structured session log (dumps/session-log.jsonl)


def sev(kind, **kw):
    """Record one structured session-log event, if a session log is open."""
    if SESSION is not None:
        SESSION.event(kind, **kw)


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
    """AA 50 01 status len16 addr32 payload ck. FUN_0041a7e0. MAIN flash only.
    The resident loader accepts 'P' in a sub-0 flash load and rejects it in a sub-1 RAM load."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: write frames are MAIN (target 1) only')
    if len(payload) > P_CHUNK:
        raise ValueError('refused: P payload over 0x400 for MAIN')
    f = (b'\xAA' + b'P' + bytes([tgt, status]) + len(payload).to_bytes(2, 'big')
         + addr.to_bytes(4, 'big') + bytes(payload))
    return f + bytes([ck(f)])


def frame_d(status, addr, payload, tgt=MAIN_TARGET):
    """AA 44 01 status len16 addr32 payload ck. FUN_00403c50 (byte 0x361 = 0x44).
    Settings RAM only. The resident loader accepts 'D' in a sub-1 RAM load (0xFFCCC4)
    and rejects 'P' there."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: write frames are MAIN (target 1) only')
    if len(payload) > P_CHUNK:
        raise ValueError('refused: D payload over 0x400 for MAIN')
    f = (b'\xAA' + b'D' + bytes([tgt, status]) + len(payload).to_bytes(2, 'big')
         + addr.to_bytes(4, 'big') + bytes(payload))
    return f + bytes([ck(f)])


def frame_i(tgt=MAIN_TARGET, field1=0, field2=0):
    """AA 49 01 field1-32 field2-32 ck (12 B). FUN_0041d3f0; the vendor sends all-zero
    fields. MAIN only."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: write frames are MAIN (target 1) only')
    f = (b'\xAA' + b'I' + bytes([tgt])
         + field1.to_bytes(4, 'big') + field2.to_bytes(4, 'big'))
    return f + bytes([ck(f)])


def frame_x_normal(tgt=MAIN_TARGET):
    """AA 58 01 02 01 ck: SSManage 'Reboot(Normal mode)' mode frame, X(1,2,1)
    (FUN_00403520, called from FUN_00401F40). The loader ACKs sub 2 (0xFFC26A), then
    stores mode 5. A mode change only — no flash write. MAIN only."""
    if tgt != MAIN_TARGET:
        raise ValueError('refused: X frame is MAIN (target 1) only')
    f = b'\xAA' + b'X' + bytes([tgt, 0x02, 0x01])
    return f + bytes([ck(f)])


def query_model(link, log, secs=I_ACK_SECS):
    """Send the 'I' target-information frame and read the fixed 54-byte reply. Returns the
    16-bit model code (reply frame bytes 5-6, FUN_0041b290), or None on timeout, a bad
    checksum (vendor result 10, a failed reply), or a reply that is not an 'I' for MAIN. The 'I' reply is a fixed-length frame, not a
    D/P data frame, so it is read directly rather than through Link.read_frame."""
    link.send(frame_i())
    deadline = time.time() + secs
    while True:
        i = link.buf.find(b'\xAA')
        if i >= 0 and len(link.buf) - i >= I_REPLY_LEN:
            f = link.buf[i:i + I_REPLY_LEN]
            link.buf = link.buf[i + I_REPLY_LEN:]
            break
        if time.time() >= deadline:
            log('< I reply: timeout')
            return None
        link.fill(deadline)
    if f[1] != ord('I') or f[2] != MAIN_TARGET:
        log(f'< I reply: bad header {f[:3].hex(" ")}')
        return None
    if ck(f[:-1]) != f[-1]:
        log(f'< I reply: bad checksum {f.hex(" ")}')
        return None
    model = int.from_bytes(f[I_MODEL_OFFSET:I_MODEL_OFFSET + 2], 'big')
    log(f'< I reply: {I_REPLY_LEN} B, model {model:#06x} {f.hex(" ")}')
    return model


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
    start, end = a.range[0] if a.range else DM_BLOCKS_RANGE
    data = dm_read_range(a, log, start, end)
    if data is None:
        return False
    d = os.path.join('dumps', 'dm-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'main_{start:06X}_{end:06X}.bin')
    open(p, 'wb').write(data)
    sha = hashlib.sha256(data).hexdigest()
    print(f'{p}: {len(data)} bytes, sha256 {sha}')
    sev('dmdump', path=p, start=start, end=end, bytes=len(data), sha256=sha)
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
    sev('flash-write-start', image=a.image, sha256=sha, label=ACCEPTED_IMAGES[sha],
        note='counts as 1 MAIN flash cycle (safety-plan.md rule 5)')
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
        # I: target information, between C and L (loader-interface §2.8 "Before L";
        # FUN_004081c0 -> FUN_0041d3f0, model check FUN_00407C60 @ 0x407d81). Guard that
        # this is an AVR-4306 BEFORE any erase; refuse on a wrong/missing model code.
        model = query_model(l, log)
        if model is None:
            sys.exit('I (target information) not answered; nothing written (no erase). '
                     'Power-cycle the unit and check the version screen.')
        if model != MAIN_MODEL_CODE:
            sys.exit(f'refused: unit model code {model:#06x} != expected '
                     f'{MAIN_MODEL_CODE:#06x} (AVR-4306). Nothing erased or written.')
        print(f'unit model code {model:#06x} confirmed (AVR-4306).')
        # L: begin load (FUN_0041d600, TCP path). ACK within 6 s, 3 retries.
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
                         'now partly written. Do not power off yet: follow '
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
    # Vendor: 5 s between the last P and the post-write step (FUN_00408310, 0x40876b).
    # Also keeps the connection churn down (docs/lan-access.md).
    time.sleep(max(POST_WRITE_SETTLE, a.delay))
    ok = a.no_verify or verify_readback(a, img, log)
    sev('flash-write-done', verified=(None if a.no_verify else ok), sha256=sha)
    print('\nNOW: turn the unit off with its power switch, wait 10 s, turn it on '
          '(vendor manual 3.9-3). Then check the version screen and a VI? query.')
    if a.no_verify:
        print('verify skipped (--no-verify); read it back with `read --sub 0` after the '
              'power cycle.')
    print('\nsafety-plan.md write-log row (fill Date/Path/Result, bump MAIN cycles):')
    print(f'  | {datetime.datetime.now():%Y-%m-%d} | MAIN | {ACCEPTED_IMAGES[sha]}, '
          f'sha256 `{sha[:8]}…` | LAN, TCP 5000, loader_client.py '
          f'{"rollback" if sha == VENDOR_IMAGE_SHA else "write"} | '
          f'{"read-back equal" if ok else "VERIFY FAILED"} | +1 |')
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


class Session:
    """Append-only structured session log (dumps/session-log.jsonl), one JSON line per
    event, each tagged with the session id — a machine-readable record of what the tool
    did to the unit, alongside the dumps/loader.log frame transcript. Events: start, the
    key protocol milestones, every file written (with sha256), flash writes (with the MAIN
    wear note for safety-plan.md), and end."""

    def __init__(self, path, cmd, ip):
        self.path = path
        self.id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.event('start', cmd=cmd, ip=ip)

    def event(self, kind, **kw):
        rec = {'session': self.id,
               't': datetime.datetime.now().isoformat(timespec='seconds'),
               'kind': kind, **kw}
        with open(self.path, 'a') as f:
            f.write(json.dumps(rec) + '\n')


def exit_normal(a, log):
    """SSManage 'Reboot(Normal mode)' (FUN_00401F40): one connection, wait 5 s, X(1,2,1)
    and require its ACK (FUN_00403520, 5 s, 3 retries), wait 5 s, RBNORM\r -> RBSTART
    (FUN_00404b40), wait 5 s. Returns True if RBSTART was seen. No flash write."""
    wait = max(EXIT_WAIT, a.delay)
    time.sleep(wait)
    l = Link(a.ip, a.loader_port, log)
    try:
        if not send_with_retry(l, frame_x_normal(), EXIT_WAIT, log, 'X(1,2,1)'):
            sev('exit-normal', rbstart=False, x_ack=False)
            return False
        print('X(1,2,1) acknowledged.')
        time.sleep(wait)
        l.send(b'RBNORM\r')
        ok, _ = l.wait_text(b'RBSTART', EXIT_WAIT)
        if ok:
            time.sleep(wait)
    finally:
        l.close()
    sev('exit-normal', rbstart=ok, x_ack=True)
    return ok


def finish_session_mode(a, log):
    """End an update-mode session: the SSManage X(1,2,1)+RBNORM exit, or (--power-cycle-exit)
    the manual power cycle the updater/read path uses."""
    if a.power_cycle_exit:
        print('\nNOW: turn the unit off with its power switch, wait 10 s, turn it on, then '
              'check a VI? query.')
        sev('exit-power-cycle')
        return True
    print('\nexiting update mode: X(1,2,1) + RBNORM (SSManage Reboot(Normal mode))...')
    ok = exit_normal(a, log)
    print('RBNORM confirmed (RBSTART); unit back in normal mode.' if ok else
          'RBNORM not confirmed — power-cycle the unit to be sure it is back to normal.')
    return ok


def parse_vi(reply):
    """Split a VI? reply ('VI01:0100;02:0050;...') into {id: value}."""
    body = reply[reply.find('VI') + 2:] if 'VI' in reply else reply
    out = {}
    for part in body.split(';'):
        part = part.strip()
        if ':' in part:
            k, v = part.split(':', 1)
            out[k.strip()] = v.strip()
    return out


VI_LABELS = {0x01: 'MAIN', 0x02: 'SUB', 0x03: 'DSP', 0x0A: 'DM850', 0x0B: 'CPLD'}


def cmd_status(a, log):
    """Read-only, normal mode: VI? parsed into per-processor versions, then a normal-mode C
    probe to report whether the unit is in normal or update mode. Changes nothing."""
    t = Link(a.ip, a.control_port, log)
    try:
        t.send(b'VI?\r')
        ok, got = t.wait_text(b'VI', 3.0)
    finally:
        t.close()
    if not ok:
        print('VI? not answered. The unit may be off, mid-boot, or in update mode.')
        sev('status', vi=False)
        return False
    reply = got.decode('latin1', 'replace').strip()
    fields = parse_vi(reply)
    print('VI reply:', reply)
    print('versions:')
    for k, v in fields.items():
        try:
            lbl = VI_LABELS.get(int(k, 16), f'id {k}')
        except ValueError:
            lbl = f'id {k}'
        print(f'  {k} {lbl:5} {v}')
    time.sleep(a.delay)
    l = Link(a.ip, a.loader_port, log)
    try:
        mode_update = connect_check(l, MAIN_TARGET, log)   # C: silent in normal mode
    finally:
        l.close()
    print('mode:', 'UPDATE MODE (loader answered C)' if mode_update
          else 'normal (loader silent, as expected)')
    sev('status', vi=True, versions=fields, update_mode=mode_update)
    return True


def cmd_settings_save(a, log):
    """SSManage save (update-tools.md §3a): update mode, C, S sub 1 (returns all RAM), slice
    the settings body 0x040C-0x2701, write it, then the X(1,2,1)+RBNORM exit. Read-only to
    flash; no MAIN wear."""
    if not a.confirm_update_mode:
        sys.exit('refused: settings-save enters update mode (RBUPDATE). Follow '
                 'docs/safety-plan.md (UPS, direct cable, nothing else on the LAN), then '
                 'add --confirm-update-mode.')
    out = a.out or os.path.join(
        'dumps', 'settings-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.bin')
    if not a.in_update_mode and not enter_update_mode(a, log):
        sys.exit('did not enter update mode; nothing read.')
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, MAIN_TARGET, log, tries=3):
            sys.exit('loader did not answer C after RBSTART.')
        got = read_range(l, MAIN_TARGET, RAM_START, RAM_END, log, sub=1)
    finally:
        l.close()
    if not got or not got[1]:
        sys.exit('settings-save: no RAM read back.')
    first, data = got
    lo = SETTINGS_START - first
    if lo < 0 or lo + SETTINGS_SIZE > len(data):
        sys.exit(f'settings-save: RAM read {first:#06x}+{len(data)} B does not cover '
                 f'{SETTINGS_START:#06x}-{SETTINGS_END:#06x}.')
    body = bytes(data[lo:lo + SETTINGS_SIZE])
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    open(out, 'wb').write(body)
    sha = hashlib.sha256(body).hexdigest()
    print(f'\n{out}: {len(body)} bytes (RAM {SETTINGS_START:#06x}-{SETTINGS_END:#06x}), '
          f'sha256 {sha}')
    sev('settings-save', path=out, bytes=len(body), sha256=sha)
    return finish_session_mode(a, log)


def cmd_settings_restore(a, log):
    """SSManage load (update-tools.md §3a, FUN_00402370 -> FUN_00403280): update mode, C, I
    (model guard), L sub 1 for 0x040C-0x2701 (FUN_004038f0; the range is the ushorts
    FUN_00402610 reads at body offsets 2 and 4, which are 0x040C and 0x2701), D frames of
    the 8,950-byte body (FUN_00403c50, type 0x44, 0x400-byte chunks, 5 s ACK), then the
    X(1,2,1)+RBNORM exit. Writes MAIN parameter RAM, not flash: no MAIN wear."""
    if not a.image:
        sys.exit('refused: settings-restore needs --image (an 8,950-byte RAM settings file, '
                 'e.g. a settings-save output or a .bid body).')
    body = open(a.image, 'rb').read()
    if len(body) != SETTINGS_SIZE:
        sys.exit(f'refused: {a.image} is {len(body)} bytes, expected {SETTINGS_SIZE} '
                 f'(0x{SETTINGS_SIZE:X}) for RAM {SETTINGS_START:#06x}-{SETTINGS_END:#06x}.')
    sha = hashlib.sha256(body).hexdigest()
    print(f'settings image: {a.image} ({len(body)} bytes, sha256 {sha})')
    if not a.confirm_restore:
        sys.exit('refused: settings-restore writes the MAIN parameter RAM (0x040C-0x2701). '
                 'It does not touch flash and costs no MAIN write, but it enters update '
                 'mode. Add --confirm-restore to proceed.')
    sev('settings-restore-start', path=a.image, bytes=len(body), sha256=sha)
    if not a.in_update_mode and not enter_update_mode(a, log):
        sys.exit('did not enter update mode; nothing written.')
    nframes = (len(body) + P_CHUNK - 1) // P_CHUNK
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, MAIN_TARGET, log, tries=3):
            sys.exit('loader did not answer C after RBSTART.')
        model = query_model(l, log)
        if model is None:
            sys.exit('I (target information) not answered; settings not restored.')
        if model != MAIN_MODEL_CODE:
            sys.exit(f'refused: unit model code {model:#06x} != {MAIN_MODEL_CODE:#06x} '
                     '(AVR-4306). Settings not restored.')
        print(f'unit model code {model:#06x} confirmed (AVR-4306).')
        # L for the RAM settings range: sub 1, version 0 (FUN_00403280 -> FUN_004038f0).
        # ACK timeout is SSManage's 5 s, not the updater's 6 s L timeout.
        if not send_with_retry(l, frame_l(SETTINGS_START, SETTINGS_END, version=0, sub=1),
                               SETTINGS_ACK_SECS, log, 'L(settings)'):
            sys.exit('L not acknowledged; settings not restored.')
        for i in range(nframes):
            off = i * P_CHUNK
            payload = body[off:off + P_CHUNK]
            status = 1 if i == 0 else 3 if i == nframes - 1 else 2
            addr = SETTINGS_START + off
            if not send_with_retry(l, frame_d(status, addr, payload), SETTINGS_ACK_SECS, log,
                                   f'D[{i + 1}/{nframes}] {addr:#06x}'):
                sys.exit(f'settings restore failed at frame {i + 1}/{nframes}. The parameter '
                         'RAM is partly written; power-cycle the unit to clear it, then '
                         'retry (no flash was touched).')
        print(f'settings written: {nframes} D frames to RAM '
              f'{SETTINGS_START:#06x}-{SETTINGS_END:#06x}.')
    finally:
        l.close()
    sev('settings-restore-done', frames=nframes)
    ok = finish_session_mode(a, log)
    print('Then check that your inputs and FM presets are back.')
    return ok


def dm_read_range(a, log, start, end):
    """Normal mode, DM patch (main-dump-patch.md): 'DMaaaaaa?' per 32 bytes; returns the
    bytes read, or None on a missing/invalid reply. No file is written here."""
    if start % 32 or (end + 1) % 32 or not 0xF00000 <= start <= end <= 0xFFFFFF:
        sys.exit('refused: range must be 32-byte aligned inside 0xF00000-0xFFFFFF')
    t = Link(a.ip, a.control_port, log)
    data = bytearray()
    try:
        for addr in range(start, end + 1, 32):
            want = f'DM{addr:06X}'.encode()
            line = None
            for _ in range(3):
                t.send(f'DM{addr:06X}?\r'.encode())
                deadline = time.time() + 3.0
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
                line = None
            if line is None:
                print(f'no valid reply for {addr:06X} after 3 tries; is the DM patch installed?')
                return None
            data += bytes.fromhex(line[8:].decode())
            if addr % 0x4000 == 0:
                print(f'  {addr:06X}', flush=True)
    finally:
        t.close()
    return bytes(data)


def flash_read_back(a, log):
    """Enter update mode and S sub-0 read the whole application flash (0xF00000-0xFFBFFF).
    Returns the bytes, or None. Settings-safe: a read-only session does not reset them."""
    if not a.in_update_mode and not enter_update_mode(a, log):
        return None
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, MAIN_TARGET, log, tries=3):
            print('loader did not answer C after RBSTART.')
            return None
        got = read_range(l, MAIN_TARGET, MAIN_START, MAIN_END, log, sub=0)
    finally:
        l.close()
    return got[1] if got and got[1] else None


def compare(data, ref, base, log):
    """Print and log a byte-for-byte comparison of `data` against reference `ref`."""
    got_sha, ref_sha = hashlib.sha256(data).hexdigest(), hashlib.sha256(ref).hexdigest()
    if data == ref:
        print(f'MATCH: {len(data)} bytes, sha256 {got_sha}')
        sev('verify', result='match', bytes=len(data), sha256=got_sha)
        return True
    n = min(len(data), len(ref))
    diff = next((base + i for i in range(n) if data[i] != ref[i]), None)
    where = (f'first difference at {diff:#08x}' if diff is not None
             else f'equal for {n} bytes but lengths differ ({len(data)} vs {len(ref)})')
    print(f'MISMATCH: read sha256 {got_sha}, reference sha256 {ref_sha}; {where}')
    sev('verify', result='mismatch', bytes=len(data), sha256=got_sha,
        ref_sha256=ref_sha, first_diff=diff)
    return False


def cmd_verify(a, log):
    """Dump a region and compare it to a reference file. --source flash: S sub-0 read-back of
    the application flash (update mode), compared to --against (an image). --source dm: the
    DM-patch dump of --range (default blocks 0-2), compared to --against. Read-only."""
    if not a.against:
        sys.exit('refused: verify needs --against FILE (the reference to compare to).')
    ref = open(a.against, 'rb').read()
    if a.source == 'dm':
        start, end = a.range[0] if a.range else DM_BLOCKS_RANGE
        print(f'verify (DM dump {start:#08x}-{end:#08x}) against {a.against}...')
        data = dm_read_range(a, log, start, end)
        base = start
    else:                                   # flash read-back
        if not a.confirm_update_mode:
            sys.exit('refused: verify --source flash enters update mode (RBUPDATE). Add '
                     '--confirm-update-mode (it does not reset settings).')
        if len(ref) != MAIN_SIZE:
            sys.exit(f'refused: --against is {len(ref)} bytes, expected {MAIN_SIZE} '
                     f'(0x{MAIN_SIZE:X}) for the application flash.')
        print(f'verify (flash read-back) against {a.against}...')
        data = flash_read_back(a, log)
        base = MAIN_START
    if data is None:
        print('verify: nothing read back.')
        return False
    ok = compare(data, ref, base, log)
    if a.source == 'flash' and not a.in_update_mode:
        print('\nNOW: power-cycle the unit (off, 10 s, on), then check a VI? query.')
    return ok


def cmd_rollback(a, log):
    """Write the vendor (unpatched) MAIN 01.00 image — the rollback image. Same sequence and
    guards as `write`; counts as a MAIN flash write. Refuses anything but the vendor image."""
    if not a.image:
        sys.exit('refused: rollback needs --image (the vendor MAIN 01.00 image).')
    sha = hashlib.sha256(open(a.image, 'rb').read()).hexdigest()
    if sha != VENDOR_IMAGE_SHA:
        sys.exit(f'refused: {a.image} (sha256 {sha}) is not the vendor MAIN 01.00 image. '
                 'rollback writes only the unpatched vendor image; use `write` for the patch.')
    print('ROLLBACK: writing the vendor (unpatched) MAIN 01.00 image.')
    sev('rollback', image=a.image, sha256=sha)
    return cmd_write(a, log)


def main():
    ap = argparse.ArgumentParser(description='read-only AVR-4306 loader-protocol client')
    ap.add_argument('cmd', choices=['version', 'status', 'check', 'read', 'dmdump',
                                    'settings-save', 'settings-restore', 'verify',
                                    'write', 'rollback'])
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
    ap.add_argument('--image', help='write/rollback: firmware image; settings-restore: the '
                    '8,950-byte RAM settings file')
    ap.add_argument('--out', help='settings-save: output file (default dumps/settings-<ts>.bin)')
    ap.add_argument('--against', help='verify: reference file to compare the read-back to')
    ap.add_argument('--source', choices=['flash', 'dm'], default='flash',
                    help='verify: flash = S sub-0 read-back (update mode); dm = DM-patch dump')
    ap.add_argument('--confirm-write', action='store_true',
                    help='write/rollback: attest the safety-plan.md checklist is done')
    ap.add_argument('--confirm-restore', action='store_true',
                    help='settings-restore: proceed with the RAM settings write (no flash)')
    ap.add_argument('--power-cycle-exit', action='store_true',
                    help='settings-save/restore: exit by power cycle instead of X+RBNORM')
    ap.add_argument('--no-verify', action='store_true',
                    help='write: skip the read-back verify (not recommended)')
    ap.add_argument('--log', default=None, help='transcript file (default dumps/loader.log)')
    ap.add_argument('--session-log', default=None,
                    help='structured session log (default dumps/session-log.jsonl)')
    a = ap.parse_args()
    if a.target != 1:
        sys.exit('refused: only target 1 (MAIN) is supported')
    if a.cmd in ('write', 'rollback') and not a.image:
        sys.exit(f'refused: {a.cmd} needs --image')
    if a.cmd == 'settings-restore' and not a.image:
        sys.exit('refused: settings-restore needs --image')
    os.makedirs('dumps', exist_ok=True)
    lf = open(a.log or os.path.join('dumps', 'loader.log'), 'a')

    def log(msg):
        lf.write(f'{datetime.datetime.now().isoformat(timespec="milliseconds")} {msg}\n')
        lf.flush()

    global SESSION
    SESSION = Session(a.session_log or os.path.join('dumps', 'session-log.jsonl'), a.cmd, a.ip)
    log(f'--- {a.cmd} {a.ip} (session {SESSION.id})')
    ok = False
    try:
        ok = {'version': cmd_version, 'status': cmd_status, 'check': cmd_check,
              'read': cmd_read, 'dmdump': cmd_dmdump, 'settings-save': cmd_settings_save,
              'settings-restore': cmd_settings_restore, 'verify': cmd_verify,
              'write': cmd_write, 'rollback': cmd_rollback}[a.cmd](a, log)
    finally:
        sev('end', ok=bool(ok))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
