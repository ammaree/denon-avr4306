# Rebuilding images and disassembly

The original Denon firmware is not in this repo. Everything is regenerated from the
vendor update tools in the local docs folder.

## Prerequisites

- Python 3 (standard library only).
- GNU binutils built for `m32c-elf` (M16C + M32C disassembly) at
  `~/.local/opt/binutils-m32c-2.43/bin/` — see firmware-package.md §8. Override with
  `M32C_OBJDUMP=...`.
- `objdump` that understands `elf32-littlearm` (LLVM's, Apple's, or GNU arm) for the
  DM850 image. Override with `ARM_OBJDUMP=...`.
- `unshield` (Homebrew) only if you also want the FWCV recovery images.

## Targets

```bash
make images     # extract + de-invert all firmware images into build/images/
make verify     # check build/images against ref/images.sha256
make disasm     # disassemble MAIN/SUB/DM850 into build/disasm/
```

`SRC` points at the folder holding the tools (default is the ProtonDrive Denon folder);
`UPD` picks the updater zip. `build/` is git-ignored.

## What `make images` produces

Nine `*.flash.bin` files — the true flash contents (de-inverted where the updater stored
them XOR 0xFF):

| File | Target | Load | Source |
|---|---|---|---|
| MAIN_01.00.flash.bin | M32C main µcom | 0xF00000 | 6.0.0.4 |
| MAIN_00.76.flash.bin | M32C main µcom | 0xF00000 | FWCV recovery |
| SUB_00.50.flash.bin | M16C sub µcom | 0x0C0000 | 6.0.0.4 |
| DSP_00.04.flash.bin | ADSP-21366 (loader stream) | 0x008000 | 6.0.0.4 |
| DM850I_x.flash.bin | DM850 ARM image | 0x000000 | 6.0.0.4 |
| DM850W_x.flash.bin | DM850 web pages | 0x000000 | 6.0.0.4 |
| DM850D_x.flash.bin | DM850 placeholder page | 0x000000 | 6.0.0.4 |
| DM850IMG_11.22.flash.bin | DM850 recovery image | 0x000000 | 6.0.0.4 (res 351) |
| DM850_11.22.flash.bin | DM850 2005 image | 0x000000 | FWCV recovery |

All nine reproduce the hashes in [ref/images.sha256](../ref/images.sha256); `make verify`
checks this.

## Tools

- [tools/extract.py](../tools/extract.py) — PE resource walk + AVTOOL3 split + de-invert.
- [tools/disasm.sh](../tools/disasm.sh) — per-target disassembly at true load addresses.
- [tools/elfwrap.py](../tools/elfwrap.py) — wrap a raw blob as ELF for ARM objdump.
- [tools/isa_score.sh](../tools/isa_score.sh), [tools/isa_signatures.py](../tools/isa_signatures.py)
  — ISA identification.
- [tools/pe_map.py](../tools/pe_map.py), [tools/pe_ports.py](../tools/pe_ports.py) — PE and
  Winsock analysis of the Windows tools.

Note: the GNU M16C/M32C decoders leave 14–18 % of instructions as `*unknown*`
(firmware-package.md §8); the `.asm` files are a starting point, not a complete decode.
