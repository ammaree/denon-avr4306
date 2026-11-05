#!/bin/sh
# Load a de-inverted firmware image into the GNU M32C simulator and run it.
#
# The M32C simulator (m32c-elf-run, from the gdb 'sim' tree) is a CPU-accurate model of
# the M16C/80..M32C core. It models the CPU and RAM/ROM only — NOT the AVR-4306 board
# peripherals (UARTs, PCA9555, tuner, DM850 link). So it is a validation harness for the
# instruction stream, not a full-system boot: code that reads an unmodelled SFR or waits
# on a peripheral will stall or diverge. Use it to (a) prove the assemble->link->run loop
# a byte-exact/C rebuild will be validated against, and (b) smoke-run real functions.
#
# Usage:
#   sim.sh selftest                         build+run the toolchain self-test
#   sim.sh run <image.bin> <vma_hex> <start_hex> [max_insns]
#
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
BINDIR="${M32C_BIN:-$HOME/.local/opt/binutils-m32c-2.43/bin}"
AS="$BINDIR/m32c-elf-as"; LD="$BINDIR/m32c-elf-ld"; OC="$BINDIR/m32c-elf-objcopy"
RUN="${M32C_RUN:-$HOME/.local/opt/sim-m32c/bin/m32c-elf-run}"
OUT="$HERE/build/sim"; mkdir -p "$OUT"

# The sim has no instruction-count limit flag; bound wall-clock with an alarm wrapper
# so a firmware function that loops on an unmodelled peripheral still returns.
cap() { s=$1; shift; perl -e 'alarm (shift @ARGV); exec @ARGV' "$s" "$RUN" "$@" 2>&1 || true; }

case "$1" in
selftest)
  "$AS" -o "$OUT/selftest.o" "$HERE/sim/selftest.s"
  "$LD" -Ttext=0xF00000 -e _start -o "$OUT/selftest.elf" "$OUT/selftest.o"
  echo "running self-test:"
  out=$(cap 10 -m m32c "$OUT/selftest.elf")
  echo "$out" | grep SimTrace
  if echo "$out" | grep -q 'SimTrace.* 2345' && echo "$out" | grep -q 'SimTrace.* 0015'; then
    echo "SELF-TEST PASS (0x1234+0x1111=0x2345, 7*3=0x15)"
  else
    echo "SELF-TEST FAIL"; exit 1
  fi
  ;;
run)
  IMG=$2; VMA=$3; START=$4; SECS=${5:-5}
  "$OC" -I binary -O elf32-m32c -B m32c \
        --rename-section .data=.image "$IMG" "$OUT/image.o"
  "$LD" -T "$HERE/sim/image.ld" --defsym IMAGE_VMA=$VMA --defsym START_ADDR=$START \
        -e $START -o "$OUT/image.elf" "$OUT/image.o"
  "$OC" -O srec "$OUT/image.elf" "$OUT/image.srec"   # sim boots SREC from reset vector
  echo "running $IMG from $START (<= ${SECS}s):"
  cap "$SECS" -d -m m32c "$OUT/image.srec" | head -60
  ;;
*)
  sed -n '2,24p' "$0"; exit 1 ;;
esac
