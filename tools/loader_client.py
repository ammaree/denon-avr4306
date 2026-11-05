#!/usr/bin/env python3
"""Read-only client for the AVR-4306 MAIN loader protocol.

Protocol decompiled from the 6.0.0.4 updater (docs/loader-interface.md §2.4–2.6):
telnet TCP 23 carries control-protocol commands (`VI?`, `RBUPDATE`); TCP 5000 carries raw
AA-framed loader frames, bridged by the DM850 to MAIN.

  frame   = AA <type> <target> ... <ck>        ck = low byte of the sum of all prior bytes
  C       = AA 'C' tgt ck                       connect / target info (reply type 'C')
  S       = AA 'S' tgt 00 start32 end32 ck      read memory start..end (BE); reply ACK, then
                                                data frames
  data    = AA 'D'|'P' tgt status len16 addr32 payload ck
            status 0 = only, 1 = first, 2 = middle, 3 = last frame
  A / N   = AA 'A'|'N' tgt ck                   ACK / NACK from the PC after each data frame

SAFETY (docs/safety-plan.md): the frame builder can only produce C, S, A and N frames. It
cannot produce L (load/erase) or send P data to the unit, and nothing here sends DM850
loader commands, RBNORM, or any state-changing control command. `S` is sent only after the
unit has answered RBUPDATE with RBSTART. Every connection is opened one at a time, with a
delay, because the DM850 hangs under fast connection churn (docs/lan-access.md).

Commands:
  loader_client.py version --ip IP               telnet 'VI?' (normal mode, read-only)
  loader_client.py check   --ip IP               port 5000 'C' frame (vendor "Check
                                                 communication"), normal mode
  loader_client.py read    --ip IP --start A --end B --confirm-update-mode
        RBUPDATE -> RBSTART, then C and S(A, B) on port 5000; saves the bytes to dumps/
        with a sha256. Afterwards the unit must be power-cycled (vendor procedure).

Run with python3 -I. --telnet-port / --loader-port exist for the local test peer
(sim/fake_unit.py).
"""
import argparse, datetime, hashlib, os, socket, sys, time

ALLOWED_TYPES = {b'C', b'S', b'A', b'N'}     # frames this tool may ever send
MAX_READ = 0x400000
DATA_TYPES = (ord('D'), ord('P'))


def ck(b):
    return sum(b) & 0xFF


def frame(ftype, tgt, body=b''):
    if ftype not in ALLOWED_TYPES:
        raise ValueError(f'refused: frame type {ftype!r} is not read-only')
    f = b'\xAA' + ftype + bytes([tgt]) + body
    return f + bytes([ck(f)])


def frame_s(tgt, start, end):
    return frame(b'S', tgt, b'\x00' + start.to_bytes(4, 'big') + end.to_bytes(4, 'big'))


class Link:
    """One TCP connection with a receive buffer and a transcript."""

    def __init__(self, ip, port, log, timeout=6.0):
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
    t = Link(a.ip, a.telnet_port, log)
    try:
        t.send(b'VI?\r')
        ok, got = t.wait_text(b'VI', 3.0)
        print('VI reply:', got.decode('latin1', 'replace').strip() if ok else '(none)')
        return ok
    finally:
        t.close()


def connect_check(link, tgt, log):
    link.send(frame(b'C', tgt))
    f = link.read_frame(6.0)
    log(f'< C reply: {desc(f)}' + (f' {f.hex(" ")}' if f else ''))
    return f is not None and f[1] == ord('C') and ck(f[:-1]) == f[-1]


def cmd_check(a, log):
    l = Link(a.ip, a.loader_port, log)
    try:
        ok = connect_check(l, a.target, log)
        print('Check communication:', 'OK' if ok else 'NG')
        return ok
    finally:
        l.close()


def read_range(link, tgt, start, end, log):
    link.send(frame_s(tgt, start, end))
    f = link.read_frame(6.0)
    log(f'< S reply: {desc(f)}')
    if f is None or f[1] != ord('A') or ck(f[:-1]) != f[-1]:
        print('S not acknowledged:', desc(f), '— loader refused or not in update mode')
        return None
    data, retries, expect = bytearray(), 0, start
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
        data += f[10:10 + n]
        expect = addr + n
        retries = 0
        link.send(frame(b'A', tgt))
        log(f'< data status={status} addr={addr:#08x} len={n}')
        if status in (0, 3):
            return bytes(data)
        if status not in (1, 2):
            print(f'unexpected status {status}; stopping')
            return bytes(data)
        if len(data) > MAX_READ:
            print('read exceeds 4 MB; stopping')
            return bytes(data)


def cmd_read(a, log):
    if not a.confirm_update_mode:
        sys.exit('refused: `read` puts the unit in update mode. Follow docs/safety-plan.md '
                 '(UPS, direct cable, nothing else on the LAN), then add --confirm-update-mode.')
    if a.end < a.start or a.end - a.start + 1 > MAX_READ:
        sys.exit('refused: range must be 1 byte .. 4 MB')
    # 1. Vendor "Check communication": port 5000, C frame, normal mode.
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, a.target, log):
            sys.exit('C frame not answered in normal mode; nothing changed on the unit.')
    finally:
        l.close()
    time.sleep(a.delay)
    # 2. Enter update mode exactly as the vendor tool does: RBUPDATE over telnet, wait RBSTART.
    t = Link(a.ip, a.telnet_port, log)
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
    print('unit confirmed update mode (RBSTART)')
    time.sleep(a.delay)
    # 3. Loader: C, then the read.
    l = Link(a.ip, a.loader_port, log)
    try:
        if not connect_check(l, a.target, log):
            print('loader did not answer C after RBSTART')
            data = None
        else:
            data = read_range(l, a.target, a.start, a.end, log)
    finally:
        l.close()
    if data:
        d = os.path.join('dumps', 'loader-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f'tgt{a.target:02X}_{a.start:06X}_{a.end:06X}.bin')
        open(p, 'wb').write(data)
        print(f'{p}: {len(data)} bytes (asked {a.end - a.start + 1}), '
              f'sha256 {hashlib.sha256(data).hexdigest()}')
    print('\nNOW: turn the unit off with its power switch, wait 10 s, turn it on '
          '(vendor manual 3.9-3). Then check the version screen and a VI? query.')
    return bool(data)


def main():
    ap = argparse.ArgumentParser(description='read-only AVR-4306 loader-protocol client')
    ap.add_argument('cmd', choices=['version', 'check', 'read'])
    ap.add_argument('--ip', required=True)
    ap.add_argument('--telnet-port', type=int, default=23)
    ap.add_argument('--loader-port', type=int, default=5000)
    ap.add_argument('--target', type=lambda x: int(x, 0), default=1, help='1 = MAIN')
    ap.add_argument('--start', type=lambda x: int(x, 0), default=0xFFC000)
    ap.add_argument('--end', type=lambda x: int(x, 0), default=0xFFFFFF)
    ap.add_argument('--delay', type=float, default=2.0, help='seconds between connections')
    ap.add_argument('--confirm-update-mode', action='store_true')
    ap.add_argument('--log', default=None, help='transcript file (default dumps/loader.log)')
    a = ap.parse_args()
    if a.target != 1:
        sys.exit('refused: only target 1 (MAIN) is supported')
    os.makedirs('dumps', exist_ok=True)
    lf = open(a.log or os.path.join('dumps', 'loader.log'), 'a')

    def log(msg):
        lf.write(f'{datetime.datetime.now().isoformat(timespec="milliseconds")} {msg}\n')
        lf.flush()

    log(f'--- {a.cmd} {a.ip}')
    ok = {'version': cmd_version, 'check': cmd_check, 'read': cmd_read}[a.cmd](a, log)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
