"""Model guard: confirm the target is an AVR-4306 DM850 before we touch it.

Checks: the MAC is a Denon OUI (00:05:CD), a DM850 shell answers on TCP 5001, and — when the
app is running — a `VI?` version string on telnet 23 looks like the AVR-4306 family. `VI?`
cannot report the DM850I stamp (it reads `I unknown`), so it is corroboration, not the key.
The sha256 pin on the image (acquire/patch) is the ultimate guard against a wrong write.
"""
from . import discovery, probe
from .resources import DENON_OUI

_OUI = DENON_OUI.lower().replace(":", "")


def check(ip, mac=None):
    """Return a report dict. `blocking` lists hard reasons to refuse; `warnings` are soft."""
    blocking, warnings = [], []
    if mac is None:
        for aip, amac in discovery.arp_table():
            if aip == ip:
                mac = amac
                break
    if mac is not None and not mac.replace(":", "").startswith(_OUI):
        blocking.append(f"MAC {mac} is not a Denon device (OUI 00:05:CD).")

    mode = probe.prompt_mode(ip)
    if mode is None:
        blocking.append(f"no DM850 shell answered on {ip}:5001 (is the receiver on and reachable?).")

    vi = probe.read_vi(ip) if mode == "app" else ""
    vi_ok = vi.startswith("VI") and "01:" in vi
    if mode == "app" and not vi_ok:
        warnings.append("could not read an AVR-4306 version string (VI?) on telnet 23.")
    if mac is None:
        warnings.append("could not read the device MAC from the ARP table to confirm the vendor.")

    return {
        "ip": ip,
        "mac": mac,
        "mode": mode,
        "vi": vi.strip(),
        "vi_ok": vi_ok,
        "blocking": blocking,
        "warnings": warnings,
        "ok": not blocking,
    }
