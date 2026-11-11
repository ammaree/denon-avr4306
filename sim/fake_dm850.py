#!/usr/bin/env python3
"""Fake DM850 bootloader for offline testing of the DM850I writer (tools/dm850_writer.py).

Pure simulation — never touches a real unit. It models what docs/updater-protocol.md and
docs/dm850-delivery.md establish about the DM850 bootloader:

- A line-based shell on TCP 5001: it prints a prompt (`>`), reads `command\r\n`, replies.
- Known commands: `start bootloader`, `start image`, `start tftp client`, `update image`.
- On `update image` (or `start tftp client`) it acts as a TFTP client and *pulls* the image
  file `<name>` from the writer's TFTP server (RFC 1350, octet), storing what it receives so
  a test can check the bytes delivered.
- It refuses the forbidden commands so a test can assert the writer never sends them:
  `update bootloader`, `erase image`, `erase webpage`, `update webpage`.

  python3 -I sim/fake_dm850.py --help
"""
import argparse
import os
import socket
import struct
import threading

PROMPT = b'>'
FORBIDDEN = {b'update bootloader', b'erase image', b'erase webpage', b'update webpage'}


class FakeDm850:
    def __init__(self, tftp_server=None, image_name=None):
        self.tftp_server = tftp_server      # (host, port) of the writer's TFTP server
        self.image_name = image_name        # the .bcd name to request
        self.received = None                # bytes pulled via TFTP
        self.commands = []                  # every command line received
        self.refused = []                   # forbidden commands seen
        self.started_image = False

    def tftp_pull(self, name):
        """RFC 1350 TFTP read request (octet) from self.tftp_server; return the file bytes."""
        host, port = self.tftp_server
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5)
        rrq = b'\x00\x01' + name.encode() + b'\x00octet\x00'
        s.sendto(rrq, (host, port))
        data = bytearray()
        expected = 1
        while True:
            pkt, addr = s.recvfrom(1024)
            op = struct.unpack_from('>H', pkt, 0)[0]
            if op == 5:   # ERROR
                raise RuntimeError('TFTP error: ' + pkt[4:].split(b'\x00')[0].decode('latin1'))
            if op != 3:   # not DATA
                raise RuntimeError(f'unexpected TFTP op {op}')
            blk = struct.unpack_from('>H', pkt, 2)[0]
            if blk == expected:
                chunk = pkt[4:]
                data += chunk
                s.sendto(b'\x00\x04' + struct.pack('>H', blk), addr)   # ACK
                expected += 1
                if len(chunk) < 512:
                    break
            else:
                s.sendto(b'\x00\x04' + struct.pack('>H', blk), addr)
        s.close()
        return bytes(data)

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
                    continue
                if cmd == b'start image':
                    self.started_image = True
                    conn.sendall(b'OK\r\n' + PROMPT)
                elif cmd in (b'update image', b'start tftp client'):
                    if self.tftp_server and self.image_name:
                        try:
                            self.received = self.tftp_pull(self.image_name)
                            conn.sendall(b'OK\r\n' + PROMPT)
                        except Exception as e:
                            conn.sendall(b'NG ' + str(e).encode() + b'\r\n' + PROMPT)
                    else:
                        conn.sendall(b'OK\r\n' + PROMPT)
                else:
                    conn.sendall(b'OK\r\n' + PROMPT)

    def serve(self, host, port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        self.port = srv.getsockname()[1]
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=5001)
    ap.add_argument('--tftp-host', default='127.0.0.1')
    ap.add_argument('--tftp-port', type=int, default=0)
    ap.add_argument('--image-name', default='DM850I_0011.bcd')
    a = ap.parse_args()
    f = FakeDm850((a.tftp_host, a.tftp_port) if a.tftp_port else None, a.image_name)
    print(f'fake DM850 bootloader on {a.host}:{a.port}')
    f.serve(a.host, a.port)


if __name__ == '__main__':
    main()
