# denon-avr4306

Reverse engineering of the Denon AVR-4306 AV receiver firmware (target version 6.0.0.4).

- [docs/hardware.md](docs/hardware.md) — processors, flash parts, pin maps, boot-mode pins, service modes
- [docs/re-plan.md](docs/re-plan.md) — reverse-engineering plan, Phase 1 and Phase 2
- [docs/firmware-package.md](docs/firmware-package.md) — updater package format, per-processor images, ISA identification
- [docs/schematic-notes.md](docs/schematic-notes.md) — programming paths, JTAG/serial access points, update route
- [tools/](tools/) — carving, header parsing and analysis scripts; [ref/sha256.txt](ref/sha256.txt) — image hashes

Source documents (local, not in this repo):
`~/Library/CloudStorage/ProtonDrive-.../FamilyShare/Vendors/Hifi/Denon/`

Original firmware images and flash dumps are Denon copyright and are git-ignored.
