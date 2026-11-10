# DM850 complete codebase (Ghidra)

Status 2026-11-10. Whole-program disassembly of the DM850I ARM firmware, built to the same
standard as the MAIN codebase (docs/main-codebase.md) so control flow and cross-references
resolve across the whole image, not just the SSDP handful Cursor named.

## What it is

- Ghidra project `build/ghidra/denon` (git-ignored), program **`DM850I_x.flash.bin`**.
- The reconstructed image at its runtime ARM addresses: the file loaded at `0x400DFFF4`
  (BinaryLoader) plus the scatter copies (`0x60008000` SDRAM code/data, and the smaller
  `0x00400028`/`0x00410000`/`0x00540000`/`0x00580000` regions), replayed by
  `tools/ghidra/LoadDm850.java` (docs/dm850-map.md).
- Processor `ARM:LE:32:v5t`; the SSDP/UPnP and Denon-app code is Thumb, the BridgeCo
  platform (telnet server, etc.) is ARM — Ghidra follows the interworking.
- **~12,361 functions** discovered (was 34). Cross-references resolve (e.g.
  `urn_service_reply` shows its 2 callers).

## How it was built (reproducible; the image is git-ignored)

The image was already imported with the scatter loader (LoadDm850.java). Full coverage came
from re-analysis with the ARM function finder, seeded by `tools/ghidra/SeedDm850.java` (the
bCoD entry, the known SSDP/UPnP roots, and every ARM `STMFD sp!,{...,lr}` prologue in the
SDRAM code region):

```
analyzeHeadless build/ghidra denon -process DM850I_x.flash.bin \
  -scriptPath tools/ghidra -preScript SeedDm850.java
```

Unlike MAIN's M32C (where auto-analysis is weak and needed the prologue scan to carry the
load), ARM auto-analysis is strong: the few roots plus its own function finder reached
~12k functions. Annotations are applied from `docs/dm850-names.tsv` by the shared
`tools/ghidra/ApplyNames.java`.

## Why this matters

The DM850 is the network module — the LAN-facing attack surface. A navigable codebase turns
every DM850 question (the NicheStack INFRA:HALT class suspected in dm850-audit.md §3, the
web server, UPnP, streaming) into a control-flow trace instead of a string-reference guess,
the same lift the MAIN codebase gave.

## Coverage and limits

- ~12,361 functions cover the bulk of the image. The platform is BridgeCo **object code**
  with no source (docs/dm850-firmware.md), so names/types are recovered, not original.
- Data (tables, the UPnP/SSDP format strings, the web pages) is partly still typed as code.
- Naming/typing is the ongoing iteration (docs/dm850-names.tsv, docs/dm850-codeflow.md).
- There is still **no proven flash delivery or recovery path** for the DM850, so audit
  findings here cannot be acted on (flashed) yet — the value is understanding and the
  offline-gated patches (the SSDP guards).
