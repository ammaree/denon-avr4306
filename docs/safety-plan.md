# Brick-safe firmware development plan (DM850 + MAIN)

Status: approved 2026-11-05. Governs every action that writes to the unit.

## Constraints

One unit, ~20 years old, in South Africa, no local service, no donor, no spare chips. The
unit is **not opened** except as an absolute last resort. The network fix is firmware
only. Therefore every write goes through the vendor update path (PC → LAN → DM850 →
MAIN, or RS-232 → MAIN resident loader if that path exists).

The safety net per processor is the vendor resident loader that updates never rewrite:
MAIN user blocks 0–2 (0xFFC000–0xFFFFFF) and the DM850 bootloader (DM850B).

"Brick" = not recoverable without opening the unit. A fault the vendor tools can fix is
not a brick.

## Facts this rests on

M32C/87 hardware manual REJ09B0180 Rev 1.50:

- The Renesas serial-I/O program is in a separate 4 KB factory boot ROM that CPU
  rewrite and serial mode cannot erase (§26.1). It always survives, but entering it
  needs CNVSS high, i.e. opening the unit.
- ID-code mismatch: commands refused; no lockout, no auto-erase (§26.2.2). ROMCP blocks
  parallel mode only. Application code can read all user flash, blocks 0–2 included.
- Top 16 KB = block 2 (8 KB, 0xFFC000–0xFFDFFF), block 1 (4 KB, 0xFFE000–0xFFEFFF),
  block 0 (4 KB, 0xFFF000–0xFFFFFF) (Fig. 26.1). Package writes cover blocks 3–20.
- Endurance 100 program/erase cycles, all areas including data-flash block A
  (Table 27.10). Data retention specified at 10 years minimum; blocks 0–2 are ~20 years
  old and have never been refreshed.
- M32C/87 has no Renesas "user boot" mode: the resident loader is Denon's own code.
  Whether it recovers a broken application is unknown until blocks 0–2 are read.

Field reports (AVForums, AVR-4306): an update timed out while programming the DM
module and was fixed with a direct crossover cable and static IPs; units have been lost
to power cuts mid-update; a Denon RS-232 recovery tool exists.

## Hard rules

1. Never write SUB, DSP, CPLDs, MAIN blocks 0–2, or the DM850 bootloader.
2. Never send DM850 `update bootloader`, `update image cne`, `erase image` or
   `erase webpage`. Never run an updater VME (CPLD) stage. Never use an off-the-shelf
   M32C flasher (Renesas FDT, Delorie's tool): they erase first.
3. Change one processor at a time; the other stays on vendor firmware. DM850 recovery
   needs a working MAIN; MAIN updates need a working DM850 (or the RS-232 path).
4. Every write follows the checklist below.
5. MAIN wear budget: at most 10 MAIN writes for the whole project. Each costs one cycle
   on blocks 3–20; prior history is unknown. Log every write in the table below.
6. Nothing reaches the unit without passing that processor's offline gate.
7. The unit stays on an isolated LAN segment: the DM850 loader accepts unauthenticated
   update/erase commands from any host.

## Per-write checklist

Before:
- [ ] Offline gate for this image passed and recorded (commit hash, image sha256).
- [ ] Rollback image (vendor bytes) packed, verified, on the PC.
- [ ] Unit and PC on a sine-wave UPS/inverter; no load-shedding window or storm due
      within the next 2 hours.
- [ ] PC wired directly to the unit (crossover or a dedicated switch with nothing else
      on it), static IPs, Wi-Fi off, no other tool talking to the unit.
- [ ] Settings backup (`.bid`) taken and copied off the PC.
- [ ] Unit AC power-cycled immediately before; DM850 answers ping.
- [ ] Image set contains only the intended target; no VME stage; no bootloader image.

During:
- [ ] Do not touch the unit, cable, PC or mains. Do not abort a write in progress.

After:
- [ ] Version screen shows the expected versions.
- [ ] Read-only control queries (`tools/lan_dump.py`) answer as before.
- [ ] Web UI reachable; MAC unchanged (00:05:CD:13:81:94).
- [ ] Settings restored from `.bid`; write logged below.

## Stages

| Stage | Content | Unit writes |
|---|---|---|
| 0 | Version screen, MAC/IP, menu photos, SSManage `.bid` + FWCV parameter backup | none |
| 1 | Offline: RE FWCV/updater (loader paths, read command, RS-232 path, DM850 recovery, VME stage); RE MAIN app↔loader interface (no-touch zone, block A runtime writes); bCoD checksum; byte-exact AVTOOL3 packer | none |
| 2 | LAN hang diagnosis (firmware vs hardware); DM850 `start bootloader`/`start image`; DM850W 2006→2008; DM850I vendor round trip | DM850 only, vendor bytes |
| 3 | MAIN blocks 0–2 dump. **Primary (2026-11-05): read-only `S` read through the vendor loader protocol** — the same session the vendor updater opens on every update (`RBUPDATE`, `C`, `S` parameter read), with the `S` range set to 0xFFC000–0xFFFFFF; no `L`, no write (loader-interface.md §2.4). Preconditions: Stage 1 items 3 (how to leave update mode) and "no erase/flag on entry" answered. Fallback only if the loader filters the range: minimal read-only MAIN patch. Gate A: loader recovers a broken app by itself | 0 MAIN (primary), 1 MAIN (fallback) |
| 4 | DM850I reliability patch for the fault found in Stage 2 | DM850 |
| 5 | MAIN patches after Gate A: DM850 supervisor (E_RESET/EPOWER), protocol hardening, further functions; bypass key + boot-attempt counter | MAIN, batched |

**Gate A** is a user decision. If the loader cannot recover a broken application by
itself, functional MAIN changes carry real brick risk and the options go back to the
user.

**Last resort** (opening): only if a MAIN write leaves the loader unreachable. Needs the
ID code from Stage 3. CNVSS high via R602/J305, P65 held low (async mode 2), 3.3 V UART
on TP501. `tools/mcu_dump.py` to read; a program-capable variant that never touches
blocks 0–2 unless restoring them from the Stage 3 dump.

## Write log

| Date | Processor | Image (version, sha256 prefix) | Path | Result | MAIN cycles used |
|---|---|---|---|---|---|
| — | — | — | — | — | 0 / 10 |
