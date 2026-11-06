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
- [ ] Settings backup (settings RAM 0x040C–0x2701 from the Stage 3 session, or a `.bid`) taken and copied off the PC.
- [ ] Unit AC power-cycled immediately before; DM850 answers ping.
- [ ] Image set contains only the intended target; no VME stage; no bootloader image.

During:
- [ ] Do not touch the unit, cable, PC or mains. Do not abort a write in progress.

After:
- [ ] Version screen shows the expected versions (`loader_client.py status`).
- [ ] Read-only control queries (`loader_client.py status`, `tools/lan_dump.py`) answer as before.
- [ ] Web UI reachable; MAC unchanged (00:05:CD:13:81:94).
- [ ] Settings restored (`loader_client.py settings-restore`, or from a `.bid`); write logged below.

## Stages

| Stage | Content | Unit writes |
|---|---|---|
| 0 | Version screen (done by `VI?`: 6.0.0.4), MAC/IP, menu photos. The settings backup is **not** a normal-mode step: SSManage itself enters update mode to take it (update-tools.md §3a). It moves into the Stage 3 session | none |
| 1 | Offline: RE FWCV/updater (loader paths, read command, RS-232 path, DM850 recovery, VME stage); RE MAIN app↔loader interface (no-touch zone, block A runtime writes); bCoD checksum; byte-exact AVTOOL3 packer | none |
| 2 | LAN hang diagnosis (firmware vs hardware); DM850 `start bootloader`/`start image`; DM850W re-flash of the same vendor build; DM850I re-flash of the same vendor build. **Conflict (2026-11-06, loader-interface.md §2.8):** every vendor LAN run sends `erase webpage` for DM850W/D, with no version check, and rule 2 forbids `erase webpage`. This step needs a user decision | DM850 only, vendor bytes |
| 3 | MAIN blocks 0–2 dump. **`S` read: tried 2026-11-05, does not reach blocks 0–2** (the loader ignores the range; sub 0 = application flash, sub 1 = RAM; lan-access.md). The same session took the settings backup (RAM 0x040C–0x2701) and proved the application flash equals vendor 01.00. Update-mode entry and power-cycle exit worked, settings kept. **Remaining route: minimal read-only MAIN patch** — built and simulator-tested, not delivered: `DMaaaaaa?` query, 314 bytes changed (main-dump-patch.md). Delivery analysed 2026-11-06: the vendor updater always runs stage 2 (DM850W erase + write), so the recommended path is an own `L`/`P` writer for MAIN only (main-dump-patch.md §5). Gate A: loader recovers a broken app by itself | 0 MAIN (S read, done), 1 MAIN (patch) |
| 4 | DM850I reliability patch for the fault found in Stage 2 | DM850 |
| 5 | MAIN patches after Gate A: DM850 supervisor (E_RESET/EPOWER), protocol hardening, further functions; bypass key + boot-attempt counter | MAIN, batched |

**Gate A** is a user decision. If the loader cannot recover a broken application by
itself, functional MAIN changes carry real brick risk and the options go back to the
user.

**Gate A verdict (2026-11-06, loader-interface.md §5):** the resident updater can
reprogram a blank application without opening the unit, but only when power-on finds
the key chord that stores mode 4 (AN_3 code 6, AN_4 code 4, AN_5 at 0x3D6–0x3FF). It
does not do that unattended. Any other cold-boot key state jumps to 0xF00000 with no
checksum and no entry-pointer test, and a blank application there does not come back
to the updater. Mode 0x0C still needs the header pointer at 0xFFBE7C. The decision on
further MAIN writes stays with the user.

The MAIN writer for Stage 3 (Option C, main-dump-patch.md §5) is `tools/loader_client.py
write`: MAIN target 1 only, the vendor `C`→`I`→`L`→`P` sequence with a full read-back
verify, gated by a two-image sha256 whitelist and `--confirm-write` (which prints this
checklist until given). It was run on the unit on 2026-11-06 to deliver the DM-dump patch
(write-log row below; 1 of 10 MAIN writes used, settings reset by the write).

`loader_client.py` has grown the rest of the per-unit tooling, all simulator-tested
against `sim/fake_unit.py` (`make sim-writetest sim-toolstest`) and **not yet re-run on the
unit beyond the write above**:
- `status` — read-only VI? + a mode probe. `verify` — read-back (S sub 0, or the DM dump)
  compared byte-for-byte to a reference; read-only.
- `settings-save` / `settings-restore` — the SSManage save/load flows (update-tools.md §3a):
  save reads the parameter RAM 0x040C–0x2701; restore writes it back with `L` sub 1 + `D`.
  **RAM, not flash** — a restore costs no MAIN flash cycle and cannot brick the unit — but
  it enters update mode, so it needs `--confirm-restore` and the environment parts of this
  checklist. This is how the settings reset by a MAIN write are recovered.
- `rollback` — `write` restricted to the vendor (unpatched) image; counts as a MAIN write.
- Every run appends a structured record to `dumps/session-log.jsonl` (git-ignored).

The X(1,2,1)+RBNORM update-mode exit used by save/restore is decompiled (update-tools.md
§3a) but not yet exercised on the unit; `--power-cycle-exit` falls back to the proven
power-cycle exit.

**Last resort** (opening): only if a MAIN write leaves the loader unreachable. Needs the
ID code from Stage 3. CNVSS high via R602/J305, P65 held low (async mode 2), 3.3 V UART
on TP501. `tools/mcu_dump.py` to read; a program-capable variant that never touches
blocks 0–2 unless restoring them from the Stage 3 dump.

## Write log

| Date | Processor | Image (version, sha256 prefix) | Path | Result | MAIN cycles used |
|---|---|---|---|---|---|
| 2026-11-05 | MAIN | none (read-only update-mode session: `S` sub 0 and sub 1) | LAN, TCP 5000 | OK; unit normal after power cycle | 0 / 10 |
| 2026-11-06 | MAIN | 01.00 + DM-dump patch, sha256 `9470fa59…` | LAN, TCP 5000, `loader_client.py write`; house LAN (rule 7 deviation, user decision) | OK; read-back equal; patch works; **settings reset to defaults**; blocks 0–2 dumped | 1 / 10 |
| 2026-11-06 | MAIN | settings RAM only (restore of 2026-11-05 backup, sha256 `02bed182…`) | LAN, TCP 5000, `settings-restore`, X+RBNORM exit | OK; presets back; survive standby + power cycle | 1 / 10 (no flash) |
