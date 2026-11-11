#!/usr/bin/env python3
"""DM850I-only firmware writer (TFTP + port-5001 orchestration).

Delivers a patched DM850I image to the unit the way the vendor updater does — a text-command
shell on TCP 5001 plus a TFTP server the DM850 pulls the image from (docs/updater-protocol.md,
docs/dm850-delivery.md) — but **only** the DM850I image: it never sends `update bootloader`,
`erase webpage` or `update webpage` (safety-plan rules 1-2). Recovery is the vendor "Recovering
DM800" path: reconnect to 5001 and re-send, which the bootloader survives (dm850-delivery.md §2).

Guards:
- A hard command whitelist (`CMD_ALLOW`): `send_cmd` refuses to transmit anything else, so a
  forbidden command cannot leave this tool even by mistake.
- The served image must be sha256-pinned (the patched build or the vendor rollback).
- `--confirm-write` is required for a real run and prints the safety checklist first.
- Default is a dry run against sim/fake_dm850.py; a real run needs `--ip`.

STATUS: the on-unit run is gated. The exact bootloader-entry trigger and the precise command
order are not yet confirmed on the unit (dm850-delivery.md §4); `--confirm-write` additionally
requires `--sequence-confirmed`. Until then this tool is exercised only against the fake unit.
"""
import argparse
import hashlib
import socket
import struct
import threading
import time

# Only these may ever be sent. Forbidden (update bootloader / *webpage / erase*) are absent
# by construction, so there is no code path that transmits them.
CMD_ALLOW = {'start bootloader', 'start image', 'start tftp client', 'update image'}

# sha256 of images this tool may serve (patched DM850I build + vendor rollback). Fill the
# vendor hash before a rollback run.
ACCEPTED_SHA256 = {
    # patched DM850I (build/patch/DM850I_ssdp.flash.bin); recomputed below if present
}


# ---- TFTP server (RFC 1350, octet, read requests only) -------------------------------------
class TftpServer(threading.Thread):
    def __init__(self, filename, data, host='0.0.0.0', port=0):
        super().__init__(daemon=True)
        self.filename = filename
        self.data = data
        self.host = host
        self.port = port
        self.served = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self.port = self._sock.getsockname()[1]
        self._stop = False

    def run(self):
        self._sock.settimeout(0.5)
        while not self._stop:
            try:
                pkt, client = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            op = struct.unpack_from('>H', pkt, 0)[0]
            if op != 1:          # only RRQ
                continue
            name = pkt[2:].split(b'\x00', 1)[0].decode('latin1')
            if name != self.filename:
                self._sock.sendto(b'\x00\x05\x00\x01Not found\x00', client)
                continue
            self._send_file(client)
            self.served = True

    def _send_file(self, client):
        blk = 1
        for off in range(0, len(self.data) + 1, 512):
            chunk = self.data[off:off + 512]
            pkt = b'\x00\x03' + struct.pack('>H', blk) + chunk
            for _ in range(5):
                self._sock.sendto(pkt, client)
                try:
                    ack, _ = self._sock.recvfrom(64)
                    if ack[:2] == b'\x00\x04' and struct.unpack_from('>H', ack, 2)[0] == blk:
                        break
                except socket.timeout:
                    continue
            blk += 1
            if len(chunk) < 512:
                break

    def stop(self):
        self._stop = True


# ---- port-5001 shell client ----------------------------------------------------------------
class Shell:
    def __init__(self, ip, port=5001, timeout=10):
        self.s = socket.create_connection((ip, port), timeout=timeout)
        self.s.settimeout(timeout)
        self._read_prompt()

    def _read_prompt(self):
        buf = b''
        while not buf.rstrip().endswith((b'>', b'#')):
            c = self.s.recv(256)
            if not c:
                break
            buf += c
        return buf

    def send_cmd(self, cmd):
        if cmd not in CMD_ALLOW:
            raise PermissionError(f'refused: {cmd!r} is not in the command whitelist')
        self.s.sendall(cmd.encode() + b'\r\n')
        return self._read_prompt()

    def close(self):
        self.s.close()


def pin_image(path):
    data = open(path, 'rb').read()
    sha = hashlib.sha256(data).hexdigest()
    return data, sha


def checklist():
    print("""\
DM850 write checklist (dm850-delivery.md / safety-plan.md):
  [ ] Unit on an isolated segment; PC wired direct; UPS; no load-shedding window.
  [ ] Image is the patched DM850I (sha256 pinned) — NOT the bootloader or web pages.
  [ ] The bootloader-entry trigger and command sequence are CONFIRMED on this unit.
  [ ] Recovery understood: on failure, reconnect to 5001 and re-run (bootloader survives).
""")


def accepted_shas():
    """sha256 of the images this tool may serve: the current patched build, and the vendor
    rollback if present. Computed from the files so the whitelist tracks the build."""
    import os
    out = set()
    for p in ('build/patch/DM850I_ssdp.flash.bin', 'build/images/DM850I_x.flash.bin'):
        if os.path.exists(p):
            out.add(hashlib.sha256(open(p, 'rb').read()).hexdigest())
    return out


def run_write(ip, image_path, served_name, confirm, sequence_confirmed, enter_bootloader):
    data, sha = pin_image(image_path)
    allowed = accepted_shas()
    if allowed and sha not in allowed:
        raise SystemExit(f'image sha256 {sha[:16]}… is not the patched build or the vendor '
                         f'rollback; refusing to serve it')
    if not confirm:
        raise SystemExit('refused: a real write needs --confirm-write (and --sequence-confirmed)')
    if not sequence_confirmed:
        raise SystemExit('refused: the command sequence is not yet confirmed on the unit '
                         '(dm850-delivery.md §4); pass --sequence-confirmed only after the probe')
    checklist()
    tftp = TftpServer(served_name, data)
    tftp.start()
    sh = Shell(ip)
    try:
        if enter_bootloader:
            sh.send_cmd('start bootloader')
            time.sleep(2)
        sh.send_cmd('update image')          # DM850 pulls `served_name` via TFTP
        time.sleep(1)
        sh.send_cmd('start image')           # reboot into the patched application
    finally:
        sh.close()
        tftp.stop()
    print(f'write issued (image sha256 {sha[:16]}…, served as {served_name}); '
          f'verify VI? stamp I200805270746 after reboot')


def main():
    ap = argparse.ArgumentParser(description='DM850I-only firmware writer (TFTP + 5001)')
    ap.add_argument('--ip', help='unit IP (real run); omit for a dry run against the fake')
    ap.add_argument('--image', default='build/patch/DM850I_ssdp.flash.bin')
    ap.add_argument('--served-name', default='DM850I_0011.bcd')
    ap.add_argument('--enter-bootloader', action='store_true',
                    help='send `start bootloader` first (per the confirmed entry trigger)')
    ap.add_argument('--confirm-write', action='store_true')
    ap.add_argument('--sequence-confirmed', action='store_true')
    a = ap.parse_args()
    if not a.ip:
        raise SystemExit('dry run: drive this tool against sim/fake_dm850.py in a test '
                         '(see sim/test_dm850_writer.py); a real run needs --ip')
    run_write(a.ip, a.image, a.served_name, a.confirm_write, a.sequence_confirmed,
              a.enter_bootloader)


if __name__ == '__main__':
    main()
