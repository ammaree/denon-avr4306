"""A cohesive fake DM850 in bootloader mode, modelling the real update flow for the flasher
FSM test: a `#` shell on TCP that erases/arms on `update image`, a TFTP server that receives the
WRQ push, and the post-transfer `ok` the shell sends once the image is in. Never touches a unit.
"""
import socket
import struct
import threading

FORBIDDEN = {b"update bootloader", b"erase webpage", b"update webpage", b"erase bootloader"}


class FakeBootUnit:
    def __init__(self, host="127.0.0.1"):
        self.host = host
        self.received = None
        self.commands = []
        self.refused = []
        self.started_image = False
        self._got = threading.Event()

        self._shell = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._shell.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._shell.bind((host, 0))
        self._shell.listen(1)
        self.shell_port = self._shell.getsockname()[1]

        self._tftp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._tftp.bind((host, 0))
        self.tftp_port = self._tftp.getsockname()[1]

    def start(self):
        threading.Thread(target=self._serve_shell, daemon=True).start()
        threading.Thread(target=self._serve_tftp, daemon=True).start()
        return self

    def _serve_shell(self):
        while True:
            try:
                conn, _ = self._shell.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        conn.sendall(b"#")
        buf = b""
        while True:
            try:
                chunk = conn.recv(256)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.strip(b"\r \t")
                if not cmd:
                    continue
                self.commands.append(cmd)
                if cmd in FORBIDDEN:
                    self.refused.append(cmd)
                    conn.sendall(b"NG\r\n#")
                elif cmd == b"erase image":
                    conn.sendall(b"\r\nerase image\r\nok\r\n#")
                elif cmd == b"update image":
                    conn.sendall(b"erase firmware image\r\nstart tftp client\r\n")
                    if self._got.wait(timeout=20):      # block until the TFTP push finishes
                        conn.sendall(b"ok\r\n#")
                elif cmd == b"start image":
                    self.started_image = True            # reboot: no reply
                elif cmd == b"start bootloader":
                    pass                                  # reboot: no reply
                else:
                    conn.sendall(b"ok\r\n#")

    def _serve_tftp(self):
        self._tftp.settimeout(15)
        try:
            pkt, client = self._tftp.recvfrom(2048)
        except socket.timeout:
            return
        if struct.unpack_from(">H", pkt, 0)[0] != 2:     # WRQ
            return
        tid = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tid.bind((self.host, 0))
        tid.settimeout(15)
        tid.sendto(struct.pack(">HH", 4, 0), client)     # ACK block 0
        data = bytearray()
        expected = 1
        while True:
            try:
                p, a = tid.recvfrom(2048)
            except socket.timeout:
                break
            op = struct.unpack_from(">H", p, 0)[0]
            if op == 5:                                   # ERROR (probe abort)
                break
            if op != 3:                                   # DATA
                continue
            blk = struct.unpack_from(">H", p, 2)[0]
            tid.sendto(struct.pack(">HH", 4, blk), a)
            if blk == expected:
                chunk = p[4:]
                data += chunk
                expected += 1
                if len(chunk) < 512:
                    self.received = bytes(data)
                    self._got.set()
                    break
        tid.close()
