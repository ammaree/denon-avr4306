# MAIN firmware audit — bugs and optimization

Status 2026-11-10, pass 1. Audit of the MAIN M32C firmware (vendor 01.00; the "final
firmware" is vendor + the patches in CHANGELOG.md — a from-source rebuild was ruled out,
docs/main-audit.md). Uses the whole-program codebase (docs/main-codebase.md) and the
code-flow map (docs/main-codeflow.md). Confirmed = read in the disassembly. Each finding
notes severity and confidence.

## Method and coverage

Audited in depth this pass: the **external serial/network command path** — the main
remote attack surface — end to end (RX ISR → line assembler → dispatch → handler entry →
reply builder → TX ISR), and the init structure. Not yet audited: the per-mode runtime
handlers, the SUB/DSP link, the tuner/zone/DSP handlers, and the VFD output path (later
passes). Two candidate bugs were investigated and **refuted** at instruction level — that
is a result, not a gap.

## Findings

### 1. Command ingress is bounded — no overflow (confirmed, positive)

Both receive assemblers saturate the per-line index at `0x86` (`uart1_rx_assemble`
0xF4BA26 buffer 0x4A45; `uart0_rx_assemble` 0xF4BBF2 buffer 0x528E), and the per-line step
clears `0x87` bytes (docs/main-audit.md §1). The path telnet → DM850 → UART0 → MAIN and the
rear RS-232 port cannot be driven into a MAIN buffer overflow. Unknown token → id 0 →
dropped. **No fix needed.**

### 2. Reply / TX path is robust — two candidate bugs refuted (confirmed, positive)

The TX ISRs (`0xF4BB72` UART0, `0xF4B962` UART1) send the reply buffer `0x4ACC` byte by
byte, length in `0x531B`/`0x527B`, across segments whose lengths come from table `0x5265`.
Two things that looked risky in the decompiler output are correct in the instructions:

- **The reply index compare is unsigned.** `CMP.B:G 0x531B,0x5318` then **`JLTU`** — the
  index-vs-length test is unsigned, so a reply up to `0xFF` bytes is handled correctly.
  (Ghidra rendered the index as `(char)`, which suggested a signed-overflow bug at length
  ≥ 0x80; the instruction shows there is none.)
- **The shared status flags are updated atomically.** The line-ready / TX-busy byte
  `0x5319` (and `0x5279`) is manipulated with single-instruction bit ops — `BTST 0x4,…`,
  `BCLR 0x4,…` — not a read-modify-write. So the RX ISR, the TX ISR and the main loop
  touching different bits of the same byte cannot corrupt each other. No ISR/main race.

**No fix needed.** The external command subsystem is well implemented.

### 3. Watchdog: no refresh found — likely unused (note, low, unconfirmed)

No immediate-store refresh to the M32C watchdog start register `WDTS` (`0x000E`) exists in
the image, and the init does not set it up in the first instructions. This suggests the
watchdog is **not active**, which would make the already-flashed DM-dump patch's ~76 ms
main-loop block safe (docs/main-dump-patch.md). Not conclusive — a register-store refresh
can't be ruled out from static search, and the SFR region isn't in the Ghidra image.
**Recommendation:** if a MAIN write is made, add a cheap WDTS refresh inside any long
blocking operation as insurance; otherwise leave it, the risk is low.

### 4. Reply segment over-read (confirmed, low)

The cumulative reply length `0x531B` grows by each segment length from table `0x5265`
without a check against the size of the `0x4ACC` reply buffer. The lengths are firmware
-generated (not attacker-controlled), so the worst case is sending a few trailing bytes of
adjacent RAM on a malformed internal reply — an information disclosure, not a crash, and
only to the connected control client. **Low priority;** bound the cumulative length against
the buffer size if this area is ever touched.

## Pass 2 — command argument parsing (2026-11-10)

The next surface after the bounded line buffer: how handlers parse the command's argument.

### 5. Argument matcher and numeric validation are sound (confirmed, positive)

- `cmd_str_match` (`0xF4B8FC`, the shared helper) is a **bounded** byte compare of the
  received argument against a reference string of length `param_4` (a small constant). No
  overflow.
- `cmd_arg_proc` (`0xF463EF`, the source/surround/volume argument processor) **range-checks
  the numeric argument**: the master-volume value must be a multiple of 5 and `< 0x79`,
  else it sets the error path. So out-of-range volumes are rejected, not applied. Good.

### 6. Source/surround table index not locally bounds-checked (suspected, low)

`cmd_arg_proc` indexes tables near `0xF870xx` by `[FB-0x2c] * 2` with no bounds check in
the function itself. It is safe **only if** the upstream token match bounds that index —
which it normally does, because the index is the position of a matched source/surround
name (inherently 0..N). So in the shipped command set this is not reachable with an
arbitrary index. Flagged because it is a bound that lives upstream, not here: if this path
is ever extended (new sources, a new command that reuses it), add a local range check.

## Pass 3 — whole-codebase risk scan, all subsystems (2026-11-10)

To cover every subsystem for the memory-safety bug classes without hand-reading ~2000
functions, `tools/ghidra/AuditScan.java` scans **every decoded instruction** (134,611 of
them) for the dangerous patterns. Results:

### 7. No unbounded block copy anywhere in the image (confirmed, positive — strongest result)

The firmware uses the M32C block-move `SMOVF` at **45 sites**; the count register `R3` is
loaded with a **compile-time constant** immediately before **every one** (checked all 45:
`MOV.W #imm,R3` general or quick form). So there is **no variable-length / attacker-length
block copy in MAIN** — the exact bug class that crashed the DM850 SSDP responder
(docs/dm850-audit.md) does not exist here. Lengths range from 3 to `0xB0A` bytes (the last
is the boot-loader copying a fixed region), all constant.

### 8. Divide-by-zero is not a crash on this architecture (confirmed, non-issue)

380 divide sites; only 5 use a register divisor. The M32C **does not trap divide-by-zero**
— it sets the overflow flag and leaves an undefined result, no reset. So even an unguarded
register-divisor divide yields a wrong value at worst, not a crash. One checked site
(`0xF0445E`) even tests the result afterwards. Not a defect.

### 9. Large stack frames carry locals, not copy buffers (confirmed, low)

13 functions use a frame `>= 0x40` bytes. The only one on the external command path,
`cmd_dispatch_group` (`0xF46172`, 132-byte frame — previously mislabeled `cmd_build_response`),
holds small locals and dispatches by command id via a bounded `INDEXWD`/`JMPI` jump table;
it is not a copy target. The other 12 are internal (menu/display/DSP). Because finding 7
shows **no** unbounded copy exists, none of these frames can be overflowed by a length-driven
copy; they are filled by constant-count copies or field stores. Low risk.

### Coverage and honesty

Pass 3 is a **pattern scan of every instruction in every subsystem** for the memory-safety
classes (unbounded block copy, divide-by-zero, oversized stack buffers). It is not a
per-function semantic/logic audit of all ~2000 functions — that is infeasible, and the
external attack surface (the part that matters) got the per-function treatment in passes 1-2.
Logic bugs inside internal subsystems (wrong state transitions, off-by-one in a menu, a bad
table index like the §6 suspected item) are not fully covered by a pattern scan; they would
surface only in targeted per-subsystem reads, which the framework (docs/main-codebase.md)
supports on demand.

## Optimization

A 20-year-old, in-field-stable firmware offers little safe optimization headroom, and every
MAIN write spends one of the limited flash cycles with brick risk, so the bar is high.

- No hot-path inefficiency was found that would justify a write. The super-loop / init /
  mode-dispatch structure (docs/main-codeflow.md) is conventional for the era.
- The one cosmetic note: init clears RAM in ~17 separate routines (`init_01..17`); these
  could be one block clear, but that is a size/readability nicety with zero runtime benefit
  and real risk, so **not recommended**.
- The genuine improvement opportunities are the **features** already scoped (version
  identification §VERSIONS, the remote dimmer command via key-injection, display behaviour),
  not micro-optimization of working code.

## Next passes

- The per-mode runtime handlers (reached by the `JMPI` mode dispatch) — the actual control
  loops; audit for the same classes there.
- The SUB/DSP link protocol and the VFD output path.
- A sample of command handlers for argument-range validation (e.g. MV volume, TF tuner).
