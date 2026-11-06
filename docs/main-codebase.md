# MAIN complete codebase (Ghidra)

Status 2026-11-06. A whole-program disassembly/decompilation of the MAIN M32C firmware,
built so control flow and cross-references resolve — replacing the per-function value-scan
that kept dead-ending on pointer/struct-relative code (docs/main-audit.md §3).

## What it is

- Ghidra project `build/ghidra/denon` (git-ignored), program **`MAIN_01.00.full.bin`**.
- The **complete image**, `0xF00000–0xFFFFFF` (`0x100000` bytes): the application
  (`0xF00000–0xFFBFFF`, `build/images/MAIN_01.00.flash.bin`) concatenated with the boot
  block `0xFFC000–0xFFFFFF` dumped from the unit on 2026-11-06
  (`dumps/dm-20261106-102403/main_FFC000_FFFFFF.bin`, sha `80ec3239…`).
- Processor `M16C/80:LE:16:default` (decodes M32C), base `0xF00000`.
- **~2016 functions** discovered; cross-references resolve (e.g. the token dispatcher
  `0xF4B42E` now shows its 4 call sites, the command processor `0xF4B1C0` its 2).

## Why it is possible now

The real reset/startup and the top-level loop live in the boot block `0xFFC000–0xFFFFFF`,
which was absent until the 2026-11-06 dump (docs/control-protocol.md). With it, the fixed
vector table resolves: **RESET (`0xFFFFFC`) → `0xFFC000`**, the other fixed vectors →
`0xFFC0BC` (the default `reit` handler). Seeding that real entry plus the application
entry lets whole-program analysis follow flow and bind the base pointers that defeated
value-scan.

## How it was built (reproducible; the image is git-ignored)

```
# 1. assemble the complete image
cat build/images/MAIN_01.00.flash.bin dumps/dm-20261106-102403/main_FFC000_FFFFFF.bin \
    > build/images/MAIN_01.00.full.bin

# 2. import + seed the real entry + whole-program analysis
analyzeHeadless build/ghidra denon -import build/images/MAIN_01.00.full.bin \
  -loader BinaryLoader -loader-baseAddr 0xF00000 -processor M16C/80:LE:16:default \
  -scriptPath tools/ghidra -preScript SeedMain.java -preScript SeedLoader.java -overwrite

# 3. seed the application cold-boot entry (0xF00000) + known anchors, re-analyse
analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin \
  -scriptPath tools/ghidra -preScript SeedApp.java

# 4. aggressive function discovery: ENTER #imm ; PUSHM prologues, re-analyse
analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin \
  -scriptPath tools/ghidra -preScript SeedPrologues.java
```

Seed scripts (`tools/ghidra/`): `SeedLoader` (fixed vectors + loader services in the boot
block), `SeedMain` (app interrupt-vector table `0xFFBF00`, agent), `SeedApp` (app entry
`0xF00000` + known code anchors), `SeedPrologues` (the 1130-function prologue scan).

## Using it

- Decompile: `tools/ghidra/decompile.sh`-style headless with `DecompileAt.java <out> <addr>…`
  (resolves each address to its function and prints C).
- Raw listing of a range: `DisasmRange.java <out> <start> <end>`.
- Cross-references: `XrefsTo.java`, or `VerifyFull.java <out> <addr>…` for function/ref counts.

## Coverage and limits (the iterative part)

- ~2016 functions cover the bulk of the application. Not yet found: functions that start
  with a bare `PUSHM` (no `ENTER`, e.g. `0xF149D6`) or other prologues, and leaf routines;
  these are picked up on demand by `DecompileAt` (it creates a function at the address) or
  by extending `SeedPrologues` with more signatures.
- Data interleaved with code (jump tables, the OSD/menu string tables) is partly still
  typed as code; the settings block and menu descriptors are not yet typed as structs.
- Nothing is named yet beyond what the docs record. Naming/typing is the ongoing cleanup.
- Two M32C instructions (`0xF33F77`, `0xF79537`) tripped the constant/stack analyzers; both
  are isolated and did not stop the analysis.

This is a foundation, not a finished reverse-engineering: it makes any MAIN question a
control-flow trace in a real codebase instead of a value-scan. Immediate payoff: the dimmer
apply (docs/main-audit.md §3) — the setup-menu dispatch and the VFD path — is now reachable
by following callers/callees from the known anchors.
