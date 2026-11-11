"""Find the AVR-4306 on the LAN by its Denon OUI (00:05:CD), the way the vendor updater does.

Reads the OS ARP table (per-OS parse). If nothing is there yet, does a bounded, concurrent
TCP sweep of the local /24 to populate ARP, then re-reads it. Always falls back to manual IP.
"""
import concurrent.futures
import ipaddress
import re
import socket
import subprocess

from .resources import DENON_OUI

_OUI = DENON_OUI.lower().replace(":", "")


def _norm_mac(mac):
    parts = re.split(r"[:-]", mac.strip())
    if len(parts) != 6:
        return None
    try:
        return ":".join(f"{int(p, 16):02x}" for p in parts)
    except ValueError:
        return None


def local_ipv4s():
    """Local IPv4 addresses (for source-NIC selection and subnet sweep)."""
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    # The address used to reach a public host — the primary egress interface.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [a for a in addrs if not a.startswith("127.")]


def arp_table():
    """[(ip, normalized_mac)] from the OS ARP table."""
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        ipm = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
        macm = re.search(r"([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})", line)
        if ipm and macm:
            mac = _norm_mac(macm.group(1))
            if mac:
                rows.append((ipm.group(1), mac))
    return rows


def _denon_hits(rows):
    seen = {}
    for ip, mac in rows:
        if mac.replace(":", "").startswith(_OUI):
            seen[ip] = {"ip": ip, "mac": mac}
    return list(seen.values())


def _sweep(subnet, ports=(80, 23), timeout=0.3, workers=128):
    def poke(ip):
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                s.connect((str(ip), p))
                s.close()
                return
            except OSError:
                pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(poke, subnet))


def find_denon(active=True):
    """Return [{ip, mac}] for Denon-OUI devices. If none and active, sweep the local /24(s)
    to populate ARP, then re-read. The caller still offers manual-IP entry regardless."""
    hits = _denon_hits(arp_table())
    if hits or not active:
        return hits
    for addr in local_ipv4s():
        try:
            net = ipaddress.ip_network(addr + "/24", strict=False)
        except ValueError:
            continue
        _sweep(list(net.hosts()))
    return _denon_hits(arp_table())


def source_ip_for(target):
    """The local source IP the OS would use to reach `target` — bind the TFTP push to it so a
    multi-NIC host sends from the interface on the unit's subnet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target, 69))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "0.0.0.0"
