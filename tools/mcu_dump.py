#!/usr/bin/env python3
"""Read-only M32C/M16C standard serial-I/O-mode flash reader (bench tool).

Purpose
-------
Dump the resident boot block (and the rest of flash) from a MAIN M32C/87 or SUB M16C/62P
over its standard serial I/O mode. This is the one artifact Phase 1 cannot get any other
way: the reset vector, fixed/special-page vectors, the 7-byte ID code and the C-startup
live in the boot block, which is absent from every firmware package (see
docs/phase1-status.md and docs/control-protocol.md). With a boot-block dump the byte-exact
rebuild (re-plan.md 1a) and a full boot-from-reset test in the emulator become possible.

This runs on a BENCH machine with a USB-serial (3.3 V TTL) adapter wired to the MCU's
serial-I/O pins, with the part held in serial-I/O (boot) mode. It does NOT run over the
LAN — the network path reaches only the DM850, never MAIN/SUB flash (docs/lan-access.md).

Safety
------
READ-ONLY by design. It sends only: auto-baud, version read (0xFB), ID-code verify
(0xF5), status read (0x70), and page read (0xFF). It never sends erase (0xA7/0xD0) or
program (0x41) — those are deliberately not implemented, so this tool cannot modify or
brick the part. Wrong wiring or voltage can still damage hardware: follow the service
manual (isolating transformer; 3.3 V levels; correct pin set from schematic-notes.md).

Wiring (from schematic-notes.md / research.md)
----------------------------------------------
- MAIN M32C/87: standard serial I/O mode 2 (async) on UART1 — P66/RXD1, P67/TXD1. Enter
  the mode with CNVSS high at reset release (via R602/J305/J306 or TP501). 3.3 V.
- SUB M16C/62P: mode 2 (async, UART1) with CE(P50)=H, EPM(P55)=L, CNVSS=H, CLK1(P65) low
  at reset release; pins P66/P67.
Confirm the exact pads against the board before connecting.

Protocol (Renesas standard serial I/O, async mode 2; see research.md)
---------------------------------------------------------------------
- 9600 8N1 auto-baud: send 0x00 until the device echoes/locks, then optional baud-rate
  select (0xB0..0xB4).
- 0xFB            -> version string ("VER.x.xx")
- 0xF5 addr(3) n id(7)  -> ID-code verify/unlock (n = 7). Commands that touch a programmed
                     part are refused until the ID matches. If flash is blank the ID is
                     all 0x00 or all 0xFF.
- 0x70            -> read status register (2 bytes); bit for "ID verified" must be set.
- 0xFF addr(3)    -> read one 256-byte page at addr (24-bit little-endian, page-aligned).

Usage
-----
  python3 tools/mcu_dump.py --port /dev/tty.usbserial-XXXX --probe
  python3 tools/mcu_dump.py --port COM5 --start 0xFFC000 --end 0xFFFFFF --id FF:FF:FF:FF:FF:FF:FF
  python3 tools/mcu_dump.py --port /dev/ttyUSB0 --start 0xF00000 --end 0xFFFFFF   # full MAIN

Needs pyserial (`pip install pyserial`). Output -> dumps/ (git-ignored) with a sha256.
"""
import argparse, sys, time, os, hashlib, datetime

try:
    import serial  # pyserial
except ImportError:
    serial = None

PAGE = 256


def le3(addr):
    return bytes([addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])


class SerialIO:
    def __init__(self, port, baud=9600, timeout=1.0):
        self.s = serial.Serial(port, baud, timeout=timeout,
                               bytesize=8, parity="N", stopbits=1)

    def autobaud(self):
        # Send 0x00 bytes; the boot firmware measures the start bit to lock baud.
        for _ in range(16):
            self.s.write(b"\x00"); time.sleep(0.02)
        self.s.reset_input_buffer()

    def version(self):
        self.s.write(b"\xFB")
        return self.s.read(8)

    def status(self):
        self.s.write(b"\x70")
        return self.s.read(2)

    def id_check(self, addr, idbytes):
        if len(idbytes) != 7:
            raise ValueError("ID must be 7 bytes")
        self.s.write(b"\xF5" + le3(addr) + bytes([7]) + bytes(idbytes))
        time.sleep(0.05)

    def read_page(self, addr):
        self.s.write(b"\xFF" + le3(addr))
        return self.s.read(PAGE)

    def close(self):
        self.s.close()


def parse_id(s):
    parts = [p for p in s.replace(":", " ").split() if p]
    return bytes(int(p, 16) for p in parts)


def outpath(start, end):
    d = os.path.join("dumps", "mcu-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "flash_%06X_%06X.bin" % (start, end))


def main():
    ap = argparse.ArgumentParser(description="read-only M32C/M16C serial-I/O flash reader")
    ap.add_argument("--port", required=True, help="serial device (/dev/tty.usbserial-*, COMx)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--probe", action="store_true", help="auto-baud + version read only")
    ap.add_argument("--start", type=lambda x: int(x, 0), default=0xFFC000,
                    help="first address (default 0xFFC000, the MAIN boot block)")
    ap.add_argument("--end", type=lambda x: int(x, 0), default=0xFFFFFF)
    ap.add_argument("--id", default="", help="7-byte ID code, e.g. FF:FF:FF:FF:FF:FF:FF")
    ap.add_argument("--id-addr", type=lambda x: int(x, 0), default=0xFFFFDF)
    args = ap.parse_args()

    if serial is None:
        sys.exit("pyserial not installed: pip install pyserial")

    io = SerialIO(args.port, args.baud)
    print("auto-baud ...")
    io.autobaud()
    ver = io.version()
    print("version: %r" % ver)
    if not ver:
        print("no response — check wiring, 3.3 V levels, serial-I/O mode entry, and that "
              "the part is held in boot mode at reset release.")
    if args.probe:
        io.close(); return

    if args.id:
        idb = parse_id(args.id)
        print("ID verify @ %06X with %s" % (args.id_addr, idb.hex()))
        io.id_check(args.id_addr, idb)
        print("status: %r" % io.status())

    start = args.start & ~(PAGE - 1)
    end = args.end
    out = outpath(start, end)
    print("reading %06X..%06X -> %s" % (start, end, out))
    h = hashlib.sha256()
    with open(out, "wb") as f:
        addr = start
        blank = 0
        while addr <= end:
            page = io.read_page(addr)
            if len(page) != PAGE:
                print("short/no read at %06X (%d bytes) — stopping. ID verified?"
                      % (addr, len(page)))
                break
            f.write(page); h.update(page)
            if page == b"\xFF" * PAGE:
                blank += 1
            if (addr & 0xFFF) == 0:
                print("  %06X" % addr)
            addr += PAGE
    print("sha256: %s" % h.hexdigest())
    print("blank (0xFF) pages: %d" % blank)
    io.close()


if __name__ == "__main__":
    main()
