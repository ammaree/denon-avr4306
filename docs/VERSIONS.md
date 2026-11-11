# Firmware versioning

Every patched module gets a **minor-version uptick** that is uniquely identifiable on
the unit itself (via `VI?`), so a patched module can never be confused with vendor
firmware or with an earlier patch. Each version is recorded in `CHANGELOG.md` and
tagged in git as the repo release that builds it.

## Rule

- One minor bump per patched build of a module, in the field the unit reports through
  `VI?` (see each module below). Never reuse a number.
- The bump and its changes land in the **same flash write** — never spend a MAIN write
  cycle on a version bump alone (safety-plan.md rule 5, 10-write budget).
- Every bump has a `CHANGELOG.md` entry and an annotated git tag
  `<module>-p<rev>` on the commit that produces the image.
- The repo (CHANGELOG + tag) is the authoritative map from an on-unit version to the
  exact changes and the commit.

## `VI?` fields

`VI?` returns `VI01:MMMM;02:SSSS;03:DDDD;0A:<bootstamp>,<imgstamp>` — MAIN, SUB, DSP,
then the DM850 bootloader and image stamps.

**Correction (observed on the unit 2026-11-11):** field `0A` does **not** surface the
DM850I bCoD build stamp. On the flashed unit `VI?` returns `0A:B200510231011…,I unknown` —
the image-stamp slot reads the literal placeholder `I unknown` (that string, with `B unknown`
/ `C unknown`, is baked into the DM850I image at offset `0x1A837E` in both the vendor and the
patched build). So a DM850I patch is **not** uniquely identifiable via `VI?`; the bCoD stamp
at header `0x08` is only visible by reading the flashed image back, or inferred from a
functional test (the SSDP survival check). The `VI?`-identifiable scheme below holds for MAIN,
not for DM850I.

## Module registry

| Module | Vendor version | On-unit field | Patched version | Flashed? |
|---|---|---|---|---|
| MAIN (M32C app) | `Ver01.00` → `VI?` `01:0100` | identity string `Ver01.00` at `0xFFBEB0`; `VI?` MAIN field | **p1 = `01.01` (pending)** | no — bundled with the next MAIN write |
| DM850I (network image) | stamp `20080527074501` | bCoD build stamp at header `0x08` (NOT shown by `VI?`, which reads `I unknown` — see correction above; read the image back to confirm) | **p1 = stamp `20080527074601`** | **yes — flashed & verified 2026-11-11** |
| SUB (M16C) | `00.50` | `VI?` SUB field | — | unchanged |
| DSP | `00.04` | `VI?` DSP field | — | unchanged |
| DM850W / DM850D | build stamps | — | — | unchanged |

### MAIN minor scheme

The minor is the two digits after the dot in the identity string `Ver01.NN` at
`0xFFBEB0` and the matching `VI?` MAIN field. `p1` = `01.01`.

**Gap to correct:** the DM-dump read-only patch flashed 2026-11-06 (lan-access.md)
reports `01.00` — it was flashed before this scheme, so a patched unit currently looks
like vendor. The next MAIN write (which the audit in `docs/main-audit.md` is scoping)
carries `01.01` **and** the audited fixes, closing the gap without a wasted cycle.

### DM850I minor scheme

The bump is the minute field of the bCoD build stamp, advanced by the patch revision
from the vendor `0745`. `p1` = minute `46`, stamp `20080527074601`. The header CRC is
recomputed by `tools/bcod_sum.py` after the stamp change. Note: this stamp is **not**
reported by `VI?` (which shows `I unknown` for DM850I — see the correction above); it is the
record in the flashed image's bCoD header, confirmable only by reading the image back.

## Releases

| Tag | Module | Version | Commit produces | Status |
|---|---|---|---|---|
| `dm850i-p1` | DM850I | stamp `20080527074601` | `build/patch/DM850I_ssdp.flash.bin` (SSDP triple guard) | **flashed & verified 2026-11-11** |
