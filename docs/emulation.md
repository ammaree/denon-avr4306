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

This proves the whole **assemble → link → simulate** loop — the exact loop a rebuilt
image (asm or C→asm) will be validated through.

### Running real firmware code

```bash
sh tools/sim.sh run build/images/MAIN_01.00.flash.bin 0xF00000 0xF0D58E 3
```

`sim.sh run` wraps the raw image into an ELF at its true load address, synthesizes the
M32C reset vector at 0xFFFFFC (missing from the package — it lives in the boot block) to
point at the chosen start, converts to SREC (the sim boots an SREC from the reset
vector), and runs. The example executes the real function at 0xF0D58E — the sim decodes
`mov.w:z #0,0x3f0d; mov.w:z #0,0x3f21; add.b:q #7,-8226[fb]`, identical to objdump, then
stops with "NULL pointer dereference" when the `[fb]`-relative access runs with FB
uninitialised.

## Limits (why this is not yet a full-system boot)

1. **No board model.** The sim models the CPU, RAM/ROM, UART1 and timer A only — not the
   PCA9555 expanders, tuner, DAtuner, DSP/sub-µcom links, or the DM850. Firmware that
   reads an unmodelled SFR or polls a peripheral diverges or faults immediately.
2. **No reset entry.** The real reset vector and startup (stack/FB/SB setup, RAM init)
   are in the boot block that no package contains. Running from reset needs that block
   dumped from the unit (re-plan.md 1b). `sim.sh run` starts at a chosen address with
   uninitialised registers, so it only smoke-tests straight-line code, not whole
   functions.
3. Addresses 0x400–0x402 are hijacked by the sim's semihosting and overlap real M32C RAM
   (0x400+); irrelevant for the self-test, a minor caveat when modelling RAM behaviour.

## Next steps toward objective d

- Build a board-peripheral shim (UART1 bridge to a scripted controller, PCA9555/relay
  capture, encoder/IR injection) as a small sim patch or an LD_PRELOAD on the syscall
  hooks — enough to run the control-protocol parser.
- Dump the MAIN boot block from the unit to get a real reset path, then boot from reset.
- For the DSP (SHARC) and DM850 (ARM) there is no free cycle-accurate sim here; test
  those by image hash and, for the DM850, under QEMU-arm once its load map is confirmed.
