# Brief: DM850 firmware reconstruction, audit and fix proposals

For a Cursor session on this repo (`~/DevSpace/z-projects/denon-avr4306`). This is a
pointer brief: the material is already in the repo, so read it first rather than starting
from scratch. All work is on the owner's own AVR-4306 (see CLAUDE.md). **Analysis only —
nothing in this brief writes to the unit.** A DM850 flash write needs a delivery path and
a recovery path that do not yet exist (see §Constraints).

## Read first

- `CLAUDE.md` — ownership, scope, safety, the classifier note and its feedback reference.
- `docs/lan-hang.md` — the confirmed root-cause fault and the firmware target.
- `docs/dm850-firmware.md` — what the image is (BridgeCo DMP 3.0 + Denon app), why a
  source build is impossible, why the patch route is the plan, the load map.
- `docs/firmware-package.md` §3.4 — bCoD header, scatter table, SDRAM map, toolchain.
- `docs/safety-plan.md` — hard rules; rule 1/2 forbid writing the bootloader and web page.
- `~/DevSpace/z-projects/control-bridge/docs/research/2026-10-23-16-avr-network-deaths-spins.md`
  — the packet-level diagnosis (read-only reference; another project).

## Inputs on disk (git-ignored, do not commit)

- `build/images/DM850I_x.flash.bin` — the module firmware on the unit (de-inverted,
  2,147,328 B, bCoD). Also `DM850W_x` (web pages), `DM850D_x`, `DM850IMG_11.22` (older).
- `tools/bcod_sum.py` (header CRCs, 7/7 vendor images), `tools/avtool3_pack.py` (rebuilds
  every vendor container byte-for-byte), `tools/ghidra/decompile.sh`.

## a) Reconstruct the firmware

"Rebuild from source" is not possible: the BridgeCo libraries (KnOS, NicheStack port,
HAL, UPnP, streaming) ship only as linked object code (dm850-firmware.md §3). So
"recreate through whatever means possible" means **reconstruct a working, analysable form
of the firmware**, not re-link it from C. Produce, in order:

1. A loader for the ARM image into Ghidra at the real addresses: the bCoD header fields,
   the scatter/relocation table at 0x1A0 applied, body at SDRAM ~0x60100000, fast region
   ~0x400E0000, ARMv5T. A script under `tools/ghidra/` (cf. `SeedLoader.java` for the M32C
   side), so the import is reproducible.
2. A symbol recovery pass: the image is GCC 3.4.0 C++ with many diagnostic strings
   (NicheStack `nptcp.c`, `pk_alloc`, `bigbufsiz`; KnOS; the GoAhead `.asp` handlers; the
   Denon `denonProtocolModule`, `LCDDisplay.cpp`). Name functions from the strings they
   reference and from the NicheStack/ThreadX public API shapes.
3. A memory + task map: ThreadX threads and their entry points, the NicheStack buffer
   pools and socket tables, the SSDP/UPnP responder, the GoAhead server, the MAIN UART0
   link. Write it to `docs/dm850-map.md`.

## b) Audit the reconstruction

- Start at the known fault (`docs/lan-hang.md`): the SSDP `M-SEARCH` responder that reads
  an incoming `ST:` and crashes on `urn:Belkin:service:basicevent`. Find that code from
  the string refs listed there, and explain the fault in terms of the actual
  instructions (unbounded copy, bad length, null deref, table walk off the end — whatever
  it is).
- Then widen to the NicheStack INFRA:HALT class (pre-4.3): TCP/IP reassembly, DHCP, DNS,
  ICMP paths. Note each finding with its address and the condition that reaches it.
- Keep findings in `docs/dm850-audit.md`, most-serious first, each marked confirmed (seen
  in the disassembly) or suspected (pattern only).

## c) Propose fixes and enhancements

- For the SSDP crash: the minimal binary patch that makes the responder reject or ignore
  an unknown/overlong `ST` instead of faulting. Give it as a located change plus new code
  in verified free space, assembled with `arm-none-eabi-gcc` (ARMv5T), with the bCoD CRCs
  recomputed by `tools/bcod_sum.py`. Do **not** flash anything.
- Enhancements to propose (not apply): the display on/off/dimming behaviour the owner
  wants (trace `LCDDisplay.cpp` and the MAIN link), and any network hardening that falls
  out of the audit.
- For each proposal: the offline test that would validate it (a Unicorn/QEMU harness over
  the patched function, or a replay of the Belkin packet against an emulated responder) —
  the gate before any real flash.

## Constraints

- Analysis only. No DM850 flash is written. No `erase`/`update bootloader`/`update
  webpage` is ever sent (safety-plan rule 2). The DM850 has **no proven recovery path**
  if a write fails, and the vendor LAN update rewrites the web pages as a side effect
  (loader-interface.md §2.8) — so delivery is a separate, unsolved problem, not part of
  this brief.
- One processor at a time; MAIN is already patched and must not be touched here.
- Commit messages terse, **no attribution lines**. Never commit `build/` or `dumps/` or
  any firmware image.
- If a classifier stop interrupts the work, record what was reached and hand back; do not
  retry the stopped content.
