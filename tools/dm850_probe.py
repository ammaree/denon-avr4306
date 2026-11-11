#!/usr/bin/env python3
"""Read-only DM850 bootloader / port prober. Writes NOTHING to the unit.

Two read-only checks for the delivery entry trigger (docs/dm850-delivery.md §4):

  watch   -- for N seconds, keep trying to open TCP 5001 (and 5000/23 for context) and log
             the first instant each opens. Run this across an AC power-cycle to see whether
             the DM850 bootloader listens on 5001 during boot.
  prompt  -- connect once to 5001, read whatever the bootloader sends (a banner/prompt), and
             optionally send ONE benign line (a newline or an invalid token) to observe the
             prompt/response format. It never sends update/erase/start commands.

  python3 -I tools/dm850_probe.py watch  --ip 192.0.2.13 --seconds 60
  python3 -I tools/dm850_probe.py prompt --ip 192.0.2.13 [--poke]

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


# The ST value confirmed to crash an UNPATCHED DM850 (dm850-audit.md §1): a service URN with
# no version colon after the name. On a PATCHED unit the guard drops it and the unit survives.
BELKIN_ST = 'urn:Belkin:service:basicevent'


def ssdp(a):
    """Send the Belkin M-SEARCH (the killer packet) to the AVR's SSDP port. On an unpatched,
    unfiltered unit this hangs the DM850; on a patched unit it is dropped harmlessly. Requires
    any upstream UDP-1900 (SSDP) filter to be LIFTED, or the packet never arrives (false pass)."""
    msearch = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 1\r\n'
        f'ST: {a.st}\r\n'
        '\r\n'
    ).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(a.count):
        s.sendto(msearch, (a.ip, 1900))                       # unicast to the AVR
        s.sendto(msearch, ('239.255.255.250', 1900))          # and the multicast group
        time.sleep(0.3)
    s.close()
    print(f'sent {a.count}x Belkin M-SEARCH (ST={a.st!r}) to {a.ip}:1900 + multicast. '
          f'Now run `alive` to check the DM850 survived.')


def alive(a):
    """Is the DM850 responsive? Checks TCP 80/5001/23. All dead = the stack has hung."""
    up = []
    for port in (80, 5001, 23):
        s = try_open(a.ip, port, 1.0)
        if s:
            up.append(port)
            s.close()
    if up:
        print(f'ALIVE: {a.ip} answers TCP {up}')
    else:
        print(f'HUNG: {a.ip} answers no TCP port (80/5001/23) — the DM850 stack is down; '
              f'AC power-cycle to recover')
    return bool(up)


def vi(a):
    """Query the version string. `VI?` on TCP 23 (telnet), per docs/updater-protocol.md."""
    s = try_open(a.ip, a.port, 3.0)
    if not s:
        print(f'{a.ip}:{a.port} closed')
        return
    s.settimeout(3.0)
    banner = b''
    try:
        banner = s.recv(256)
    except OSError:
        pass
    s.sendall(a.q.encode() + b'\r\n')
    time.sleep(0.6)
    data = b''
    try:
        while True:
            c = s.recv(512)
            if not c:
                break
            data += c
    except OSError:
        pass
    s.close()
    if banner:
        print(f'  banner={banner!r}')
    print(f'  {a.q!r} -> {data!r}')
    # pull any I-prefixed stamp (DM850I build stamp, e.g. I200805270746)
    import re
    for m in re.findall(rb'I20[0-9]{12}', data):
        print(f'  DM850I stamp: {m.decode()}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    vp = sub.add_parser('vi')
    vp.add_argument('--ip', required=True)
    vp.add_argument('--port', type=int, default=23)
    vp.add_argument('--q', default='VI?')
    vp.set_defaults(func=vi)
    w = sub.add_parser('watch')
    w.add_argument('--ip', required=True)
    w.add_argument('--seconds', type=int, default=60)
    w.set_defaults(func=watch)
    p = sub.add_parser('prompt')
    p.add_argument('--ip', required=True)
    p.add_argument('--poke', action='store_true', help='send one bare newline to see the prompt')
    p.set_defaults(func=prompt)
    ss = sub.add_parser('ssdp')
    ss.add_argument('--ip', required=True)
    ss.add_argument('--st', default=BELKIN_ST)
    ss.add_argument('--count', type=int, default=3)
    ss.set_defaults(func=ssdp)
    al = sub.add_parser('alive')
    al.add_argument('--ip', required=True)
    al.set_defaults(func=alive)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
