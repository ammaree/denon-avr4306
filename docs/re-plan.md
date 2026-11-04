# AVR-4306 firmware reverse-engineering plan

Status: draft from local documentation only (service manual Ver. 3, upgrade manual,
control protocol 4.6a, operating instructions). No firmware image has been analysed yet.
Hardware facts: [hardware.md](hardware.md).

## 1. What "the firmware" is

Version 6.0.0.4 is not one binary. Per processor:

| # | Target | ISA | Store | Field-updatable | Priority |
|---|---|---|---|---|---|
| F1 | Main µcom M30879 | M32C/80 | internal flash | yes (via update tool, path to confirm) | 1 |
| F2 | Sub µcom M30624 | M16C/60 | internal flash | likely | 2 |
| F3 | DSP ADSP-21366 | SHARC | LH28F160 parallel flash | likely (sub CPU drives VPP/DSPBOOT) | 3 |
| F4 | Network module DM850 | ARM32 LE (BridgeCo, GCC 3.4.0, ThreadX) | W19B320 flash | yes (I/W/D/IMG images in package) | 4 |
| F5 | CPLDs EPM570 ×2, LC4064V | logic | on-chip | probably factory-only | 5 |
| F6 | EDID EEPROMs ×3 | data | BR24L02 | runtime-written by sub CPU? | data only |
| F7 | FLI2310 settings | data | in F1/F2 image (expected) | with host | data only |

The scope of "rebuild a binary-exact copy" is F1–F4. F5 is a netlist problem, not
firmware; F6/F7 are data tables carried in or written by F1/F2.

## 2. Feasibility and the byte-exact requirement

A binary-exact rebuild from **C** requires the original compiler, version, options and
link order. Expected original toolchains **[verify from image signatures]**:

| Target | Likely original | Free alternative |
|---|---|---|
| F1, F2 | Renesas NC308 / NC30 (2005–2008 releases) | GNU binutils `m32c-elf` (assembles M16C and M32C) |
| F3 | Analog Devices VisualDSP++ 4.x | none — need own assembler or emit raw words |
| F4 | depends on core | depends on core |

Approach, in order of confidence:

1. **Byte-exact assembler source** (always achievable): disassemble to re-assemblable
   source with symbols, reassemble, `sha256` must match. This is the Phase 1 deliverable.
2. **Matching C** (only if the original compiler can be obtained and identified): convert
   functions one at a time from asm to C that compiles to identical bytes, keeping the rest
   as asm. Same method as console decompilation projects. Progress = % of bytes matched.
3. **Equivalent C** (Phase 2): clean C with the same behaviour, verified by differential
   testing in the emulator, not by bytes.

Rough effort (estimate, single engineer, for F1 alone): image extraction and asm round-trip
2–4 weeks; full annotation 3–6 months; matching C depends entirely on toolchain access.

## 3. Phase 1 work breakdown

### 1a. Documentation and research

Done: local docs read, processor inventory, pin maps, boot-mode pins, service modes,
control protocol.

To do (online):
- M32C/87 and M16C/62P hardware manuals: memory map, flash size, vector table, ID-code
  check, standard serial I/O mode protocol, boot program area.
- ADSP-21366 hardware reference: boot modes (BOOT_CFG), loader (.ldr) format, SPI slave boot.
- LH28F160BJE and W19B320 datasheets: command sets, sector maps, protection.
- BCOIC-DM850: identify CPU core and SDK. Search Denon/Marantz models of the same era
  that share it.
- FLI2310: configuration method.
- Community sources: AVR-4306 / AVC-4320 / AVR-4806 owner and repair forums, prior dumps.
- Schematic pages (PDF images): find test pads/headers on CNVSS, P50, P55, UART pins,
  DSP JTAG, DM850 JTAG/UART, CPLD JTAG.

### 1b. Image acquisition (two independent sources, cross-checked)

Source A — vendor packages (no risk to the unit):
- Unpack the three updater versions and the network recovery package in an isolated
  directory; identify the per-processor images, their containers, checksums and
  load addresses.
- Diff 6.0.0.2 → 6.0.0.3 → 6.0.0.4 to find which processors each release touched.
- Decode the update transfer protocol from the updater (needed to know what the unit
  checks before it writes — essential for safe testing and for the security audit).

Source B — the unit (read-only first):
- Record the version screen (SURROUND PARAMS + STATUS). Compare to 6.0.0.4.
- Passive network inventory: which TCP/UDP ports answer (expected TCP 23).
- Flash read-back, only with the unit opened, on the bench, with an isolating
  transformer (mains inside the case — service manual safety section):
  - F1/F2 via Renesas standard serial I/O mode. Readout requires the 7-byte ID code;
    the code lives in the image's vector area, so get it from Source A first.
    Do not guess IDs against the live part.
  - F3 by reading LH28F160 in-circuit (DSP held in reset by DSPRST) or via DSP JTAG.
  - F4 via DM850 JTAG/UART if exposed, else in-circuit flash read.
- Store every dump with sha256 in `dumps/` (git-ignored). These dumps are the recovery
  baseline for every later step.

Exit criterion: for each of F1–F4, image from A == image from B (or the difference is
explained, e.g. per-unit config sectors).

### 1c. Boot chain (to confirm per image)

Expected sequence from the pin tables:

1. Mains on → standby supply → main µcom F1 resets, runs from internal flash (CNVSS = L).
   Handles IR, POWER KEY interrupt, LEDs while in standby.
2. Power on → F1 drives POWER relay, then `EXP19 SCPU POWER` (TC4094) and releases
   sub-µcom reset (P87).
3. F2 starts, switches DIGITAL POWER (P72), I/O POWER after 10 ms, DSP oscillator after
   20 ms (manual timings), then releases DSPROMRST/DSPRST.
4. DSP F3 boots from LH28F160 (boot source to confirm from BOOT_CFG straps).
5. F2 initialises PLDs (runtime registers), HDMI Rx/Tx, DIRs, DACs, EDID.
6. F1 powers the network module (EPOWER) and releases E_RESET; F4 boots from its own flash
   and links to F1 over SPI + UART.
7. F1 drives OSD, FL display, video switching, volume.

Each step becomes a section in `docs/boot/` with addresses and code references once the
images are in hand.

### 1d. Static analysis

- Tooling: Ghidra (M16C/60 and M16C/80 processor modules ship with it; M32C/80
  extensions need checking — may need SLEIGH additions). SHARC needs a third-party or
  own SLEIGH spec. GNU `m32c-elf-objdump` as a second disassembler for cross-checks.
- Order for F1: vectors → reset → init → main loop → serial protocol parser (UART1, TCP
  via F4) → main↔sub protocol → front panel/IR → display/OSD → audio/video switching →
  update/flash-write code.
- Name every peripheral access against the hardware manual SFR map; tie every port
  access to the pin table in hardware.md.
- Output: re-assemblable source per image under `src/<target>/asm/`, `make verify`
  checks sha256 against the reference hashes (hashes are committed; images are not).

### 1e. Emulation and test

- F1/F2 ISA: GDB's `sim/m32c` simulator covers M16C and M32C instructions **[verify
  coverage of M32C/87]**. Add peripheral models: timers, UARTs, interrupt controller,
  ports, flash registers.
- Board model: UART link F1↔F2, stub DM850 on SPI/UART, FL display capture (PT6302
  serial stream → text), TC4094 output capture (relays, mutes), encoder/key/IR injection.
- F3: no free SHARC simulator expected; test F3 by image hash only, and by its host-port
  traffic from F2.
- Differential testing: run original and rebuilt image side by side; feed identical
  stimulus (control-protocol commands, key presses, IR codes from
  `AVR-4306_AVC-4320_IR_Codes.pdf`); compare all outputs cycle-by-cycle for asm builds,
  event-by-event for C builds.
- Byte-exact asm builds need no behavioural test beyond the hash; the emulator matters for
  Phase 2.

### 1f. Physical testing (optional, recovery-first)

Order, each step gated on the previous:

1. Read-only checks only (version screen, control protocol, port inventory).
2. Full flash dumps of F1–F4 (1b, Source B) and a proven write-back of the **original**
   F1 image via serial I/O mode on the bench. Until that write-back has worked once, no
   modified image goes near the unit.
3. Byte-exact rebuilds: flash only an image whose hash equals the original — this proves
   the toolchain path, not the code.
4. Modified images: F1 first (internal flash, recoverable via serial I/O mode). F3/F4
   only after their own in-circuit recovery is proven. Never test through the network
   updater unless its failure behaviour is understood from 1b.
5. Keep the unit's per-unit data (EEPROM settings, MAC address, EDIDs) from step 2.

## 4. Phase 2

### 2e. Repository layout (this repo)

```
docs/            hardware, plan, boot chain, protocols, audit findings
tools/           extractors, hash checks, disassembly helpers (own code only)
src/main/asm     F1 re-assemblable source
src/sub/asm      F2
src/dsp/asm      F3
src/net/         F4 (once the core is known)
src/*/c          Phase 2 C sources
sim/             emulator, board model, test stimulus
ref/sha256.txt   reference hashes of original images
orig/, dumps/    original images and dumps — git-ignored, never pushed
```

### 2f. Modern C

- Per processor, C11, freestanding, no dynamic allocation.
- HAL layer per SFR group so the logic builds and unit-tests on the host.
- Keep the original module boundaries found in 1d; one C module per identified subsystem.
- Compiler: `m32c-elf-gcc` if a usable build exists **[verify — GCC m32c support status]**,
  else LLVM is not an option for M16C; fallback is a commercial Renesas compiler.

### 2g. Audit

Checklist, applied to both the recovered original and the new C:

Reliability
- Watchdog use and coverage; behaviour on main↔sub link loss; DSP boot failure handling.
- Brown-out path (P84 B.DOWN): settings write atomicity, flash wear of the settings area.
- Protection input (P83) and temperature input (P20) response times.
- Interrupt priorities, shared-buffer races between UART ISRs and the main loop.

Functionality
- Control protocol vs spec 4.6a (every command, 200 ms response limit, 4 s after PWON).
- Known field complaints for this model (collect in 1a).

Security
- TCP 23 control: documented without authentication — any LAN host can control the unit.
- Network update path: does the unit authenticate or check integrity of images before
  writing? Can it be triggered without physical presence?
- Parser robustness: 135-byte command limit, iPod, XM, RS-232, main↔sub frames, USB
  mass-storage and network-audio parsers in F4.
- Flash ID-code protection settings on F1/F2.

## 5. Open questions

1. DM850 CPU core: ARM (confirmed); exact core and SoC memory map still open.
2. Updater rewrites F1, F2, F3 and F4; route MAIN→SUB→DSP and MAIN→DM850 (package header). Resident boot blocks are not in the package.
3. DSP: boots from LH28F160 on its parallel port; SUB can change BOOTCFG and feed it over SPI (schematic-notes.md). Strap levels still to confirm.
4. Serial I/O mode pins: MAIN has TP501 (unfitted) + R602/J305/J306 options; DSP has an unfitted 10-pin JTAG footprint CX502; see schematic-notes.md.
5. Contents and purpose of `SSManage4306.EXE` and `original_AVR-4306.bid`.
6. Availability of NC308/NC30 and VisualDSP++ versions matching the originals.

## 6. Legal

The original images are Denon copyright. Keep them, dumps and update packages out of any
pushed repository (`.gitignore` covers `orig/`, `dumps/` and binary extensions). Commit
only own code, documentation and hashes.
