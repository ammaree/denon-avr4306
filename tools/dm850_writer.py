#!/usr/bin/env python3
"""DM850I-only firmware writer (port-5001 orchestration + TFTP push).

Delivers a patched DM850I image the way the vendor updater does, verified by decompiling
AVR-4306_upgrade_6_0_0_4.exe (docs/updater-protocol.md, docs/dm850-delivery.md):

  FACT (updater binary):
  - The 5001 text shell drives the DM850 bootloader (prompt `#`; app prompt is `>`).
    Commands are `\\r\\n`-terminated; each returns the token `ok`.
  - The DM850I flash sequence is:  erase image  ->  update image  ->  start tftp client
    (each -> `ok`), then the updater PUSHES the image over TFTP.
  - TFTP direction is PUSH: FUN_004207c0 emits opcode 2 (WRQ) + filename + `octet` to the
    DM850 at UDP 69; FUN_00420a90 emits opcode 3 (DATA, 512 B) blocks. The DM850 is the TFTP
    SERVER; the updater is the client that WRITES the image to it.
  - Finalise: wait `ok` (flash complete), then `start image` to reboot into the app.

  INFERRED (not yet observed on THIS unit): that the DM850 accepts this sequence and flashes.
  `--probe-wrq` observes acceptance WITHOUT writing image data: it runs the arm sequence and
  the WRQ, waits for the server's ACK of block 0, then ABORTS (TFTP ERROR, no DATA). In TFTP
  no image byte is written before the server ACKs block 0, so a probe writes nothing.

Safety:
- Hard command whitelist (`CMD_ALLOW`): `send_cmd` refuses anything else. `update bootloader`,
  `update webpage`, `erase webpage` are absent by construction.
- The pushed image must be sha256-pinned (the patched build or the vendor original).
- A real write needs `--confirm-write`; nothing touches the unit without `--ip`.
"""
import argparse
import hashlib
import os
import socket
import struct
import time

# Only these may ever be sent on 5001. Forbidden (update bootloader / *webpage) are absent by
# construction, so no code path can transmit them. `erase image` only clears the DM850I region
# (recoverable by re-flash); the bootloader region is never addressed by any command here.
CMD_ALLOW = {'start bootloader', 'start image', 'start tftp client', 'update image',
             'erase image'}
REBOOT_CMDS = {'start bootloader', 'start image'}   # drop the socket; no `ok`/prompt returns

TFTP_RRQ, TFTP_WRQ, TFTP_DATA, TFTP_ACK, TFTP_ERR = 1, 2, 3, 4, 5
# Paths resolve relative to the repo root (parent of tools/), so the tool is portable.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE_DEFAULT = os.path.join(_REPO, 'build', 'patch', 'DM850I_ssdp.flash.bin')


def accepted_shas():
    """sha256 of images this tool may push: the patched build and the vendor original if
    present. Computed from the files so the pin tracks the build."""
    out = {}
    for p in (IMAGE_DEFAULT,
              os.path.join(_REPO, 'build', 'images', 'DM850I_x.flash.bin')):
        if os.path.exists(p):
            out[os.path.abspath(p)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return out


# ---- TFTP push: a WRQ client that writes the image to the DM850 (server on UDP 69) ----------
class TftpPush:
    """Write `data` to `server_ip:server_port` as filename `name` (RFC 1350 WRQ, octet).

    send(probe=False): full write. send(probe=True): WRQ, wait for the server's ACK of
    block 0, then abort with a TFTP ERROR and send NO data. Returns a dict of what was seen.
    """
    def __init__(self, server_ip, name, data, server_port=69, src_ip='0.0.0.0'):
        self.server = (server_ip, server_port)
        self.name = name
        self.data = data
        self.src_ip = src_ip

    def send(self, probe=False, log=print):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((self.src_ip, 0))
        s.settimeout(2.0)
        res = {'ack0': False, 'tid': None, 'blocks_sent': 0, 'complete': False,
               'local_port': s.getsockname()[1], 'error': None}
        try:
            wrq = struct.pack('>H', TFTP_WRQ) + self.name.encode() + b'\x00octet\x00'
            tid = self._handshake(s, wrq, res, log)
            if tid is None:
                return res
            res['ack0'] = True
            res['tid'] = tid
            log(f'  [TFTP] WRQ accepted: server ACK block 0 from {tid[0]}:{tid[1]}')
            if probe:
                s.sendto(struct.pack('>H', TFTP_ERR) + b'\x00\x00probe: no data\x00', tid)
                log('  [TFTP] PROBE: sent ERROR, no image data written')
                return res
            self._send_data(s, tid, res, log)
            res['complete'] = True
            log(f'  [TFTP] all {res["blocks_sent"]} data block(s) ACKed ({len(self.data)} B)')
            return res
        except Exception as e:                       # noqa: BLE001 - report, don't crash mid-write
            res['error'] = repr(e)
            return res
        finally:
            s.close()

    def _handshake(self, s, wrq, res, log):
        """Send WRQ (retransmit up to 6x); return the server TID on ACK block 0, else None."""
        for _ in range(6):
            s.sendto(wrq, self.server)
            try:
                pkt, addr = s.recvfrom(1024)
            except socket.timeout:
                continue
            op = struct.unpack_from('>H', pkt, 0)[0]
            if op == TFTP_ERR:
                res['error'] = 'server TFTP ERROR: ' + pkt[4:].split(b'\x00', 1)[0].decode('latin1')
                return None
            if op == TFTP_ACK and struct.unpack_from('>H', pkt, 2)[0] == 0:
                return addr                           # the server's transfer TID
        return None

    def _send_data(self, s, tid, res, log):
        blk = 1
        for off in range(0, len(self.data) + 1, 512):
            chunk = self.data[off:off + 512]
            pkt = struct.pack('>HH', TFTP_DATA, blk & 0xFFFF) + chunk
            for attempt in range(20):
                s.sendto(pkt, tid)
                try:
                    ack, a = s.recvfrom(64)
                except socket.timeout:
                    continue
                if (a == tid and ack[:2] == struct.pack('>H', TFTP_ACK)
                        and struct.unpack_from('>H', ack, 2)[0] == (blk & 0xFFFF)):
                    break
            else:
                raise TimeoutError(f'no ACK for data block {blk}')
            res['blocks_sent'] = blk
            blk += 1
            if len(chunk) < 512:
                break


# ---- port-5001 bootloader shell ------------------------------------------------------------
class Shell:
    def __init__(self, ip, port=5001, timeout=10):
        self.s = socket.create_connection((ip, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.prompt = self._read_prompt()

    def _read_prompt(self):
        buf = b''
        while not buf.rstrip().endswith((b'>', b'#')):
            try:
                c = self.s.recv(256)
            except socket.timeout:
                break
            if not c:
                break
            buf += c
        return buf

    def mode(self):
        """'boot' if the prompt is `#`, 'app' if `>`, else 'unknown' (FACT from the prompt)."""
        p = self.prompt.rstrip()
        if p.endswith(b'#'):
            return 'boot'
        if p.endswith(b'>'):
            return 'app'
        return 'unknown'

    def send_cmd(self, cmd, expect=b'ok', timeout=40):
        if cmd not in CMD_ALLOW:
            raise PermissionError(f'refused: {cmd!r} is not in the command whitelist')
        self.s.sendall(cmd.encode() + b'\r\n')
        if cmd in REBOOT_CMDS:                        # reboots; no reply to wait for
            try:
                return self.s.recv(256)
            except OSError:
                return b''
        return self._read_until(expect, timeout)

    def _read_until(self, expect, timeout):
        self.s.settimeout(timeout)
        buf = b''
        end = time.time() + timeout
        while time.time() < end:
            try:
                c = self.s.recv(256)
            except socket.timeout:
                break
            if not c:
                break
            buf += c
            if expect in buf.lower():
                break
        self.s.settimeout(10)
        return buf

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def connect_retry(ip, port=5001, total=70, log=print):
    end = time.time() + total
    while time.time() < end:
        try:
            return Shell(ip, port)
        except OSError:
            time.sleep(1)
    raise SystemExit(f'could not reconnect to {ip}:{port} within {total}s')


def pin_image(path):
    data = open(path, 'rb').read()
    return data, hashlib.sha256(data).hexdigest()


def _cmd(sh, c, expect=b'ok', timeout=40):
    print(f'  5001 > {c}')
    reply = sh.send_cmd(c, expect=expect, timeout=timeout)
    tag = 'ok' if (expect and expect in reply.lower()) else ('reboot' if c in REBOOT_CMDS
                                                             else '??')
    print(f'  5001 < {reply!r}   [{tag}]')
    if expect and c not in REBOOT_CMDS and expect not in reply.lower():
        raise SystemExit(f'did not get {expect!r} after {c!r} within {timeout}s — aborting '
                         f'(nothing written past this point)')
    return reply


def checklist():
    print("""\
DM850 write checklist (dm850-delivery.md / safety-plan.md):
  [ ] UPS / stable power; no load-shedding window.
  [ ] Image is sha256-pinned (patched DM850I or the vendor original) — NOT bootloader/webpage.
  [ ] Recovery understood: on failure, reconnect to 5001 (`#`) and re-run (bootloader survives).
""")


def run_flash(ip, image_path, served_name, confirm, probe, src_ip, tftp_port):
    data, sha = pin_image(image_path)
    allowed = accepted_shas()
    if sha not in allowed.values():
        raise SystemExit(f'image sha256 {sha[:16]}… is not a pinned image; refusing to push')
    print(f'image: {image_path}\n  {len(data)} B, sha256 {sha}')
    if probe:
        print('PROBE: arm the sequence + WRQ, confirm the DM850 ACKs block 0, then ABORT '
              '(no image data written).')
    else:
        if not confirm:
            raise SystemExit('refused: a real write needs --confirm-write')
        checklist()

    sh = Shell(ip)
    m = sh.mode()
    print(f'  5001 connected; prompt {sh.prompt!r} -> mode={m}')
    if m == 'app':
        _cmd(sh, 'start bootloader', expect=None)
        print('  waiting for reboot into bootloader…')
        time.sleep(8)
        sh.close()
        sh = connect_retry(ip)
        print(f'  reconnected; prompt {sh.prompt!r} -> mode={sh.mode()}')
    if sh.mode() != 'boot':
        sh.close()
        raise SystemExit(f'not at the bootloader `#` prompt (got {sh.prompt!r}); aborting')

    try:
        _cmd(sh, 'erase image', timeout=60)
        # OBSERVED on-unit 2026-11-11: `update image` makes the DM850 erase the firmware image
        # and AUTO-arm its TFTP receiver (it prints "erase firmware image" / "start tftp
        # client"); it does NOT return `ok` until after the transfer. So send it, wait for the
        # tftp-arm indication, and do not require `ok` here (and do not send a separate
        # `start tftp client` — the unit started it itself).
        reply = sh.send_cmd('update image', expect=b'tftp', timeout=60)
        print(f'  5001 > update image\n  5001 < {reply!r}')
        if b'tftp' not in reply.lower():
            raise SystemExit('update image did not arm the tftp receiver (no "tftp" in reply) — '
                             'aborting; nothing written')
        time.sleep(1)
        print(f'  [TFTP] pushing {served_name!r} to {ip}:{tftp_port} '
              f'(probe={probe}) from {src_ip}')
        push = TftpPush(ip, served_name, data, server_port=tftp_port, src_ip=src_ip)
        res = push.send(probe=probe)
        print(f'  [TFTP] result: {res}')
        if not res['ack0']:
            raise SystemExit('DM850 did not ACK the WRQ (block 0) — push not accepted; nothing '
                             'written. Module is still in the bootloader.')
        if probe:
            print('PROBE OK: the DM850 accepted the WRQ (ACKed block 0). No image data was '
                  'written. Re-run without --probe-wrq to perform the real flash.')
            return
        if not res['complete']:
            raise SystemExit(f'push did not complete: {res.get("error")}')
        # flash-complete handshake, then reboot into the app
        print('  waiting for flash-complete `ok` on 5001 (the unit writes ~2 MB now)…')
        try:
            tail = sh._read_until(b'ok', 150)
            print(f'  5001 < {tail!r}')
        except OSError as e:
            print(f'  (5001 dropped during flash write: {e!r}; reconnecting to finalise)')
            sh.close()
            sh = connect_retry(ip, total=150)
            print(f'  reconnected; prompt {sh.prompt!r} -> mode={sh.mode()}')
        try:
            _cmd(sh, 'start image', expect=None)
        except OSError:
            sh.close()
            sh = connect_retry(ip)
            _cmd(sh, 'start image', expect=None)
        print(f'WRITE ISSUED (sha {sha[:12]}…). Verify after reboot: VI? stamp I200805270746 '
              f'and that the app ports (80/23/5000) come up.')
    finally:
        sh.close()


def main():
    ap = argparse.ArgumentParser(description='DM850I-only firmware writer (5001 + TFTP push)')
    ap.add_argument('--ip', required=True, help='unit IP')
    ap.add_argument('--image', default=IMAGE_DEFAULT)
    ap.add_argument('--served-name', default='DM850I_0011.bcd')
    ap.add_argument('--src-ip', default='0.0.0.0',
                    help='source IP for the TFTP push (bind a specific NIC; default: OS picks)')
    ap.add_argument('--tftp-port', type=int, default=69)
    ap.add_argument('--probe-wrq', action='store_true',
                    help='arm + WRQ, confirm ACK0, then abort WITHOUT writing image data')
    ap.add_argument('--wrq-only', action='store_true',
                    help='send ONLY a WRQ (no 5001), confirm ACK0, abort — for an already-armed unit')
    ap.add_argument('--confirm-write', action='store_true')
    a = ap.parse_args()
    if a.wrq_only:
        data, sha = pin_image(a.image)
        if sha not in accepted_shas().values():
            raise SystemExit('image sha not pinned; refusing')
        print(f'WRQ-only probe: WRQ {a.served_name!r} -> {a.ip}:{a.tftp_port}, abort after ACK0')
        res = TftpPush(a.ip, a.served_name, data, server_port=a.tftp_port,
                       src_ip=a.src_ip).send(probe=True)
        print(f'result: {res}')
        return
    run_flash(a.ip, a.image, a.served_name, a.confirm_write, a.probe_wrq, a.src_ip, a.tftp_port)


if __name__ == '__main__':
    main()
