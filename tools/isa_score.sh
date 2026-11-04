#!/bin/sh
# Disassemble a raw (already de-inverted) image with GNU objdump for m32c-elf as both
# M16C and M32C and count invalid opcodes; the right ISA gives far fewer "(bad)".
# Usage: isa_score.sh <objdump> <image.bin> <vma_hex> [start_hex] [len_hex]
OBJDUMP=$1; IMG=$2; VMA=$3; START=${4:-0}; LEN=${5:-0x4000}
for M in m16c m32c; do
  n=$($OBJDUMP -D -b binary -m $M --adjust-vma=$VMA --start-address=$((VMA+START)) --stop-address=$((VMA+START+LEN)) "$IMG" | grep -cE '\(bad\)|\*unknown\*')
  t=$($OBJDUMP -D -b binary -m $M --adjust-vma=$VMA --start-address=$((VMA+START)) --stop-address=$((VMA+START+LEN)) "$IMG" | grep -cE '^ *[0-9a-f]+:')
  echo "$M: $n unknown of $t instructions"
done
