# Vendor updater — complete ports, protocols and options map

Status 2026-11-11. A systematic map of `AVR-4306_upgrade_6_0_0_4.exe` (and FWCV, the same
engine): every port, transport, command and option it uses to reach the unit. Synthesised
from the whole-exe Ghidra analysis (~2162 functions; the firmware-relevant surface is a few
dozen of them — the rest is CRT/MFC/Winsock/installer UI). Complements loader-interface.md §2
(the µcom frame detail) and docs/dm850-delivery.md (the DM850 path). The exe is in the Ghidra
project for any further query.

## Ports and transports

| Port | Transport | Role | Protocol |
|---|---|---|---|
| **23** | TCP (telnet) | "Check comm." | `VI?` version query |
| **5000** | TCP | MAIN/SUB/DSP/CPLD update | control lines (`VI?`, `RBUPDATE`→`RBSTART`, `RBNORM`) **and** AA-framed µcom loader frames on the same socket |
| **5001** | TCP | DM850 bootloader control | **text commands** (ASCII `send()` + reply), §below |
| **69** | UDP (TFTP) | DM850 image/bootloader **data** | updater is the **TFTP server**; the DM850 (tftp client) pulls the `.bcd` file; "octet" mode |
| COM1–8 | Serial, 9600–115200 | alternative to 5000 | same AA-framed µcom protocol over `WriteFile`/`ReadFile` |

## µcom loader (port 5000 / serial) — MAIN, SUB, DSP, CPLD

AA-framed, big-endian, checksum = low byte of the sum of preceding bytes. Targets: 1 MAIN,
2 SUB, 3 DSP, 0x0A DM850 (relay via MAIN), 0x0B CPLD. Frames (loader-interface.md §2.4):
`C` connect/info, `I` target info (model code), `L` begin load, `P` data (≤0x400 B), `S`
read range, `A`/`N` ack/nack. Entered by `RBUPDATE`→`RBSTART` (+15 s), exited by `RBNORM` /
power-cycle. This is the path the `loader_client.py` MAIN writer already uses.

## DM850 bootloader (port 5001 text + TFTP data)

The DM850 bootloader speaks **ASCII command strings** on TCP 5001 (`FUN_0041FBC0` → raw
`send()` `FUN_004203E0`, reply checked). The image bytes go over **TFTP** (UDP 69): the
updater serves the file, the DM850 fetches it by name.

Command vocabulary (0x41F1CF–0x42016F; UI labels in parentheses):

| Command | Effect |
|---|---|
| `start bootloader` | reboot into bootloader mode (Reboot(Bootloader Mode)...) |
| `start image` | reboot into the application (Reboot(Application Mode)...) |
| `start tftp client` | DM850 becomes a TFTP client and pulls the image |
| `update image` | flash DM850I (Updating(image)...) |
| `update image cne` | flash DM850I, cne variant (Updating(image + cne)...) |
| `erase image` | erase the DM850I region |
| `update bootloader` | flash DM850B — **forbidden** (safety rule 1) |
| `erase webpage` / `update webpage` | DM850W/D — **forbidden** (rule 2) |
| `STATE RESET;` / `STATE L_RESET;` / `RESETFLOW` / `Reboot Apl\|Bld\|update Mode` | bootloader state machine / reboot targets |

TFTP filenames: image `<model>_%04X.bcd`, bootloader `BL_<model>_%04X.bcd` (`%04X` = the
image/model code). So a DM850I write serves the patched image as `<model>_<code>.bcd`.

## Update flow (LAN)

1. **Check comm.** (`FUN_00405CB0`): 23 `VI?`; fallback 5000 `C`.
2. **Enter update mode:** 5000 `RBUPDATE`→`RBSTART`, 15 s wait.
3. **Stage 1** (resource 320, `FUN_00407C60`): µcom loop (`FUN_00408310`, 5000) writes
   MAIN/SUB/DSP; then the DM850 loop (`FUN_004090A0`, 5001+TFTP).
4. **Stage 2** (resource 321): the rest — including DM850W/DM850D web pages.
5. **Finish:** reboot to application (`start image` / `RBNORM`).

DM850 action byte (m column byte 2): **1 bootloader, 2 image, 3 image+cne, 4 webpage**;
DM850I = 2. The web-page erase/write fires only for DM850W/DM850D images present — see
dm850-delivery.md §1.

## Recovery

"Recovering DM800" (`FUN_004065B0`): reconnect to 5001 and re-run the write loop
(`FUN_004090A0`) — the bootloader survives a failed image write and re-flashes.
"Checking DM800" (`FUN_004060B0`): connect to 5001 with a 5 s wait and 3 retries; the
bootloader listens at boot/reset (dm850-delivery.md §4).

## Options and modes

- **Start mode:** no arg = **Factory mode** (title `<Factory Mode>`, dialog 102 shows all
  controls); `/NN` = **user mode** (reads `UpdateInformation_NN.txt`: `IPAddress`, `Skip`,
  `Drive`).
- **Container flags** (`MW/BP/PV` at 0x448B7C ff.): `MW:ON` = All/Select radio; `BP` =
  "Backup the setting of the product." (product-parameter backup before update, `Backup of
  product parameter`); `PV` = "Pass the update of the same version." Vendor containers:
  MW:ON, BP:OFF, PV:OFF.
- **Skip check:** per-image version-string equality (the '.'-stripped package version vs the
  `VI?` field); checked for MAIN/SUB/DSP and DM850B/DM850I only, and only while "Disable
  pass." is clear. User mode sets "Disable pass.", so it writes every image.
- **Transports:** LAN (above) or serial (COM1–8, 9600–115200 bps), same µcom protocol.
- **Errors surfaced:** `Update Fail! error code = %d`, `Erase failure`, `Communication port
  open error!`, `Device revision is not supported`.

## What this gives the DM850 delivery

A DM850I-only writer needs: (1) enter the DM850 bootloader (reset window or `start
bootloader`), (2) a **TFTP server** serving the patched `DM850I_ssdp.flash.bin` as
`<model>_<code>.bcd`, (3) the 5001 text commands to orchestrate (`update image` /
`start tftp client`, then `start image`), and (4) the recovery procedure (reconnect + retry).
It never sends `update bootloader`/`*webpage`. See dm850-delivery.md §5.
