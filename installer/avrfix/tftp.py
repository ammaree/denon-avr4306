"""TFTP write (WRQ) push, lifted verbatim from tools/dm850_writer.py.

The DM850 is the TFTP server on UDP 69; this is the client that WRITES the image to it.
`send(probe=True)` sends the WRQ, confirms the server ACKs block 0, then aborts with a TFTP
ERROR and writes NO data — used to prove the network path before anything is erased.
"""
import socket
import struct

TFTP_RRQ, TFTP_WRQ, TFTP_DATA, TFTP_ACK, TFTP_ERR = 1, 2, 3, 4, 5


class TftpPush:
    def __init__(self, server_ip, name, data, server_port=69, src_ip="0.0.0.0"):
        self.server = (server_ip, server_port)
        self.name = name
        self.data = data
        self.src_ip = src_ip

    def send(self, probe=False, on_block=None):
        """Push the image. on_block(done, total) is called per acked DATA block.
        Returns a dict: {ack0, tid, blocks_sent, complete, local_port, error}."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((self.src_ip, 0))
        s.settimeout(2.0)
        res = {"ack0": False, "tid": None, "blocks_sent": 0, "complete": False,
               "local_port": s.getsockname()[1], "error": None}
        try:
            wrq = struct.pack(">H", TFTP_WRQ) + self.name.encode() + b"\x00octet\x00"
            tid = self._handshake(s, wrq, res)
            if tid is None:
                return res
            res["ack0"] = True
            res["tid"] = tid
            if probe:
                s.sendto(struct.pack(">H", TFTP_ERR) + b"\x00\x00probe: no data\x00", tid)
                return res
            self._send_data(s, tid, res, on_block)
            res["complete"] = True
            return res
        except Exception as e:                       # noqa: BLE001 - report, don't crash mid-write
            res["error"] = repr(e)
            return res
        finally:
            s.close()

    def _handshake(self, s, wrq, res):
        for _ in range(6):
            s.sendto(wrq, self.server)
            try:
                pkt, addr = s.recvfrom(1024)
            except socket.timeout:
                continue
            op = struct.unpack_from(">H", pkt, 0)[0]
            if op == TFTP_ERR:
                res["error"] = "server TFTP ERROR: " + pkt[4:].split(b"\x00", 1)[0].decode("latin1")
                return None
            if op == TFTP_ACK and struct.unpack_from(">H", pkt, 2)[0] == 0:
                return addr
        return None

    def _send_data(self, s, tid, res, on_block):
        total = (len(self.data) + 511) // 512 + (1 if len(self.data) % 512 == 0 else 0)
        blk = 1
        for off in range(0, len(self.data) + 1, 512):
            chunk = self.data[off:off + 512]
            pkt = struct.pack(">HH", TFTP_DATA, blk & 0xFFFF) + chunk
            for _attempt in range(20):
                s.sendto(pkt, tid)
                try:
                    ack, a = s.recvfrom(64)
                except socket.timeout:
                    continue
                if (a == tid and ack[:2] == struct.pack(">H", TFTP_ACK)
                        and struct.unpack_from(">H", ack, 2)[0] == (blk & 0xFFFF)):
                    break
            else:
                raise TimeoutError(f"no ACK for data block {blk}")
            res["blocks_sent"] = blk
            if on_block:
                on_block(blk, total)
            blk += 1
            if len(chunk) < 512:
                break
