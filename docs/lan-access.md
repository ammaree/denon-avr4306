# LAN access to the AVR-4306

## What the LAN can and cannot reach

The LAN port terminates at the **DM850 network module** (ARM, ThreadX). The DM850 talks
to the MAIN M32C over UART0 + an SPI link (schematic-notes.md). Nothing on the LAN can
read MAIN or SUB internal flash:

- The MAIN **boot block** (0xFFC000–0xFFFFFF) and the rest of MAIN/SUB flash are internal
  to those chips. They are readable only over the M32C/M16C **serial-I/O programming
  mode** (UART1/CNVSS, with the 7-byte ID code) or **JTAG** — physical access. See
  re-plan.md 1b and schematic-notes.md.
- The DM850→MAIN link carries control commands and a MAIN→DM850 firmware *push*; there
  is **no memory read-back** path, and none of the 34 control commands
  (control-protocol.md) reads memory. So the boot block cannot come over the network.

What the LAN *does* expose is the DM850's own surface — a web/UPnP interface — and, if
the unit implements it, the **Denon control protocol over TCP** (the same ASCII commands
we recovered, carried over the network instead of the rear RS-232 jack).

## tools/lan_dump.py

Probes the unit over the LAN and records what is reachable. Read-only: it sends only
query commands, never a state change.

```bash
python3 tools/lan_dump.py --discover               # SSDP search, list candidates
python3 tools/lan_dump.py --ip <unit-ip>           # http surface + control queries
python3 tools/lan_dump.py --ip <unit-ip> --no-control   # web/UPnP only
python3 tools/lan_dump.py --ip <unit-ip> --control-port 23
```

It does three things, saving to `dumps/lan-<timestamp>/` (git-ignored):

1. **discovery** — SSDP M-SEARCH; prints each responder's address, SERVER string and
   device-description URL.
2. **http** — GETs the device description and common DM850 web paths.
3. **control** — opens the raw TCP control port (default 23) and sends the
   reverse-engineered tokens as queries (`PW?`, `MV?`, `SI?`, `MS?`, …), recording each
   reply. This **validates control-protocol.md against the live unit**: the token table
   should round-trip to real status strings (e.g. `PW?` → `PWON` / `PWSTANDBY`).

If the control port is refused, the unit of this generation may expose only the web
interface; the http dump then shows the device/firmware details and the discovery output
the model. The reverse-engineering itself does not depend on this — it is a cross-check
and a way to observe live protocol behaviour.
