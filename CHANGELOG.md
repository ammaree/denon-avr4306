# Changelog

Per-module firmware patches for the Denon AVR-4306. Versioning scheme: `docs/VERSIONS.md`.
"Flashed" means written to the owner's unit and verified; everything else is built and
gated offline only. Nothing is flashed without the safety-plan.md checklist.

## DM850I p1 — stamp `I200805270746` (not flashed)

Tag `dm850i-p1`. Image `build/patch/DM850I_ssdp.flash.bin` from
`tools/dm850/apply_ssdp_guard.py` over vendor `DM850I_x` (stamp `I200805270745`).

- **Fix (SSDP crash / LAN hang):** guard both URN arms of the SSDP search responder so a
  service or device `ST` with no version colon is ignored instead of driving an
  out-of-frame copy that hangs the DM850 network stack (the Belkin `M-SEARCH` from the
  LG TV, `docs/lan-hang.md`, `docs/dm850-audit.md` §1, §2, §4a).
- **Hardening:** M-SEARCH length pre-check in `receiveData` drops an `ST` longer than
  `0x40` before the search, covering a long but well-formed name the per-arm guards pass
  (`docs/dm850-audit.md` §4b).
- **Version:** bCoD build stamp `20080527074501` → `20080527074601`; bCoD CRCs recomputed.
- Gated offline: `tools/dm850/test_ssdp_guard.py` and the Unicorn
  `tools/dm850/replay_ssdp.py`. 58 bytes changed (3 BLs, 2 caves, 2 CRC words) plus the
  stamp. **Delivery and a DM850 recovery path are unsolved; not flashed.**

## MAIN — `01.00` on the unit, unversioned patch present (flashed 2026-11-06)

- **Flashed, read-only DM-dump patch** over vendor MAIN `01.00` (`docs/main-dump-patch.md`,
  `docs/lan-access.md`). Adds a `DMaaaaaa?` flash-read query; no version bump was applied,
  so the unit still reports `01.00`. 1 of 10 MAIN writes used.
- **Pending p1 = `01.01`:** the next MAIN write will set the identity string to `Ver01.01`
  and bundle the fixes/enhancements from `docs/main-audit.md`, so one cycle both versions
  the unit and improves it (`docs/VERSIONS.md`).

## Unchanged modules

SUB (`00.50`), DSP (`00.04`), DM850W, DM850D, the DM850 bootloader and the CPLDs have had
no changes.
