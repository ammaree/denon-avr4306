# Denon AVR-4306 — network fix

A community fix for the **Denon AVR-4306** losing its network/IP connection. The receiver's
network module crashes when a device on your LAN (for example some smart TVs' "home hub" scans)
sends a particular SSDP `M-SEARCH` request. The whole network stack hangs until you power-cycle
the receiver. This project patches the module's firmware so it **ignores the bad request instead
of crashing** — verified on hardware: a patched unit survives the exact packet that used to hang
it, where an unpatched unit dies within ~4 seconds.

> ⚠️ **Not affiliated with Denon or D&M.** "Denon" and "AVR-4306" are their trademarks, used
> only to say what device this is for. This repo ships **no Denon firmware** — it applies a small
> patch to firmware **you already own**. **No warranty, use at your own risk.** See
> [`DISCLAIMER.md`](DISCLAIMER.md).

## For AVR-4306 owners — apply the fix

1. **Read [`SAFETY.md`](SAFETY.md)** (2 minutes). Short version: it writes only the network
   module; the network drops for ~1 minute while it writes (normal); if interrupted it's
   recoverable by a power-cycle (not a brick); the one real risk is losing mains power *during*
   the write, so use stable power.
2. **Get your firmware** — see [`OBTAINING-FIRMWARE.md`](OBTAINING-FIRMWARE.md). The tool can
   auto-download the official Denon updater, or you point it at one. (Patch-only: your own
   firmware, patched on your machine.)
3. **Get the app** for your OS from the [Releases] page, or run from source (below).
4. **Run it and follow the prompts.** It finds your receiver, patches your firmware, flashes it,
   then tests the fix and tells you **FIXED** or not.

**Unsigned downloads** (no paid code-signing): macOS → right-click the app → **Open** (or
`xattr -dr com.apple.quarantine AVR-4306-Fix.app`); Windows → **More info → Run anyway**;
Linux → `chmod +x`.

### Run from source (no download)

Needs Python 3.8+ (standard library only — nothing to install):

```
cd installer
python3 -m avrfix            # guided command-line
python3 -m avrfix --gui      # graphical version
```

## How it works / for developers

The fix is a ~59-byte patch to the DM850 network module's SSDP responder (two guard "caves"
plus a length pre-check), applied to the vendor DM850I 6.0.0.4 image and re-CRC'd. The flash
path is the DM850 bootloader's TCP-5001 shell plus a TFTP **write** (push) to the module on
UDP 69 — never touching the module's own bootloader or the web pages.

- [docs/lan-hang.md](docs/lan-hang.md) — the bug, root cause, and the fix (start here)
- [docs/dm850-audit.md](docs/dm850-audit.md) — the SSDP crash analysis and the guard
- [docs/dm850-delivery.md](docs/dm850-delivery.md), [docs/updater-protocol.md](docs/updater-protocol.md) — how the flash works (verified on the unit)
- [docs/firmware-package.md](docs/firmware-package.md), [docs/update-tools.md](docs/update-tools.md) — vendor package format and update tools
- [docs/hardware.md](docs/hardware.md), [docs/re-plan.md](docs/re-plan.md), [docs/research.md](docs/research.md) — hardware, the RE plan, background
- [docs/building.md](docs/building.md) — the extraction/disassembly/verification harness (`make`)
- [installer/](installer/) — the guided tool (`avrfix`); [installer/tests/](installer/tests/) — offline tests
- [tools/](tools/) — extraction and analysis scripts; [ref/images.sha256](ref/images.sha256) — image hashes

The original Denon firmware (the vendor updater and the images extracted from it) is Denon
copyright and is **git-ignored — never committed**. Point the `Makefile`'s `SRC` at your own
local copy to run the RE harness.

## License

MIT for our original work (patch, tooling, docs) — see [`LICENSE`](LICENSE). This does not grant
any rights in Denon firmware, which is not distributed here.

[Releases]: ../../releases
