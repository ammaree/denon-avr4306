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
