# Disclaimer, trademarks, and safety

## Not affiliated with Denon / D&M

This is an independent, community reverse-engineering and repair project. It is **not**
affiliated with, authorized, endorsed, or supported by Denon, D&M Holdings, Masimo, Sound
United, or any related company. "Denon" and "AVR-4306" are trademarks of their respective
owners, used here **only nominally** to identify the device this project is for. No endorsement
is implied.

## What this project distributes (and does not)

- It distributes **our own byte-patch and tooling** — original work that fixes a bug in the
  DM850 network module's SSDP handling.
- It distributes **no Denon firmware**. The patch is applied, on your own machine, to firmware
  **you already own** (extracted from the official vendor updater). The repository contains no
  Denon firmware images; those are git-ignored and never published here.
- It is **non-commercial**: no ads, no paid features, no donations tied to the firmware.

This is in the spirit of repair and interoperability of a device you own — a long-discontinued
receiver for which no official fix exists.

## No warranty — use at your own risk

THIS SOFTWARE AND PATCH ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. You use them
entirely at your own risk. The authors are not liable for any damage to your equipment, data,
or anything else.

## Safety — flashing can disable your receiver's network module

- Flashing writes new firmware to the DM850 network module. During the ~1-minute write the
  receiver's LAN connectivity drops — **this is normal**.
- If a write is interrupted *logically* (network glitch, aborted transfer), the module is
  **recoverable**: an AC power-cycle returns it to its bootloader and you re-run the tool. The
  module's own bootloader is never written, by design.
- **The one way to truly brick the module is losing mains power DURING the write.** Use stable
  power (a UPS if you have one), and do not switch the receiver off while it is writing.
- This fix was developed and verified on a single unit and one firmware build (6.0.0.4). Other
  regions/variants are untested. The tool checks your device and firmware before writing and
  refuses if they don't match what it expects.

Read `SAFETY.md` before running the tool, and only ever use it on **a receiver you own**.
