# Update tools: FWCV recovery package and the 6.0.0.x updater

Sources: `RECOVERY Firmware Network AVR-4306.zip` (InstallShield 5/6 package
`FWCV_4306_VR002_SETUP`, 2006-06-15, unpacked with `unshield`) and the string tables of
both Windows tools. No code of the tools has been disassembled yet; everything below is
from embedded strings and the package headers.

## 1. FWCV_4306_4320_VR002 ("DENON Flash ROM Writer 3 Ver.D010 <TEST>")

Files in `data1.cab`: `FWCV_4306_4320_VR002.exe` (311,296 B, PE, 2006-06-15) and
`FWCV_4306_4320_VR002.bin` (3,125,792 B). The tool banner says it is for
**4306/4320/2807/2920** — the AVR-2807/AVC-2920 share the platform — and has a
"<Factory Mode>" variant string.

### 1.1 The .bin

Same `AVTOOL3 B007` container as the updaters (see firmware-package.md §2), two images:

| Image | Version | Flash range | Size | Notes |
|---|---|---|---|---|
| MAIN | 00.76 | 0xF00000–0xFFBFFF | 1,032,192 | M32C code (signature counts identical in kind to 00.99/01.00); code to 0xFBFFF, i.e. **no erased tail** — older, larger build |
| DM850 | "11.22" | 0x000000–0x1FEFFF | 2,093,056 | `bCoD` image, build stamp **2005-11-22 11:02:20**, name `EmbededDMP_Denon_Release` |

**Payloads are stored plain**, not XOR 0xFF: the header checksum equals the 32-bit
byte sum of the raw data, the MAIN image starts with readable M32C code and the DM850
image with `bCoD` in clear. The 6.0.0.x updaters (two months later) store every payload
inverted with the checksum over the inverted bytes, under an identical header format and
identical `MW:ON / BP:OFF / PV:OFF` flags. The inversion is therefore a property of the
tool generation, not signalled in the header.

The DM850 "11.22" label is not a version: the FWCV image is a 2005-11-22 build, the
updater's DM850IMG "11.22" is a 2006-02-07 build of different size. Both are older than
the DM850I images the updaters actually install (2006-08, 2008-05).

### 1.2 What the tool can do (from strings)

Target protocol (MAIN/SUB/DSP side, "Microcomputer side" in error texts):

- Command letters with ACK/NACK: `SendPCmd():P`, `SendLCmd():L`, `SendSCmd():S`,
  `ReceiveCmd():C/P/D`, `SendNackCmd()`; debug format `M[%02X][%02X][%08X][%08X]`
  (two bytes + two 32-bit words — likely target id, command, address, length).
- Steps: "Connection with target", "Request information of target"
  (`ID:TargetName Version`, `[ID:%02d] %s`), "Switch of target" (`ID:%02d->`), "Setting
  of baud rate" (9600–115200 bps table), "Reboot(Bootloader Mode)", "Reboot(Update
  Mode)", "Reboot(Application Mode)", "Erasing", "Updating", "Verify check of update",
  "Pass update. (The same version.)".
- Error codes from the target: E0 connection, E1 communication mode switchover, E2/E3
  timeout/retry, E8/EB flash erase, E9/EA timeout/retry during data writing, EC flash
  write, ED ROM data write, EE backup-data write.
- **Parameter backup/restore**: "Backup of product parameter", "Receive of backup
  data", "Send of backup data", "Writing of product parameter", files
  `%s_%04X.bcd` / `BL_%s_%04X.bcd` and `parameter`. `original_AVR-4306.bid` in the
  Denon folder is such a backup: header `4306EU0099` (model, EU, MAIN 00.99) followed by
  the unit's settings (input names, tuner presets, and an XML fragment that looks like
  DM850 state). Treat it as personal data; it is not firmware.
- **CPLD programming**: `CUpdateCpld`, `CPLDL`, `CPLDA`, `-aPROGRAM`, "initialize JTAG
  chain to known state", "drscan/irscan", and a complete Lattice ispVM **VME player**
  (`// VENDOR LATTICE/ALTERA/XILINX`, `SHIFTDR`, `RUNTEST`, `ENDIR`, `LCOUNT`, …) with
  the ispVM exit-code texts ("Device verify failure", "Erase failure", "Reading IDCODE
  failure", …). So the CPLDs (EPM570 ×2, LC4064V) are field-programmable through the
  unit: the tool streams a VME file and a µcom bit-bangs the CX152 JTAG chain
  (`SUBCPUJTAGON` net on the SUB). No CPLD image is in any package on hand.
- **DM850 side** — plain text commands to the module's loader: `start image`,
  `start bootloader`, `start tftp client`, `update bootloader`, `update image`,
  `update image cne`, `erase image`, `update webpage`, `erase webpage`, with the
  matching status texts "Updating(bootloader)...", "Updating(image + cne)...". The
  complete **TFTP** error-string set ("Illegal TFTP operation", "Unknown transfer ID",
  `octet`) shows the PC runs a TFTP server and the DM850 pulls the image with its TFTP
  client. Image types `DM850I` (image), `DM850B` (bootloader), `DM850D`, plus "cne"
  (a config/network entity blob, cf. `getCneConfigNumber` in the ARM firmware).
- Unit discovery: the updater searches the LAN for the receiver by MAC prefix; it
  carries a list of Denon OUIs (`00:05:CD:...`) and "Searching IP = %d.%d.%d.%d".
- "Checking DM800 ...", "Recovering DM800 ..." — DM800 is the tool's generic name for
  the network module; "The VIDEO version is different" — a version check on the video
  (FLI2310/PLD?) part before update.

### 1.3 Transport

Both tools import `WS2_32` (TCP/UDP) and also use `SetCommTimeouts`/COM-port strings and
a baud-rate table, so the same engine serves a serial (RS-232 / factory jig) path and
the Ethernet path. On the AVR-4306 the Ethernet path reaches MAIN through the DM850's
UART/SPI link (schematic-notes.md §"Update route"); the baud-rate step applies to that
UART.

## 2. The 6.0.0.x updater

Same engine ("DenonWriter" work directory, same string tables, same VME player, same
DM850 commands) with a wizard UI: "DENON Upgrade Tool %s for AVR-4306", the network
set-up instructions, "%d/2 stage" progress, "Update Complete !" / "Update Fail! error
code = %d". Differences from FWCV: payloads inverted; three AVTOOL3 packages (resources
320/321/351) instead of one file; recovery of the DM850 ("Recovering DM800") from
resource 351 when the module does not answer.

## 3. Security observations (for Phase 2g)

- DM850 loader accepts plain-text `update ...` / `erase ...` commands and fetches
  images by TFTP from any host on the LAN; no authentication string anywhere.
- The µcom update protocol has ACK/NACK and checksums only; no signature. Whoever can
  reach the DM850's control port can rewrite MAIN, SUB, DSP and the CPLDs.
- Unit discovery by Denon OUI makes targets easy to find on a LAN.

## 3a. SSManage4306.EXE (2005-10-21)

Settings backup/restore tool, not a firmware writer. Strings: "Backup Image Data
(*.BID)", "Save the bakup image", "Load the backup image", "Reboot(Save mode)",
"Reboot(Load mode)", model table `AVR-4306ASA / AVR-4306EUR / AVR-4306USA /
AVC-4320JPN`, header parse `%4s%2s%4s` (model, region, version). It talks to the unit
over one TCP connection (socket/htons/connect/send/recv only). `original_AVR-4306.bid`
(`4306EU0099`) is a file this tool produced from an EU unit running MAIN 00.99.

**Save flow, decompiled 2026-11-05 (Ghidra; `FUN_004018F0`).** All on TCP 5000:

1. "Reboot(Save mode)" (`FUN_00401D90`): `VI?\r`, `SYMO\r` (model/region), check them,
   then `RBUPDATE\r` → `RBSTART`, wait 5 s, close.
2. Reconnect, `C(1)` with a 5 s timeout (`FUN_00403670`).
3. Target information (`FUN_00403770(1, …)`); model name compared with the file type.
4. "Saving" (`FUN_004032F0`): `S` = `AA 'S' 01 01 00000400 00002701 ck` (sub-byte 1),
   data frames with ACK/NACK; the file is `%4s%2s%4s` (model, region, version) + RAM
   0x040C–0x2701 (8,950 B).
5. "Reboot(Normal mode)" (`FUN_00401F40`): reconnect, wait 5 s, `X` frame
   `AA 'X' 01 02 01 ck`, wait 5 s, `RBNORM\r` → `RBSTART`, wait 5 s, close.

So the vendor's own settings backup is an update-mode session: there is no normal-mode
path to the settings. `tools/loader_client.py read` does steps 1–4 without `SYMO`
(with the updater's 15 s wait and SSManage's sub-byte 1), and exits by power cycle
instead of step 5. On the unit the sub-1 read returns all RAM 0x0400–0xC3FF; the range
in the frame is ignored (lan-access.md, 2026-11-05).

## 4. Open items

1. Disassemble the FWCV tool (x86, MFC) to recover the exact framing of `P/L/S/C/D`
   commands, the TCP port(s) used, and the DM850 command port — needed before any
   PC-side re-implementation and for the security audit.
2. Capture a real update session on the wire (passive tap) to confirm.
3. Check whether `update image cne` / `.bcd` parameter files are needed for a full
   recovery of a dead network module.
