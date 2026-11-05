# Emulation harness (objective d)

A CPU-accurate M32C/M16C instruction-set simulator, wired to run the extracted images.
This is the validation base a byte-exact or modern-C rebuild is checked against.

## The simulator

GNU `sim/m32c` (DJ Delorie's M16C/M32C model), built from the GDB 15.2 source with
`--enable-sim --disable-gdb`, installed at `~/.local/opt/sim-m32c/bin/m32c-elf-run`.
Tarball signature verified against the GNU keyring. Flags: `-m r8c|m16c|m32cm|m32c`
(core), `-d` (disassemble each instruction), `-t` (trace), `-v` (stats). No
instruction-count limit flag — [tools/sim.sh](../tools/sim.sh) bounds runs with an alarm.

Key property: **the simulator executes instructions that the standalone `objdump`
decoder prints as `*unknown*`.** The sim's execution engine is complete; the CGEN
disassembler shipped in binutils is not (firmware-package.md §8). So for validation the
sim is a better oracle than the disassembly.

### Semihosting / modelled I/O

The sim intercepts a few magic addresses (sim/m32c/mem.c):

| Address | Effect |
|---|---|
| 0x400 | byte write = newlib syscall (id 1 = SYS_exit, args on stack) |
| 0x401 | byte write = putchar |
| 0x402 | 8/16-bit write = `SimTrace: <pc> <value>` |
| 0x2EA / 0x3AA | M32C / M16C **UART1 TX** (console out; value 0 = exit) |
| 0x2ED, 0x2EE | UART1 control / **RX** |
| 0x104, 0x103, 0x056 | timer A |

The modelled UART1 is the same UART the AVR-4306 main µcom uses for the RS-232 / control
protocol (schematic-notes.md). That makes the sim usable later for exercising the
control-protocol parser once the parser is located and a minimal input path is stubbed.

## The board shim

The sim models the CPU, RAM/ROM, UART1 and timer A. Three gaps stop it short of a
board: there is no reset entry (the boot block is absent), real routines fault the
instant an `[fb]`/`[sb]` access lands near 0 with the pointers uninitialised, and
peripherals other than UART1/timer are unmodelled. The shim closes the first two and
makes the third observable. All of it is in [tools/sim.sh](../tools/sim.sh) and
[sim/](../sim); nothing patches the sim binary.

### Bootstrap stub ([sim/boot_stub.s](../sim/boot_stub.s))

Stands in for the missing 16 KB boot block (0xFFC000-0xFFFFFF). It sets SP/FB/SB to
valid internal-RAM addresses and jumps to a chosen entry; the linker script
[sim/image_boot.ld](../sim/image_boot.ld) places it in the empty boot-block region and
points the reset vector (0xFFFFFC) at it. The values are valid, not authentic — enough
to keep memory accesses inside the 48 KB RAM window so a routine runs far enough to
observe, not a reproduction of real boot state. Verified: with FB/SB set, fb-relative
and sb-relative load/stores resolve into RAM instead of halting at 0 (the sim's only
hard fault is a dereference of address 0 — every other unmodelled address reads 0 and
absorbs writes, so firmware stalls rather than crashes).

```bash
sh tools/sim.sh boot build/images/MAIN_01.00.flash.bin 0xF00000 <entry_hex> 3
```

### SFR peripheral tracer

`-t` prints every memory access as `MEM[addr] => v` / `<= v`. The `trace` mode boots via
the stub, captures the trace, and filters it to the SFR page (0x000000-0x0003ff),
giving a per-address access count — what peripherals a routine touches and in what
order. Modelled SFRs (UART1 RX/status/TX at 0x2ee/0x2ed/0x2ea, timer A) are intercepted
before the trace print, so the tracer surfaces exactly the *unmodelled* traffic — the
registers a fuller board model would need next.

```bash
sh tools/sim.sh trace build/images/MAIN_01.00.flash.bin 0xF00000 0xF00000 3
# -> build/sim/raw.trace (full), build/sim/sfr.log (SFR page), address histogram
```

### Scripted UART1 bridge

The sim already wires UART1 to the console: a write to U1TB (0x2ea) goes to stdout, a
read of U1RB (0x2ee) takes a byte from stdin, and U1C1 (0x2ed) reports RX-ready from
stdin readiness. That is a scripted-controller bridge on the same UART block the MAIN
µcom uses (0x2e8-0x2ef; confirmed — MAIN initialises U1MR at 0x2e8 and polls U1C1 at
0x2ed). `feed` pipes a byte file into RX and captures TX (stripping the sim's red
RX-tap echo):

```bash
printf '\x40\x31\x3f' > /tmp/cmd.bin          # example framed bytes
sh tools/sim.sh feed build/images/MAIN_01.00.flash.bin 0xF00000 <entry_hex> /tmp/cmd.bin 4
# -> build/sim/feed.tx
```

`uarttest` self-checks the bridge against an echo program (fed `denon4306`, expects TX
`DENON4306`):

```bash
sh tools/sim.sh uarttest      # -> UART-BRIDGE PASS
```

## What works now

```bash
make sim-selftest        # or: sh tools/sim.sh selftest
```

Assembles [sim/selftest.s](../sim/selftest.s), links at 0xF00000, runs it, checks the
results come back via SimTrace:

```
SimTrace: f0000c 2345     # 0x1234 + 0x1111
SimTrace: f00016 0015     # 7 * 3
SELF-TEST PASS
```

This proves the whole **assemble -> link -> simulate** loop — the exact loop a rebuilt
image (asm or C->asm) will be validated through. `uarttest` proves the UART1 bridge end
to end, and `boot`/`trace` run real MAIN code through the bootstrap stub.

## Limits (why this is not yet a full-system boot)

1. **No reset entry / no parser-in-context.** The real reset vector and C startup live
   in the absent boot block, so the true program entry is unknown. `boot`/`trace`/`feed`
   start at an address you choose; a mid-function address still faults once it needs a
   frame or global the startup would have built. Running the host control-protocol
   parser end to end needs either the MAIN boot block dumped from the unit (re-plan.md
   1b) or the C-startup located by hand — and the CGEN disassembler misaligns too often
   (firmware-package.md 8) to locate function entries reliably from the static listing.
2. **No board model.** Only CPU, RAM/ROM, UART1 and timer A are modelled. The tracer
   shows the rest as unmodelled SFR traffic (e.g. the 0xF00000 path touches a control
   SFR at 0x396); a real run needs PCA9555, tuner, DSP/sub links and DM850 modelled, or
   their status bits satisfied, so polling loops advance.
3. Addresses 0x400-0x402 are the sim's semihosting and overlap real M32C RAM; harmless
   for the harness, a caveat when modelling RAM at those addresses.

## Next steps toward objective d

- Dump the MAIN boot block from the unit to get the real reset vector, then boot from
  reset through the stub-free path — the one change that turns smoke runs into a real
  boot.
- Model (or stub the status bits of) the next peripherals the tracer flags, so a booted
  image clears its init polling loops.
- For the DSP (SHARC) and DM850 (ARM) there is no free cycle-accurate sim here; test
  those by image hash and, for the DM850, under QEMU-arm once its load map is confirmed.
