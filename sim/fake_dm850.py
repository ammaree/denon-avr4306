#!/usr/bin/env python3
"""Fake DM850 bootloader for offline testing of tools/dm850_writer.py. Never touches a unit.

Models what the updater decompile established (docs/updater-protocol.md, dm850-delivery.md):
- A line shell on TCP 5001, prompt `#`. Commands `cmd\\r\\n`; known commands reply `ok\\r\\n#`.
  Known: erase image, update image, start tftp client, start image, start bootloader.
  Forbidden (refused with `NG`): update bootloader, erase webpage, update webpage.
- A TFTP SERVER on UDP: it receives the updater's WRQ (opcode 2), ACKs block 0 from a fresh
  TID, receives DATA (opcode 3) blocks and ACKs them, storing the bytes. If the client aborts
  with a TFTP ERROR after block-0 (the writer's --probe-wrq), it records that and stores nothing.
"""
import socket
import struct
import threading

PROMPT = b'#'
FORBIDDEN = {b'update bootloader', b'erase webpage', b'update webpage', b'erase bootloader'}
TFTP_WRQ, TFTP_DATA, TFTP_ACK, TFTP_ERR = 2, 3, 4, 5


class FakeTftpServer(threading.Thread):
    def __init__(self, host='127.0.0.1'):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, 0))
        self.host = host
        self.port = self.sock.getsockname()[1]
        self.received = None
        self.saw_wrq = False
        self.wrq_name = None
        self.probe_abort = False

    def run(self):
        self.sock.settimeout(8)
        try:
            pkt, client = self.sock.recvfrom(2048)
        except socket.timeout:
            return
        if struct.unpack_from('>H', pkt, 0)[0] != TFTP_WRQ:
            return
        self.saw_wrq = True
        self.wrq_name = pkt[2:].split(b'\x00', 1)[0].decode('latin1')
        tid = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # fresh TID, per RFC 1350
        tid.bind((self.host, 0))
        tid.settimeout(8)
        tid.sendto(struct.pack('>HH', TFTP_ACK, 0), client)      # ACK block 0
        data = bytearray()
        expected = 1
        while True:
            try:
                p, a = tid.recvfrom(2048)
            except socket.timeout:
                break
            op = struct.unpack_from('>H', p, 0)[0]
            if op == TFTP_ERR:
                self.probe_abort = True
                break
            if op != TFTP_DATA:
                continue
            blk = struct.unpack_from('>H', p, 2)[0]
            tid.sendto(struct.pack('>HH', TFTP_ACK, blk), a)
            if blk == expected:
                chunk = p[4:]
                data += chunk
                expected += 1
                if len(chunk) < 512:
                    self.received = bytes(data)
                    break
        tid.close()


class FakeShell:
    def __init__(self):
        self.commands = []
        self.refused = []
        self.started_image = False

    def handle(self, conn):
        conn.sendall(PROMPT)
        buf = b''
        while True:
            chunk = conn.recv(256)
            if not chunk:
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                cmd = line.strip(b'\r \t')
                if not cmd:
                    continue
                self.commands.append(cmd)
                if cmd in FORBIDDEN:
                    self.refused.append(cmd)
                    conn.sendall(b'NG\r\n' + PROMPT)
                elif cmd == b'start image':
                    self.started_image = True            # reboot: no reply
                elif cmd == b'start bootloader':
                    pass                                   # reboot: no reply
                else:
                    conn.sendall(b'ok\r\n' + PROMPT)

    def serve(self, host, port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        self.port = srv.getsockname()[1]
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=5001)
    a = ap.parse_args()
    t = FakeTftpServer(a.host)
    t.start()
    print(f'fake DM850: shell on {a.host}:{a.port}, TFTP server on {a.host}:{t.port}')
    FakeShell().serve(a.host, a.port)
