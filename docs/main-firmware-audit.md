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
