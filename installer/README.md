# avrfix — the guided installer

Cross-platform, standard-library-only tool that applies the DM850 SSDP fix to an AVR-4306.
Patch-only: it obtains the owner's **own** DM850I image (from the vendor updater), applies the
byte-diff in `avrfix/data/`, and flashes it. No Denon firmware is bundled.

## Layout

```
avrfix/
  acquire.py    obtain + extract the owner's DM850I from the vendor updater (or download)
  patch.py      apply the byte-diff; verify result sha256 + bCoD CRC
  image.py      sha256 + bCoD CRC check (lifted from tools/bcod_sum.py)
  shell.py      DM850 5001 shell + CMD_ALLOW whitelist (lifted from tools/dm850_writer.py)
  tftp.py       TFTP WRQ push         (lifted from tools/dm850_writer.py)
  probe.py      read-only probes      (lifted from tools/dm850_probe.py)
  discovery.py  find the unit by Denon OUI; pick the source NIC
  identify.py   model guard (OUI + 5001 shell + VI?)
  selftest.py   post-flash SSDP survival verdict
  flasher.py    the FSM: preflight -> confirm -> flash -> self-test -> recovery
  cli.py        guided command line        gui.py  Tkinter wizard
  resources.py  bundle-path resolver + pinned shas    data/  the byte-diff patch (no firmware)
packaging/      PyInstaller spec + entry points      tests/  offline tests (CI gate)
```

## Run

```
python3 -m avrfix            # guided CLI
python3 -m avrfix --gui      # GUI
```

## Test (the CI safety gate)

```
python3 installer/tests/test_flasher.py        # FSM: correct sequence + whitelist, vs a fake unit
python3 installer/tests/test_acquire_patch.py  # extract -> patch -> sha match (skips w/o local images)
python3 -I sim/test_dm850_writer.py            # the underlying engine
```
The flash sequence and the DM850I-only command whitelist are asserted here; a failure blocks
the packaged build.

## Build double-click binaries

```
cd installer
pip install pyinstaller
pyinstaller packaging/avrfix.spec       # -> dist/AVR-4306-Fix(.app) and dist/avr-4306-fix-cli
```
GitHub Actions does this per-OS on a tag (`.github/workflows/build.yml`). Binaries are unsigned;
the README documents the one-time Gatekeeper/SmartScreen step.

## Troubleshooting

- **"No receiver found."** Enter the IP manually. On macOS, allow Local Network access for the
  app (System Settings → Privacy & Security → Local Network).
- **"does not match the expected vendor 6.0.0.4 image."** You pointed it at the wrong updater;
  use AVR-4306 firmware 6.0.0.4 (see `OBTAINING-FIRMWARE.md`).
- **The write didn't finish / module unresponsive.** Power-cycle the receiver and run again —
  it's recoverable (see `SAFETY.md`). On a multi-NIC machine, pass `--src-ip <addr>` for the
  interface on the receiver's subnet.
