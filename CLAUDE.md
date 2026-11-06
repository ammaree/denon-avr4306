# denon-avr4306 — project context

## Ownership and scope

- All work is done on the owner's own unit: a Denon AVR-4306, MAC 00:05:CD:13:81:94,
  serial number **<fill in: SN not recorded in this repo>**.
- Objective: fix a firmware bug that makes the unit lose LAN IP connectivity, and improve
  the display on/off/dimming and other functionality.
- All research is done locally, on the owner's own LAN. No third-party equipment is
  involved.

## Safety

- A hardware-safety-first design is in place: docs/safety-plan.md (hard rules, per-write
  checklist, write log). Every flash write is gated, verified by read-back and logged.
- Backups taken from the unit (kept in `dumps/`, git-ignored, copied off the Mac by the
  owner):
  - MAIN application flash 0xF00000–0xFFBFFF, equal to vendor 01.00 (2026-11-05).
  - MAIN settings RAM 0x040C–0x2701 and full RAM (2026-11-05, before the first write).
  - MAIN resident blocks 0xFFC000–0xFFFFFF, read twice with identical results
    (2026-11-06).
- Not yet read from the unit: DM850 flash, SUB, DSP, CPLDs. Their vendor images are
  in the updater packages, but the unit's own contents have not been dumped.
