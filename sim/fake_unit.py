#!/usr/bin/env python3
"""Local stand-in for the AVR-4306 network + MAIN loader, for testing tools/loader_client.py.

Implements the protocol as decompiled from the 6.0.0.4 updater (docs/loader-interface.md
§2.4–2.6), nothing more:
  telnet port : 'VI?\\r' -> 'VIxxxx\\r';  'RBUPDATE\\r' -> 'RBSTART\\r' and update mode
  loader port : the same two text commands (the vendor update sends them on 5000), and
                AA frames: C -> C reply in update mode only (silent in normal mode, as the
                real unit on 2026-11-05); S -> ACK, then data frames of <= 0x400 bytes,
                each acknowledged by the PC; S is NACKed unless in update mode. As on the
                real unit, S ignores start/end: sub 0 streams the image (0xF00000..),
                sub 1 streams RAM 0x0400-0xC3FF
Memory: --image at 0xF00000 (e.g. build/images/MAIN_01.00.flash.bin); RAM 0x0400-0xC3FF
with low byte of addr*13+5.
--corrupt N sends every Nth data frame with a bad checksum (tests NACK/retry).
Any other frame type is answered with NACK and logged as a protocol violation.

  python3 -I sim/fake_unit.py --image build/images/MAIN_01.00.flash.bin [--corrupt 5]
"""
import argparse, socket, threading

STATE = {'update': False, 'violations': 0}


def ck(b):
    return sum(b) & 0xFF


def mem_read(img, addr):
    if 0x0400 <= addr <= 0xC3FF:
        return (addr * 13 + 5) & 0xFF
    if 0xF00000 <= addr < 0xF00000 + len(img):
        return img[addr - 0xF00000]
    return 0


def control_line(c, line):
    if STATE.get('dm') and len(line) == 9 and line[:2] == b'DM' and line[8:] == b'?':
        # DM patch (docs/main-dump-patch.md): 32 bytes as hex; resident blocks = pattern
        a = int(line[2:8], 16)
        if 0xF00000 <= a <= 0xFFFFE0:
            body = bytes(STATE['mem'](x) for x in range(a, a + 32))
            c.sendall(line[:8] + body.hex().upper().encode() + b'\r')
    elif line == b'VI?':
        c.sendall(b'VI01:0100;02:0050;03:0004;\r')
    elif line == b'RBUPDATE':
        STATE['update'] = True
        c.sendall(b'RBSTART\r')
    else:
        print('control: unexpected', line)


def serve_telnet(sock):
    while True:
        c, _ = sock.accept()
        buf = b''
        with c:
            while True:
                d = c.recv(256)
                if not d:
                    break
                buf += d
                while b'\r' in buf:
                    line, buf = buf.split(b'\r', 1)
                    control_line(c, line)


def recv_exact(c, n):
    b = b''
    while len(b) < n:
        d = c.recv(n - len(b))
        if not d:
            raise ConnectionError
        b += d
    return b


def serve_loader(sock, img, corrupt):
    nframe = 0
    while True:
        c, _ = sock.accept()
        with c:
            try:
                while True:
                    b0 = recv_exact(c, 1)
                    if b0 != b'\xAA':
                        line = b0
                        while not line.endswith(b'\r'):
                            line += recv_exact(c, 1)
                        control_line(c, line[:-1])
                        continue
                    h = b0 + recv_exact(c, 2)
                    t, tgt = h[1], h[2]
                    if t == ord('C'):
                        f = h + recv_exact(c, 1)
                        if STATE['update']:
                            rep = b'\xAA' + b'C' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                    elif t == ord('S'):
                        f = h + recv_exact(c, 10)
                        if ck(f[:-1]) != f[-1] or not STATE['update']:
                            rep = b'\xAAN' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                            continue
                        # As the real loader (2026-11-05): range ignored, sub-byte picks
                        # the area.
                        if f[3] == 1:
                            start, end = 0x0400, 0xC3FF
                        else:
                            start, end = 0xF00000, 0xF00000 + len(img) - 1
                        ack = b'\xAAA' + bytes([tgt])
                        c.sendall(ack + bytes([ck(ack)]))
                        a = start
                        while a <= end:
                            n = min(0x400, end - a + 1)
                            first, last = a == start, a + n > end
                            status = 0 if first and last else 1 if first else 3 if last else 2
                            body = bytes(mem_read(img, x) for x in range(a, a + n))
                            fr = (b'\xAAP' + bytes([tgt, status]) + n.to_bytes(2, 'big')
                                  + a.to_bytes(4, 'big') + body)
                            nframe += 1
                            bad = corrupt and nframe % corrupt == 0
                            c.sendall(fr + bytes([(ck(fr) + bad) & 0xFF]))
                            r = recv_exact(c, 4)
                            if r[1] == ord('A'):
                                a += n
                            elif r[1] != ord('N'):
                                STATE['violations'] += 1
                                print('loader: unexpected reply', r.hex())
                                break
                    elif t in (ord('A'), ord('N')):
                        recv_exact(c, 1)
                    else:
                        STATE['violations'] += 1
                        print(f'loader: PROTOCOL VIOLATION, frame type {chr(t)!r} sent to unit')
                        rep = b'\xAAN' + bytes([tgt])
                        c.sendall(rep + bytes([ck(rep)]))
            except ConnectionError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--telnet-port', type=int, default=2323)
    ap.add_argument('--loader-port', type=int, default=5050)
    ap.add_argument('--corrupt', type=int, default=0)
    ap.add_argument('--dm', action='store_true', help='answer DMaaaaaa? like the DM patch')
    a = ap.parse_args()
    img = open(a.image, 'rb').read()
    STATE['dm'] = a.dm
    STATE['mem'] = lambda x: (x * 7 + 3) & 0xFF if x >= 0xFFC000 else mem_read(img, x)
    ts = socket.create_server(('127.0.0.1', a.telnet_port))
    ls = socket.create_server(('127.0.0.1', a.loader_port))
    threading.Thread(target=serve_telnet, args=(ts,), daemon=True).start()
    print(f'fake unit on 127.0.0.1 telnet {a.telnet_port}, loader {a.loader_port}', flush=True)
    serve_loader(ls, img, a.corrupt)


if __name__ == '__main__':
    main()
