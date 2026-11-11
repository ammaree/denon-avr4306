"""The DM850 bootloader's TCP-5001 line shell, lifted verbatim from tools/dm850_writer.py.

The command whitelist IS the DM850I-only safety guarantee: `update bootloader`,
`erase webpage`, `update webpage` are absent by construction, and send_cmd refuses anything
not in CMD_ALLOW, so no code path can transmit a forbidden command.
"""
import socket
import time

from .errors import NotReachable

# Only these may ever be sent on 5001. `erase image` clears only the DM850I region
# (recoverable); the DM850B bootloader is never addressed.
CMD_ALLOW = {"start bootloader", "start image", "start tftp client", "update image",
             "erase image"}
REBOOT_CMDS = {"start bootloader", "start image"}   # drop the socket; no `ok`/prompt returns


class Shell:
    def __init__(self, ip, port=5001, timeout=10):
        self.s = socket.create_connection((ip, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.prompt = self._read_prompt()

    def _read_prompt(self):
        buf = b""
        while not buf.rstrip().endswith((b">", b"#")):
            try:
                c = self.s.recv(256)
            except socket.timeout:
                break
            if not c:
                break
            buf += c
        return buf

    def mode(self):
        """'boot' if the prompt is `#`, 'app' if `>`, else 'unknown' (fact from the prompt)."""
        p = self.prompt.rstrip()
        if p.endswith(b"#"):
            return "boot"
        if p.endswith(b">"):
            return "app"
        return "unknown"

    def send_cmd(self, cmd, expect=b"ok", timeout=40):
        if cmd not in CMD_ALLOW:
            raise PermissionError(f"refused: {cmd!r} is not in the command whitelist")
        self.s.sendall(cmd.encode() + b"\r\n")
        if cmd in REBOOT_CMDS:                        # reboots; no reply to wait for
            try:
                return self.s.recv(256)
            except OSError:
                return b""
        return self._read_until(expect, timeout)

    def _read_until(self, expect, timeout):
        self.s.settimeout(timeout)
        buf = b""
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


def connect_retry(ip, port=5001, total=70):
    """Reconnect to the 5001 shell, retrying while the module reboots."""
    end = time.time() + total
    while time.time() < end:
        try:
            return Shell(ip, port)
        except OSError:
            time.sleep(1)
    raise NotReachable(f"could not reach {ip}:{port} within {total}s")
