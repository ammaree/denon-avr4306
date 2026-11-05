#!/bin/sh
# Drive the GNU M32C simulator over the extracted firmware images, with a board
# shim: a bootstrap stub (sim/boot_stub.s) that stands in for the missing boot
# block, an SFR peripheral tracer, and a scripted UART1 feed.
#
# The sim (m32c-elf-run) is a CPU-accurate M16C/80..M32C core. It models the CPU,
# RAM/ROM, UART1 (TX->stdout at 0x2ea, RX<-stdin at 0x2ee, status at 0x2ed) and
# timer A. Every OTHER peripheral read returns 0 and every write is absorbed into
# backing RAM -- no fault -- so firmware that polls an unmodelled status bit spins
# (bounded here by an alarm) rather than crashing. This is a validation/observation
# harness for the instruction stream, not a full-system board model.
#
# Usage:
#   sim.sh selftest
#   sim.sh run   <image.bin> <vma_hex> <start_hex> [secs]           raw, regs=0
#   sim.sh boot  <image.bin> <vma_hex> <start_hex> [secs]           via bootstrap stub
#   sim.sh trace <image.bin> <vma_hex> <start_hex> [secs]           boot + SFR trace
#   sim.sh feed  <image.bin> <vma_hex> <start_hex> <inbytes> [secs] boot + UART1 input
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
BINDIR="${M32C_BIN:-$HOME/.local/opt/binutils-m32c-2.43/bin}"
AS="$BINDIR/m32c-elf-as"; LD="$BINDIR/m32c-elf-ld"; OC="$BINDIR/m32c-elf-objcopy"
RUN="${M32C_RUN:-$HOME/.local/opt/sim-m32c/bin/m32c-elf-run}"
OUT="$HERE/build/sim"; mkdir -p "$OUT"

cap() { s=$1; shift; perl -e 'alarm (shift @ARGV); exec @ARGV' "$s" "$RUN" "$@" 2>&1 || true; }

# Build a boot-capable SREC: image at VMA + bootstrap stub in the boot-block gap,
# reset vector -> stub -> START. Leaves $OUT/boot.srec ready to run.
build_boot() {
  IMG=$1; VMA=$2; START=$3
  # Pull the image in through the assembler (.incbin) so it carries the same
  # m32c ELF flags (0x78) as the stub; objcopy -B m32c from a raw binary yields
  # flags 0x0 and ld then refuses to merge the two objects.
  printf '\t.section .image,"a",@progbits\n\t.incbin "%s"\n' "$IMG" > "$OUT/image.s"
  "$AS" -m32c -o "$OUT/image.o" "$OUT/image.s"
  "$AS" -m32c -o "$OUT/stub.o" "$HERE/sim/boot_stub.s"
  "$LD" -T "$HERE/sim/image_boot.ld" --defsym IMAGE_VMA=$VMA --defsym START_ADDR=$START \
        -o "$OUT/boot.elf" "$OUT/image.o" "$OUT/stub.o"
  "$OC" -O srec "$OUT/boot.elf" "$OUT/boot.srec"
}

# Extract the SFR-page (0x000000-0x0003ff) accesses from a -t trace on stdin.
sfr_filter() { grep -a -oE 'MEM\[000[0-3][0-9a-f][0-9a-f]\] (=>|<=)( [0-9a-f]+)?' || true; }

case "$1" in
selftest)
  "$AS" -o "$OUT/selftest.o" "$HERE/sim/selftest.s"
  "$LD" -Ttext=0xF00000 -e _start -o "$OUT/selftest.elf" "$OUT/selftest.o"
  echo "running self-test:"
  out=$(cap 10 -m m32c "$OUT/selftest.elf")
  echo "$out" | grep SimTrace
  if echo "$out" | grep -q 'SimTrace.* 2345' && echo "$out" | grep -q 'SimTrace.* 0015'; then
    echo "SELF-TEST PASS (0x1234+0x1111=0x2345, 7*3=0x15)"
  else echo "SELF-TEST FAIL"; exit 1; fi ;;

run)
  IMG=$2; VMA=$3; START=$4; SECS=${5:-5}
  "$OC" -I binary -O elf32-m32c -B m32c --rename-section .data=.image "$IMG" "$OUT/image.o"
  "$LD" -T "$HERE/sim/image.ld" --defsym IMAGE_VMA=$VMA --defsym START_ADDR=$START \
        -e $START -o "$OUT/image.elf" "$OUT/image.o"
  "$OC" -O srec "$OUT/image.elf" "$OUT/image.srec"
  echo "running $IMG from $START, regs=0 (<= ${SECS}s):"
  cap "$SECS" -d -m m32c "$OUT/image.srec" | head -60 ;;

boot)
  IMG=$2; VMA=$3; START=$4; SECS=${5:-5}
  build_boot "$IMG" "$VMA" "$START"
  echo "booting $IMG via stub -> $START (<= ${SECS}s):"
  cap "$SECS" -d -m m32c "$OUT/boot.srec" | head -80 ;;

trace)
  IMG=$2; VMA=$3; START=$4; SECS=${5:-5}
  build_boot "$IMG" "$VMA" "$START"
  echo "tracing $IMG via stub -> $START (<= ${SECS}s):"
  cap "$SECS" -t -m m32c "$OUT/boot.srec" > "$OUT/raw.trace" 2>&1 || true
  sfr_filter < "$OUT/raw.trace" > "$OUT/sfr.log" || true
  echo "raw trace: $OUT/raw.trace ($(wc -l < "$OUT/raw.trace") lines)"
  echo "SFR-page accesses: $OUT/sfr.log ($(wc -l < "$OUT/sfr.log") lines)"
  echo "--- SFR addresses touched (addr: count) ---"
  sed -E 's/.*MEM\[(000[0-3][0-9a-f][0-9a-f])\].*/\1/' "$OUT/sfr.log" | sort | uniq -c | sort -rn | head -40 ;;

uarttest)
  # Harness self-check: feed bytes through the sim's UART1 model to the echo
  # program and confirm they come back transformed (lower->upper). Proves the
  # scripted-controller bridge (stdin->U1RB, U1C1 status, U1TB->stdout).
  "$AS" -m32c -o "$OUT/uart_echo.o" "$HERE/sim/uart_echo.s"
  "$LD" -Ttext=0xF00000 -e _start -o "$OUT/uart_echo.elf" "$OUT/uart_echo.o"
  tx=$(printf 'denon4306' | cap 4 -m m32c "$OUT/uart_echo.elf" \
        | perl -pe 's/\e\[31m.\e\[0m//g; s/\e\[[0-9;]*m//g')
  echo "fed 'denon4306' -> TX='$tx'"
  if [ "$tx" = "DENON4306" ]; then echo "UART-BRIDGE PASS"; else echo "UART-BRIDGE FAIL"; exit 1; fi ;;

feed)
  IMG=$2; VMA=$3; START=$4; IN=$5; SECS=${6:-5}
  build_boot "$IMG" "$VMA" "$START"
  echo "feeding $IN into UART1 RX, booting $IMG -> $START (<= ${SECS}s):"
  # Clean TX capture: run without -t, strip the sim's red RX-tap echo and any ANSI.
  perl -e 'alarm (shift @ARGV); open(I,"<",shift @ARGV); open(S,"|-",@ARGV); local $/; print S scalar <I>; close S;' \
       "$SECS" "$IN" "$RUN" -m m32c "$OUT/boot.srec" 2>&1 \
    | perl -pe 's/\e\[31m.\e\[0m//g; s/\e\[[0-9;]*m//g' > "$OUT/feed.tx" || true
  echo "TX capture: $OUT/feed.tx ($(wc -c < "$OUT/feed.tx") bytes)" ;;

*) sed -n '2,20p' "$0"; exit 1 ;;
esac
