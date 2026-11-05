# Phase 1 status

Maps each Phase 1 objective to the evidence in this repo and states what is achieved,
what is blocked, and why. Original images stay git-ignored; only code, docs and hashes
are committed.

## (a) Research all documentation — local and internet — COMPLETE

- Local: service manual, three updater manuals, control-protocol spec 4.6a, operating
  instructions, IR code list, recovery (FWCV) package. Read and distilled into
  [hardware.md](hardware.md), [firmware-package.md](firmware-package.md),
  [schematic-notes.md](schematic-notes.md), [update-tools.md](update-tools.md).
- Internet: Renesas M32C/87 and M16C/62P datasheets and flash guides; ADSP-2136x
  datasheet and the SHARC loader/boot notes (EE-177/EE-223/EE-345); BridgeCo DM850
  background. Distilled into [research.md](research.md). Re-checked 2026-11-05: the
  web confirms the recorded facts — M16C ID-code bytes at …EB/EF/F3/F7/FB, the ADSP
  256-instruction (1536-byte) boot kernel plus 3-word init-section headers, and the
  M32C/87 lockable user-ROM blocks with a separate 4 KB data block.
- Residual (not blocking): exact flash block-address tables and board strap levels.
  The full M32C/87 and M16C/62P hardware manuals are >10 MB and timed out from here, and
  the strap levels need the physical board. Marked **[verify]** in research.md.

## (b) Boot steps and firmware components — COMPLETE

- Components: seven images across four ISAs, all confirmed. MAIN = M32C/80 and SUB =
  M16C/60 confirmed **by disassembly** (firmware-package.md §3.1); DSP = SHARC 48-bit;
  DM850 = ARM (ARMv5T+). Stores, load addresses and the AVTOOL3 container decoded; all
  nine extracted images reproduce `ref/images.sha256` (`make verify`: 9/9).
- Update route (who writes whom) read from the package route fields and the schematic:
  PC→DM850→MAIN, MAIN→SUB, MAIN→DSP, MAIN→DM850 (schematic-notes.md §route).
- Boot chain across processors documented in re-plan.md §1c (reset → MAIN → SUB → DSP →
  DM850 link).
- **Key finding:** the MAIN reset vector, fixed/special-page vectors, the 7-byte
  flash ID code, and the C-startup (SP/SB/FB setup) are all in the resident **boot
  block** (MAIN top 16 KB, 0xFFC000–0xFFFFFF), which is **absent from every package** —
  proven by the complete absence of `ldc #imm,sp/sb/fb` encodings in 1 MB
  (control-protocol.md). The live control subsystem was traced end to end in the
  emulator to confirm the runtime boot of that path (RX ISR → ring buffer → parser →
  dispatcher → handler).

## (c) Comprehensive binary-exact rebuild plan — COMPLETE

[re-plan.md](re-plan.md) is the plan: scope (F1–F4), per-target toolchains, the
disassemble→reassemble→hash method, static-analysis order, emulation/test, and an
optional recovery-first physical path. Status refreshed 2026-11-05 to match what has
since been done.

**Feasibility conclusion (sharpened by the work done):** a byte-exact rebuild of the
*complete* firmware is not reachable from the packages alone, for two independent reasons:

1. **Boot blocks are not in any package.** The reset path and vectors live in the
   resident boot block (per (b)). The full flash image cannot be reproduced byte-for-byte
   without dumping that block from a unit (serial-I/O mode, which needs the 7-byte ID
   code — itself in the boot block, so all-0x00/all-0xFF are tried first).
2. **No complete free decoder.** The GNU `m32c-elf` CGEN disassembler leaves 14–18 % of
   the stream as `*unknown*` and misaligns, so an automatic re-assemblable round-trip is
   not possible with free tools; the GNU *simulator*, by contrast, executes those bytes
   correctly and is the better oracle. A faithful source rebuild needs either a
   commercial Renesas disassembler or hand-decoding, plus the boot-block dump.

So the plan's deliverable 1a (byte-exact asm round-trip) is **blocked on a physical
boot-block dump**; everything up to it is done.

## (d) Emulator / simulator to test — ACHIEVED (test vehicle), with a noted limit

- Built: GNU `sim/m32c` (CPU-accurate M16C/M32C) + the `m32c-elf` binutils, with a board
  shim — bootstrap stub, SFR tracer, scripted UART1 bridge ([emulation.md](emulation.md),
  tools/sim.sh, sim/).
- Validated now:
  - `sim.sh selftest` → SELF-TEST PASS (the assemble→link→simulate loop a rebuild is
    checked through).
  - Runs real MAIN firmware bytes (the CGEN-`*unknown*` ones included).
  - Live control-protocol validation on the real image: `uarttest` → UART-BRIDGE PASS;
    `dispdemo PW` → 0x0001, `dispdemo MS` → 0x0010; `rxdemo` enqueues a byte through the
    real RX ISR.
  - Extraction is byte-exact: `make verify` → 9 OK, 0 FAIL.
- **Limit:** "test *the rebuilt source binary*" is Phase 2 — there is no rebuilt binary
  yet (per (c)). And a full boot-from-reset needs the boot block (per (b)). The emulator
  is proven on the original image and ready as the differential-test vehicle for Phase 2.

## Optional: physical device test — attempted (LAN), not the firmware path

The unit is on the LAN (192.168.1.13, Denon MAC). Over LAN only the DM850 is reachable —
no path reads MAIN/SUB/DSP flash (lan-access.md), so the boot block cannot come over the
network. The DM850 also hangs under load (the "LAN not connecting" symptom). The
boot-block dump therefore requires the bench serial-I/O / JTAG route in re-plan.md §1f.

The enabling software for that route is ready: [tools/mcu_dump.py](../tools/mcu_dump.py)
is a **read-only** M32C/M16C standard serial-I/O-mode flash reader (auto-baud, version,
ID verify, page read — no erase/program). On a bench machine with a 3.3 V USB-serial
adapter wired to the MAIN/SUB serial-I/O pins and the part held in boot mode, it dumps
0xFFC000–0xFFFFFF (the boot block) to dumps/ with a sha256. That is the one remaining
step, and it needs hardware access, not more analysis.

## Bottom line

Objectives (a)–(c) are complete; (d) is complete for what Phase 1 can cover (a validated
emulator and byte-exact extraction), with the rebuilt-binary test deferred to Phase 2.
**One physical artifact — a boot-block dump of MAIN (and SUB) from a unit — unblocks both
the byte-exact rebuild and the full boot-from-reset test.** Until then those two items are
constrained by the hardware, not by analysis.
