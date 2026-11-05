#!/usr/bin/env python3
"""AVR-4306 LAN probe and control-protocol dump.

Scope and honesty
------------------
The MAIN M32C boot block (0xFFC000-0xFFFFFF) is internal flash. It is reachable only
over the M32C serial-I/O programming mode (UART1/CNVSS) or JTAG -- physical access, NOT
the LAN. The LAN reaches the DM850 network module and, through it, only what the DM850
exposes: a web/UPnP surface and, if present, the Denon control protocol. None of the 34
control commands is a memory read, and the DM850 link is MAIN->DM850 push, so the boot
block cannot be fetched over the network. This tool therefore does not claim to dump
firmware. It dumps what the LAN actually exposes:

  * discovery  -- UPnP/SSDP search for the unit and its device-description URL
  * http       -- GET the DM850 web surface (root, device description, common pages)
  * control    -- open the Denon control port and send the reverse-engineered commands
                  READ-ONLY (query forms only), recording each token's live response

The control pass validates docs/control-protocol.md against the real device: the token
table we recovered (PW, MV, SI, ...) should round-trip to real status replies.

Safety
------
Read-only by default: only query commands are sent, never a state change (no power,
volume, input switch). State-changing use is intentionally not implemented here. Point
it only at your own unit on your own LAN.

Observed on the real unit (2026-11-05)
--------------------------------------
192.168.1.13 (MAC 00:05:CD:13:81:94, D&M Holdings) answered ping and served a
GoAhead-Webs frameset on :80 with open TCP :80/:5000/:6666/:8080 — then went fully
unreachable (no ICMP, no TCP) after a modest amount of probing. The DM850 network
module hangs under load and drops the whole stack; a full AC power-cycle brings it back.
This is why the HTTP pass is serial and slow and there is no port scan here: hammering
the module wedges it. Run this once, gently, right after a power-cycle.

Usage
-----
  python3 tools/lan_dump.py --discover
  python3 tools/lan_dump.py --ip 192.168.1.50            # http + control
  python3 tools/lan_dump.py --ip 192.168.1.50 --control-port 23
  python3 tools/lan_dump.py --ip 192.168.1.50 --no-control   # http only

Output lands in dumps/lan-<timestamp>/ (git-ignored). Stdlib only.
"""
import argparse, socket, sys, os, time, datetime, urllib.request, urllib.error

SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900

# Read-only query commands, built from the recovered token table (control-protocol.md).
# Denon convention: "<TOK>?\r" asks for current state; the unit replies CR-terminated.
QUERY_TOKENS = ["PW", "MV", "CV", "MU", "SI", "ZM", "SR", "SV", "SD", "MS", "PS",
                "TF", "TP", "TM", "Z2", "Z3", "SY", "SS", "NS", "VS", "HD"]
# A few longer status queries some Denon units answer (harmless if ignored).
QUERY_EXTRA = ["SSINFAISSET?", "SSINFFRM?", "MNZST?"]

CR = b"\r"


def outdir():
    d = os.path.join("dumps", "lan-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


def ssdp_discover(timeout=4.0):
    """Send an SSDP M-SEARCH and collect responders (addr, LOCATION, SERVER)."""
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: %s:%d\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 2\r\n"
           "ST: ssdp:all\r\n\r\n" % (SSDP_ADDR, SSDP_PORT)).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(timeout)
    found = {}
    try:
        s.sendto(msg, (SSDP_ADDR, SSDP_PORT))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(65535)
            except socket.timeout:
                break
            hdrs = {}
            for line in data.decode("latin-1").split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    hdrs[k.strip().upper()] = v.strip()
            found.setdefault(addr[0], (hdrs.get("LOCATION", ""), hdrs.get("SERVER", "")))
    finally:
        s.close()
    return found


def http_get(url, timeout=5.0):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() if hasattr(e, "read") else b""
        except Exception as e:
            if attempt == 2:
                return None, str(e).encode()
            time.sleep(1.5 * (attempt + 1))   # back off; the DM850 web server is fragile
    return None, b""


def http_dump(ip, od, location="", delay=1.5):
    """Fetch the device-description and a few common DM850 web paths.

    The DM850 runs a tiny GoAhead-Webs server that serves ~one connection at a time
    and wedges (and can take the whole network stack down with it) under rapid or
    concurrent requests. So this is deliberately serial and slow: one request, a pause,
    retries with back-off. Do not parallelise it or add a port scan against this unit.
    """
    paths = ["/", "/description.xml", "/device.xml", "/ServerDesc.xml",
             "/index.html", "/index.htm", "/web/index.html", "/setup.html"]
    urls = []
    if location:
        urls.append(location)
    urls += ["http://%s%s" % (ip, p) for p in paths]
    log = []
    for u in urls:
        status, body = http_get(u)
        name = u.replace("://", "_").replace("/", "_").replace(":", "_")
        if status and body:
            with open(os.path.join(od, "http_" + name), "wb") as f:
                f.write(body)
        log.append("%-55s -> %s (%s bytes)" % (u, status, len(body) if body else 0))
        time.sleep(delay)                     # give the embedded server room to recover
    with open(os.path.join(od, "http_index.txt"), "w") as f:
        f.write("\n".join(log) + "\n")
    print("  http: tried %d URLs; see %s/http_index.txt" % (len(urls), od))
    return log


def control_probe(ip, port, od, read_timeout=1.2):
    """Open the raw TCP control port; send read-only queries; record replies."""
    try:
        sk = socket.create_connection((ip, port), timeout=4.0)
    except Exception as e:
        print("  control: port %d not reachable (%s)" % (port, e))
        return None
    sk.settimeout(read_timeout)
    results = []

    def ask(cmd):
        try:
            sk.sendall(cmd.encode() + CR)
        except Exception as e:
            return "<send error: %s>" % e
        time.sleep(0.15)
        buf = b""
        try:
            while True:
                chunk = sk.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        return buf.decode("latin-1").replace("\r", "\\r").strip() or "<no reply>"

    try:
        for t in QUERY_TOKENS:
            r = ask(t + "?")
            results.append((t + "?", r))
            print("    %-6s -> %s" % (t + "?", r))
        for q in QUERY_EXTRA:
            results.append((q, ask(q)))
    finally:
        sk.close()
    with open(os.path.join(od, "control_port%d.txt" % port), "w") as f:
        for c, r in results:
            f.write("%-14s %s\n" % (c, r))
    return results


def main():
    ap = argparse.ArgumentParser(description="AVR-4306 LAN probe / control dump")
    ap.add_argument("--ip", help="unit IP address (skip to only discover)")
    ap.add_argument("--discover", action="store_true", help="SSDP discovery and exit")
    ap.add_argument("--no-control", action="store_true", help="skip the control-port pass")
    ap.add_argument("--control-port", type=int, default=23,
                    help="raw Denon control TCP port (default 23)")
    ap.add_argument("--discover-timeout", type=float, default=4.0)
    ap.add_argument("--delay", type=float, default=1.5,
                    help="seconds between HTTP requests (the DM850 server is fragile)")
    args = ap.parse_args()

    print("# SSDP discovery")
    found = ssdp_discover(args.discover_timeout)
    for addr, (loc, srv) in sorted(found.items()):
        print("  %-15s  %s  %s" % (addr, srv, loc))
    if not found:
        print("  (no SSDP responders)")
    if args.discover and not args.ip:
        return

    ip = args.ip
    if not ip:
        print("No --ip given; pass the unit's address to dump it. "
              "Discovery above lists candidates.")
        return

    od = outdir()
    print("# dumping %s -> %s" % (ip, od))
    location = found.get(ip, ("", ""))[0]
    http_dump(ip, od, location, delay=args.delay)
    if not args.no_control:
        print("# control-protocol queries (read-only)")
        control_probe(ip, args.control_port, od)
    print("done: %s" % od)


if __name__ == "__main__":
    main()
