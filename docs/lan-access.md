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

## Observed on the real unit (2026-11-05)

Probed at the user's report that "the LAN is not connecting". The unit is at
**192.168.1.13**, MAC **00:05:CD:13:81:94** (D&M Holdings / Denon — confirms the OUI).

- It was reachable: ping 0% loss, ARP resolved, and open TCP ports **80, 5000, 6666,
  8080**. Port 80 served a **GoAhead-Webs** HTML frameset titled `INDEX` (the DM850
  config/control UI). 8080 answered HTTP (404 at root). 5000 and 6666 are raw services
  (accept TCP, no banner, wait for a specific protocol). No SSDP/UPnP advert, no TFTP.
- After a modest amount of probing the module went **fully unreachable** — no ICMP, no
  TCP on any port. The DM850 hangs under load and takes the whole network stack down.

So "LAN not connecting" is the **DM850 network module crashing/hanging**, not a wiring
or DHCP problem — it gets an address and serves briefly, then drops off. A full AC
power-cycle recovers it. Capture the web UI gently (one request at a time, `--delay`),
once, right after a power-cycle; do not port-scan or crawl it fast.

## Web UI captured (after power-cycle, gentle pass)

A single serial pass with a 2 s delay captured the whole DM850 web control UI with no
crash — so careful access is stable; the earlier hang was the aggressive scan/crawl. The
server is GoAhead-Webs; the UI is a frameset (`/` → `reqTopMenu.asp` which JS-redirects
to `TopMenu.asp`). Pages (saved under dumps/, git-ignored):

`TopMenu.asp` `sendTopMenu.asp` `mainzone.htm` `reqMainZone_1/2.asp` `reqChannelVol.asp`
`ChannelVol.asp` `reqSurrPara.asp` `reqTuner.asp` `reqNetAudio.asp` `reqiPod.asp`
`multizone.htm` `systemsetup.htm` `reqPanelLock.asp` `PanelLock.asp` `S-7_9.asp`.

It is a **control front-end, not a memory interface**, and it maps 1:1 onto the recovered
serial command set (control-protocol.md) — cross-validation of the RE:

| web control | form field | serial command |
|---|---|---|
| Power ON/STANDBY | `radioSystemPower` = ON/STANDBY | PW |
| channel volumes | `VolumebarFl/Fr/C/Sw/Sl/Sr/Sb/Sbl/Sbr` | CV |
| surround parameters | reqSurrPara form | PS |
| tuner | reqTuner form | TF / TP / TM |
| net audio / iPod | reqNetAudio / reqiPod | NS |
| panel lock | PanelLock form | SY |

The channel set (FL/FR/C/SW/SL/SR/SB/SBL/SBR) confirms the AVR-4306 7.1+SB layout. No
model/firmware/version string appeared in the control pages. The web POSTs go to the
`.asp` pages, which the DM850 turns into control commands to MAIN over UART0 — the same
protocol decoded in control-protocol.md.

## Loader-client checks (2026-11-05 20:05, tools/loader_client.py)

Normal mode only; the same first steps the vendor updater takes.

| Step | Result |
|---|---|
| ping ×3 | 0 % loss; ARP 00:05:CD:13:81:94 |
| `version`: telnet TCP 23, `VI?` | **connection refused** |
| `check`: TCP 5000, `C` frame `aa 43 01 ee` | connect accepted; **no reply in 6 s** |
| ping ×2 afterwards | 0 % loss — DM850 still up |

TCP 23 is the documented control port (protocol spec 4.6a, p. 2: "TCP port 23
(telnet)", no enable setting; the only network option is Standby Mode Power Saving).
It has been closed in every observation of this unit (first scan: only 80, 5000, 6666,
8080 open). The vendor updater connects to 23 *before* it uses 5000, so the silent 5000
may follow from the same cause.

Candidate causes, not yet distinguished:
1. The receiver was in standby (vendor manual requires power on, green indicator).
2. Another client holds the single telnet session (home-automation or app), so new
   connections are refused.
3. The DM850's telnet service is down while its web server still runs (the module has
   already been seen to hang partially; docs above).
4. Port 5000 bridges to MAIN only in a state the telnet step sets up.

Next checks need the user at the unit: power state, other controllers on the LAN, then
one retry after a full AC power-cycle, then the rear RS-232 port (9600 8N1, same
`VI?`) to separate a DM850 fault from a MAIN fault.

### Retry 2026-11-05 21:35

The user found a home-automation device controlling the unit and switched it off at
21:25. Retry 10 min later, receiver not power-cycled:

| Step | Result |
|---|---|
| ping ×2 | 0 % loss |
| `version`: telnet TCP 23, `VI?` | **connection refused** (unchanged) |
| `check`: TCP 5000, `C` frame | connect accepted; **no reply in 6 s** (unchanged) |
| ping ×2 afterwards | 0 % loss |

Switching the controller off does not close its TCP session: it sends no FIN, so the
DM850 may still hold the session as open until a keep-alive timeout, if it has one.
Cause 2 is therefore not ruled out. Next: AC power-cycle the receiver with the
controller still off, wait 1 min after power-on, retry once.

### After AC power-cycle, controller off (2026-11-05 21:38)

| Step | Result |
|---|---|
| ping ×2 | 0 % loss |
| `version`: telnet TCP 23, `VI?` | **connected; reply in 13 ms** |
| `check`: TCP 5000, `C` frame `aa 43 01 ee` | connect accepted; **no reply in 6 s** |
| ping ×2 afterwards | 0 % loss |

Port 23 was blocked by the home-automation controller's session (cause 2). Keep that
controller off whenever tools talk to the unit; it also fits rule 7 of safety-plan.md.

`VI?` reply (raw):
`VI01:0100;02:0050;03:0004;0A:B200510231011\0×7,I200805270745\0×7;\r`

| Target | Reported | Vendor package |
|---|---|---|
| 01 MAIN | 01.00 | 6.0.0.4 (only package with 01.00) |
| 02 SUB | 00.50 | all packages |
| 03 DSP | 00.04 | all packages |
| 0A DM850 bootloader | B200510231011 | not in any package (factory) |
| 0A DM850 image | I200805270745 | 6.0.0.3 / 6.0.0.4 |

The unit runs the latest vendor firmware (6.0.0.4). The DM850 fields are 13-char stamps
padded with NULs to 20; the reply carries no DM850W/DM850D stamp.

Port 5000 still gives no `C` reply with telnet working. This is expected: the vendor
tool sends `C` only after `RBUPDATE`, or as a fallback when `VI?` fails
(loader-interface.md §2.1, settled offline the same evening). A normal-mode unit is
checked with `VI?`.

### `VI?` on TCP 5000 (2026-11-05 21:49)

| Step | Result |
|---|---|
| ping ×2 | 0 % loss |
| `version --control-port 5000`: `VI?` | **reply in 13 ms**, identical to the port 23 reply |
| ping ×2 afterwards | 0 % loss |

The DM850 passes control lines on 5000 through to MAIN in normal mode, as the vendor
update flow requires. The first step of `loader_client.py read` works on this unit.
