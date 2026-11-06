#!/usr/bin/env python3
"""Local stand-in for the AVR-4306 network + MAIN loader, for testing tools/loader_client.py.

Implements the protocol as decompiled from the 6.0.0.4 updater (docs/loader-interface.md
§2.4–2.6, §2.8), nothing more:
  telnet port : 'VI?\\r' -> 'VIxxxx\\r';  'RBUPDATE\\r' -> 'RBSTART\\r' and update mode
  loader port : the same two text commands (the vendor update sends them on 5000), and
                AA frames: C -> C reply in update mode only (silent in normal mode, as the
                real unit on 2026-11-05); S -> ACK, then data frames of <= 0x400 bytes,
                each acknowledged by the PC; S is NACKed unless in update mode. As on the
                real unit, S ignores start/end: sub 0 streams the image (0xF00000..),
                sub 1 streams RAM 0x0400-0xC3FF.
                I (0x49) -> fixed 54-byte reply carrying the model code at frame bytes
                5-6 (--model, default 0x0011 = AVR-4306) and a decoy at bytes 7-8;
                --i-badck corrupts its checksum; needs update mode.
                L (0x4C) -> ACK: begin a load. sub-0 flash load erases the range (sets 0xFF);
                sub-1 settings load (RAM 0x040C-0x2701) just overwrites.
                P (0x50) -> ACK per frame: data written into flash (img) or RAM per the
                address, so a following S read returns what was written. L/P need update mode.
                X (0x58) -> consumed (no reply): SSManage X(1,2,1) 'Reboot(Normal mode)'.
                RBNORM\\r -> RBSTART and leaves update mode (the SSManage exit).
                This is the write/restore side the vendor tools use (FUN_0041a070/FUN_0041a7e0;
                SSManage FUN_00402370->FUN_00403280); it lets `write`, `settings-save`,
                `settings-restore`, `verify` and `rollback` be tested without a real unit.
Memory: --image at 0xF00000 (e.g. build/images/MAIN_01.00.flash.bin); RAM 0x0400-0xC3FF
with low byte of addr*13+5. The image is held mutable so L/P writes are visible to S.
--corrupt N sends every Nth S data frame with a bad checksum (tests read NACK/retry).
--nack N NACKs the first attempt of every Nth P frame (tests write retry); the retry ACKs.
--write-out PATH dumps the image after a completed load (last P frame) for the test to check.
Any other frame type is answered with NACK and logged as a protocol violation.

  python3 -I sim/fake_unit.py --image build/images/MAIN_01.00.flash.bin [--corrupt 5]
"""
import argparse, socket, threading

STATE = {'update': False, 'violations': 0}
I_REPLY_LEN = 54                 # fixed 'I' target-information reply (loader-interface §2.8)


def ck(b):
    return sum(b) & 0xFF


def mem_read(img, addr):
    if 0x0400 <= addr <= 0xC3FF:
        return STATE['ram'][addr - 0x0400]        # mutable: settings restore writes here
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
    elif line == b'RBNORM':
        # SSManage 'Reboot(Normal mode)' exit (update-tools.md §3a): leave update mode.
        STATE['update'] = False
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


def serve_loader(sock, img, corrupt, nack=0, write_out=None):
    nframe = 0
    pframe = 0           # count of P frames seen, for --nack scheduling
    load = None          # (tgt, sub, version, start, end) from the last L, or None
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
                    elif t == ord('I'):
                        # target information: AA 49 tgt field1-32 field2-32 ck (12 B in),
                        # fixed 54-byte reply out (loader-interface §2.8, FUN_0041b290).
                        f = h + recv_exact(c, 9)
                        if ck(f[:-1]) != f[-1] or not STATE['update']:
                            rep = b'\xAAN' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                            continue
                        payload = bytearray(I_REPLY_LEN - 4)      # 50 B, frame bytes 3-52
                        model = STATE.get('model', 0x0011)
                        payload[2] = (model >> 8) & 0xFF          # frame byte 5 \ model code
                        payload[3] = model & 0xFF                 # frame byte 6 / (FUN_0041b290)
                        payload[4:6] = b'\x5A\x5A'                # frame bytes 7-8: decoy, so a
                                                                  # wrong offset fails the test
                        rep = b'\xAA' + b'I' + bytes([tgt]) + bytes(payload)
                        bad = 1 if STATE.get('i_badck') else 0
                        c.sendall(rep + bytes([(ck(rep) + bad) & 0xFF]))   # 3 + 50 + 1 = 54 B
                        print(f'loader: I -> model {model:#06x}')
                    elif t == ord('X'):
                        # SSManage 'Reboot(Normal mode)' mode frame X(1,2,1): AA 58 tgt 02 01
                        # ck (6 B). The vendor expects no reply (it just waits), so consume
                        # and stay quiet; RBNORM is what actually leaves update mode.
                        f = h + recv_exact(c, 3)
                        print(f'loader: X(1,2,1) mode frame {f.hex(" ")}')
                    elif t == ord('L'):
                        # begin load: AA 4C tgt sub vh vl start32 end32 ck (15 B total)
                        f = h + recv_exact(c, 12)
                        if ck(f[:-1]) != f[-1] or not STATE['update']:
                            rep = b'\xAAN' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                            continue
                        sub = f[3]
                        version = int.from_bytes(f[4:6], 'big')
                        start = int.from_bytes(f[6:10], 'big')
                        end = int.from_bytes(f[10:14], 'big')
                        load = (tgt, sub, version, start, end)
                        print(f'loader: L tgt={tgt} sub={sub} ver={version:#06x} '
                              f'{start:#08x}-{end:#08x}')
                        # Flash load (sub 0): erase the range (vendor erases on the first data
                        # frame; here on L so an incomplete write shows as 0xFF on read-back).
                        # RAM load (sub 1, settings): no erase, just overwrite.
                        if start >= 0xF00000:
                            lo = max(start, 0xF00000) - 0xF00000
                            hi = min(end, 0xF00000 + len(img) - 1) - 0xF00000
                            if 0 <= lo <= hi < len(img):
                                img[lo:hi + 1] = b'\xFF' * (hi + 1 - lo)
                        pframe = 0
                        ack = b'\xAAA' + bytes([tgt])
                        c.sendall(ack + bytes([ck(ack)]))
                    elif t == ord('P'):
                        # image data: AA 50 tgt status len16 addr32 payload ck
                        h2 = h + recv_exact(c, 7)        # status, len16, addr32
                        status = h2[3]
                        n = int.from_bytes(h2[4:6], 'big')
                        addr = int.from_bytes(h2[6:10], 'big')
                        f = h2 + recv_exact(c, n + 1)    # payload + ck
                        pframe += 1
                        if ck(f[:-1]) != f[-1] or load is None or not STATE['update']:
                            STATE['violations'] += 1 if load is None else 0
                            rep = b'\xAAN' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                            continue
                        if nack and pframe % nack == 0 and pframe not in STATE.setdefault('nacked', set()):
                            STATE['nacked'].add(pframe)        # NACK once; the retry gets through
                            rep = b'\xAAN' + bytes([tgt])
                            c.sendall(rep + bytes([ck(rep)]))
                            continue
                        payload = f[10:10 + n]
                        if 0xF00000 <= addr and addr - 0xF00000 + n <= len(img):
                            img[addr - 0xF00000:addr - 0xF00000 + n] = payload   # flash
                        elif 0x0400 <= addr and addr - 0x0400 + n <= len(STATE['ram']):
                            STATE['ram'][addr - 0x0400:addr - 0x0400 + n] = payload  # RAM/settings
                        ack = b'\xAAA' + bytes([tgt])
                        c.sendall(ack + bytes([ck(ack)]))
                        if status in (0, 3):             # 'only' or 'last' frame: load done
                            print(f'loader: load complete, {pframe} P frames')
                            if write_out and load is not None:
                                _, _, _, ls, le = load
                                if ls >= 0xF00000:
                                    blob = bytes(img[ls - 0xF00000:le - 0xF00000 + 1])
                                else:
                                    blob = bytes(STATE['ram'][ls - 0x0400:le - 0x0400 + 1])
                                open(write_out, 'wb').write(blob)
                            load = None
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
    ap.add_argument('--nack', type=int, default=0,
                    help='NACK the first attempt of every Nth P frame (tests write retry)')
    ap.add_argument('--write-out', default=None,
                    help='dump the image after a completed load (last P frame)')
    ap.add_argument('--dm', action='store_true', help='answer DMaaaaaa? like the DM patch')
    ap.add_argument('--start-update', action='store_true',
                    help='boot already in update mode (skip RBUPDATE; for fast write tests)')
    ap.add_argument('--model', type=lambda x: int(x, 0), default=0x0011,
                    help="model code in the 'I' reply (default 0x0011 = AVR-4306)")
    ap.add_argument('--i-badck', action='store_true',
                    help="send the 'I' reply with a bad checksum (tests rejection)")
    a = ap.parse_args()
    img = bytearray(open(a.image, 'rb').read())      # mutable: L/P writes are visible to S
    # Parameter RAM 0x0400-0xC3FF, seeded with the old synthetic pattern; settings restore
    # (L sub 1 + P) overwrites it, and a sub-1 S read streams it back.
    STATE['ram'] = bytearray((x * 13 + 5) & 0xFF for x in range(0x0400, 0xC400))
    STATE['dm'] = a.dm
    STATE['update'] = a.start_update
    STATE['model'] = a.model
    STATE['i_badck'] = a.i_badck
    STATE['mem'] = lambda x: (x * 7 + 3) & 0xFF if x >= 0xFFC000 else mem_read(img, x)
    ts = socket.create_server(('127.0.0.1', a.telnet_port))
    ls = socket.create_server(('127.0.0.1', a.loader_port))
    threading.Thread(target=serve_telnet, args=(ts,), daemon=True).start()
    print(f'fake unit on 127.0.0.1 telnet {a.telnet_port}, loader {a.loader_port}', flush=True)
    serve_loader(ls, img, a.corrupt, a.nack, a.write_out)


if __name__ == '__main__':
    main()
