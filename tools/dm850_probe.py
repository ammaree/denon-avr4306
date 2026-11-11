#!/usr/bin/env python3
"""Read-only DM850 bootloader / port prober. Writes NOTHING to the unit.

Two read-only checks for the delivery entry trigger (docs/dm850-delivery.md §4):

  watch   -- for N seconds, keep trying to open TCP 5001 (and 5000/23 for context) and log
             the first instant each opens. Run this across an AC power-cycle to see whether
             the DM850 bootloader listens on 5001 during boot.
  prompt  -- connect once to 5001, read whatever the bootloader sends (a banner/prompt), and
             optionally send ONE benign line (a newline or an invalid token) to observe the
             prompt/response format. It never sends update/erase/start commands.

  python3 -I tools/dm850_probe.py watch  --ip 192.168.1.13 --seconds 60
  python3 -I tools/dm850_probe.py prompt --ip 192.168.1.13 [--poke]

Only connect() and recv() touch the unit (and, with --poke, a single harmless byte). There is
no path here that sends a bootloader command, so nothing can be erased or written.
"""
import argparse
import socket
import time

# A guard: the poke may only ever be one of these harmless bytes/lines. No command token.
SAFE_POKES = {b'\r\n', b'\n', b'?\r\n', b'help\r\n'}


def try_open(ip, port, timeout=0.4):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return s
    except OSError:
        s.close()
        return None


def watch(a):
    ports = (5001, 5000, 23, 80)
    print(f'watching {a.ip} ports {ports} for {a.seconds}s — logging every open/close '
          f'transition. Power-cycle the unit now.')
    start = time.time()
    state = {p: None for p in ports}     # None unknown, True open, False closed
    while time.time() - start < a.seconds:
        t = time.time() - start
        for port in ports:
            s = try_open(a.ip, port, 0.3)
            now_open = s is not None
            banner = b''
            if s:
                try:
                    s.settimeout(0.4)
                    banner = s.recv(64)
                except OSError:
                    pass
                s.close()
            if state[port] is None or now_open != state[port]:
                tag = 'OPEN ' if now_open else 'close'
                print(f'  t={t:5.1f}s  TCP {port:<4} {tag}'
                      + (f'  banner={banner[:40]!r}' if banner else ''))
                state[port] = now_open
        time.sleep(0.4)
    print('final:', {p: ('open' if v else 'closed') for p, v in state.items()})


def prompt(a):
    s = try_open(a.ip, 5001, 2.0)
    if not s:
        print('5001 is closed — not in bootloader mode (run `watch` across a power-cycle first)')
        return
    s.settimeout(2.0)
    data = b''
    try:
        data = s.recv(256)
    except OSError:
        pass
    print(f'5001 connected; initial bytes = {data!r}')
    if a.poke:
        poke = b'\r\n'
        assert poke in SAFE_POKES
        s.sendall(poke)        # a bare newline — not a command
        time.sleep(0.5)
        try:
            resp = s.recv(256)
        except OSError:
            resp = b''
        print(f'after a bare newline, got = {resp!r}')
    s.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('watch')
    w.add_argument('--ip', required=True)
    w.add_argument('--seconds', type=int, default=60)
    w.set_defaults(func=watch)
    p = sub.add_parser('prompt')
    p.add_argument('--ip', required=True)
    p.add_argument('--poke', action='store_true', help='send one bare newline to see the prompt')
    p.set_defaults(func=prompt)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
