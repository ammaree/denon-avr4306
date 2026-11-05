#!/bin/sh
# Disassemble the de-inverted firmware images to text, at their true load addresses.
# MAIN = M32C, SUB = M16C (GNU binutils m32c-elf), DM850 = ARM LE (system objdump).
# Usage: disasm.sh <images_dir> <out_dir>
set -e
IMG=$1; OUT=$2
OBJ="${M32C_OBJDUMP:-$HOME/.local/opt/binutils-m32c-2.43/bin/m32c-elf-objdump}"
ARMOBJ="${ARM_OBJDUMP:-objdump}"   # LLVM objdump understands elf32-littlearm blobs
mkdir -p "$OUT"

dis_m() {  # file vma mach -> out
  "$OBJ" -D -b binary -m "$3" --adjust-vma="$2" "$IMG/$1" > "$OUT/${1%.flash.bin}.$3.asm"
  echo "  $1 ($3 @ $2) -> ${1%.flash.bin}.$3.asm"
}

[ -f "$IMG/MAIN_01.00.flash.bin" ] && dis_m MAIN_01.00.flash.bin 0xF00000 m32c
[ -f "$IMG/MAIN_00.76.flash.bin" ] && dis_m MAIN_00.76.flash.bin 0xF00000 m32c
[ -f "$IMG/SUB_00.50.flash.bin"  ] && dis_m SUB_00.50.flash.bin  0xC0000  m16c

# DM850 ARM: the image is relocated into SDRAM near 0x60100000 by the scatter loader;
# disassemble the on-flash copy at file offset 0 (the startup lives at 0x88).
if [ -f "$IMG/DM850I_x.flash.bin" ]; then
  python3 "$(dirname "$0")/elfwrap.py" "$IMG/DM850I_x.flash.bin" "$OUT/dm850i.elf" arm le 0
  "$ARMOBJ" -d "$OUT/dm850i.elf" > "$OUT/DM850I.arm.asm"
  echo "  DM850I_x.flash.bin (arm le) -> DM850I.arm.asm"
fi

echo "disassembly in $OUT"
