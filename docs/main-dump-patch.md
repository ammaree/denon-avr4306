# MAIN read-only dump patch ("DM" query)

Status 2026-11-05: built and passing in the simulator. **Not on the unit.** Purpose:
read MAIN blocks 0–2 (0xFFC000–0xFFFFFF, Denon's resident loader, the reset vector and
the ID code), which the loader's own `S` read does not return (lan-access.md, first
update-mode session). Cost: 1 MAIN write (safety-plan rule 5).

## 1. What the patch does

A received control line `DMaaaaaa?<CR>` (6 upper-case hex digits, `aaaaaa` in
0xF00000–0xFFFFE0) is answered with `DMaaaaaa` + 32 bytes as 64 hex digits + CR, on the
channel it came in on. It works in normal mode, over the network (TCP 5000 or 23) and
the rear RS-232 port. No update mode, no power cycle. Every other line, including
malformed `DM` lines, follows the vendor code unchanged.

The hook reads flash only. Its only writes are its own stack frame and the UART
transmit register, and every wait is bounded.

## 2. Where it hooks (MAIN 01.00, evidence)

| Fact | Evidence |
|---|---|
| 0xF45EEC is the per-line command step; line buffers 0x4A45 (UART1, rear RS-232) and 0x528E (UART0, DM850 link) | decompile; app vectors 18/20 (UART0/UART1 RX at 0xF4BBF2/0xF4BA26) store into these buffers |
| 0xF4B1C0(line) is called for every line, from exactly two sites: 0xF45F97 and 0xF4603B | `tools/m32c_callers.py` byte scan (validated on known calls) |
| Convention: caller `push.l line; jsr.w; add.l #4,sp`; callee reads 8[fb]; reply id in r0; 0x113 = no reply | disassembly at the call sites and in 0xF4B1C0 |
| First 4 bytes `EC 0C 8F 28` (`enter #0xc; pushm r2,a0`); nothing jumps into 0xF4B1C1–C3 | bytes; caller scan |
| Epilogue `mov.w -4[fb],r0; popm r2,a0 (8E 14); exitd (FC)` | bytes at 0xF4B2DA |
| Replies go out from buffer 0x4ACC via the UART0/UART1 TX ISRs (vectors 17/19); bit 4 of 0x5319 / 0x5279 = ISR sending; the ISR does nothing while that bit is clear | decompile of 0xF4BB72 and 0xF4B962 |
| Free space 0xFA969A–0xFFBD7B erased | loader-interface.md §1.5; checked by the build tool |

**Patch bytes:** 0xF4B1C0–C3 `EC 0C 8F 28` → `CC 00 97 FA` (`jmp.a 0xFA9700`), and the
hook at 0xFA9700–0xFA9835 (310 bytes, [src/main/patch/dm_dump.s](../src/main/patch/dm_dump.s)).
Nothing else changes. Boot, interrupt and update paths (agent, RB handler, vectors,
identity block) are untouched.

**Hook flow:**
1. It re-runs the displaced prologue and saves r0–r3, a0 and a1.
2. It accepts only line buffer 0x528E (reply on UART0) or 0x4A45 (reply on UART1), then
   the exact `DMaaaaaa?<CR>` format and the address range. Anything else restores all
   registers and does `jmp.a 0xF4B1C4`.
3. It waits up to about 0x40000 loops for the channel's ISR sender to go idle. If the
   sender is still busy it skips the reply.
4. It sends 73 bytes by polling TI (U0C1/U1C1 bit 1), with a bounded wait per byte.
5. It returns 0x113 through the vendor epilogue.

## 3. Verification (offline)

| Check | Result |
|---|---|
| `tools/main_patch.py` | refuses unless the input is vendor 01.00, the site bytes match and the hook area is erased; the output differs only in the two ranges |
| Simulator, pass-through: [sim/test_dm_patch.py](../sim/test_dm_patch.py), 80 lines × 2 buffers | every token as a query and as a command, plus malformed, lower-case and out-of-range `DM` lines: patched r0 and every non-stack memory write equal to vendor |
| Simulator, DM replies: 4 addresses × 2 channels | 73-byte replies, r0 = 0x113, flash content equal to the image |
| `loader_client.py dmdump` against `sim/fake_unit.py --dm` | 16 KB and 64 KB reads byte-exact |
| Container | `avtool3_pack.py build … --only MAIN --replace MAIN=… --ver MAIN=01.01` builds and verifies |

Limits of the offline checks:
- The simulator has no interrupt or UART0 model and mis-decodes some instructions. It
  executes the vendor and patched code identically, so the pass-through comparison
  stands, but it does not show real-time behaviour.
- The hook blocks the main loop while it sends 73 bytes: about 76 ms at 9600 baud,
  less if the link is faster. The link baud and whether MAIN uses its watchdog are not
  yet established.
- If a `DM` line arrives through the 0x528E path while that path carries a line from
  another source (0xF3DE4E copies such lines in), the reply goes to UART0.

## 4. On-unit validation plan (after the write)

1. Re-run `VI?` and the normal control queries, then the menu and settings check.
2. `dmdump --range 0xF00000:0xF0FFFF`: must equal the patched image (proves the reader
   and transport).
3. `dmdump` (default 0xFFC000–0xFFFFFF): the prize. Run it twice; both sha256 must match.
4. Then the disassembly of the loader: Gate A (can it recover a broken application by
   itself?), the reset path, and the ID code (needed for the last-resort route).

## 5. Delivery (analysed 2026-11-06; facts in loader-interface.md §2.8)

**The vendor updater cannot deliver MAIN alone over LAN:**
- After a successful stage 1 it always runs stage 2 (resource 321), and stage 2 always
  sends `erase webpage` + `update webpage` for DM850W. That breaks hard rule 2.
- In user mode it also re-writes SUB, DSP and DM850I, which breaks hard rule 1.
- "Disable pass." only switches the version checks off; it never narrows the image set.
- A new version number is not needed: the check is plain string equality.
- FWCV is the same engine (update-tools.md §2) with an older UI; not pursued.

| Option | Needs | Writes | Open risk |
|---|---|---|---|
| A. Vendor updater as shipped | Windows | MAIN + DM850W (+ DM850D) | breaks rule 2: **rejected** |
| B. Vendor updater in factory mode, with a MAIN-only container as resource 320 and a 1-byte x86 patch that skips stage 2 (0x404530 `74 6B` → `EB 6B`) | a Windows PC or VM (none set up; this Mac is arm64), and the patched exe | MAIN only | the x86 patch and the resource swap cannot be tested here |
| C. Own writer, `loader_client.py write`: the vendor `L`/`P` sequence, retries and timeouts copied from §2.8, with the `S` sub-0 read-back as verify | macOS only; the fake unit extended with `L`/`P` | MAIN only. Frame whitelist C/S/L/P/A/N, target 1 only, no port 5001 | a transcription error in framing or timing, checked against the decompile and the fake |

**Recommendation: C.**
- It sends the same frames as the vendor tool.
- It runs on the Mac, with the client that already worked on the unit.
- It cannot send DM850 commands or reach SUB, DSP or the CPLDs.
- The full 1,032,192-byte read-back proves the write.
- Version word in `L`: 0x0100, as the vendor sends for this image. The identity string
  at 0xFFBE80 stays "Ver01.00", and the patch is identified by its `DM` reply.

**Status 2026-11-06: C built and simulator-tested, not on the unit.**
`tools/loader_client.py write` implements it: the vendor `L`/`P` sequence transcribed from
loader-interface.md §2.8 (`L` = `AA 4C 01 00 0100 F00000 FFBFFF ck`, ACK ≤ 6 s, 3 retries;
1008 `P` frames of 0x400 B, status 1/2/3, ACK 60 s first/last and 6 s middle, 3 retries
each; FUN_0041d600 / FUN_0041dd60; 5 s wait after the last `P`), then a full `S` sub-0
read-back compared byte-for-byte with the image.

Reviewed against the decompile 2026-11-06 (frames, chunk size, status bytes, timeouts,
retry counts, `E` abort, all 1,008 frames sent). Three corrections made: the `L` timeout
(was the COM path's 10 s), the missing 5 s wait before verify, and the missing `I`
(target information) step. The writer now matches the vendor order `C` → `I` → `L` → `P`:
it sends `I` = `AA 49 01 00000000 00000000 F4` (FUN_0041d3f0), reads the 54-byte reply
(FUN_0041b290), and aborts **before any erase** unless the model code at reply bytes 5-6
equals 0x0011 (AVR-4306; checked by the vendor at FUN_00407C60 0x407d81). A reply with a
bad checksum is rejected, as the vendor does. Where the vendor reads the field is settled
at instruction level (big-endian frame bytes 5-6: FUN_0041b290 0x41b2d5-0x41b30a,
FUN_004081c0 0x408235); a first implementation read bytes 7-8 and was fixed. What this
unit actually sends in that field is unverified until the first session. Guards: image sha256 must be one of the two pinned files (the patch build
or vendor 01.00 rollback) and exactly 0xFC000 B; `--confirm-write` is required and prints
the safety-plan.md checklist until given; target is forced to 1; `L`/`P` builders refuse
any other target; port 5001 is refused. `sim/fake_unit.py` grew the `L`/`P` write side
(erase on `L`, data applied to a mutable image so the read-back reflects it, `--nack` to
exercise retries, `--write-out` to dump what it received). `sim/test_main_write.py` checks
the `L`/`P`/`I` frame bytes against the decompile and drives `write` end to end against the
fake (which now also answers `I` with a settable model code): both images written
byte-exact, the model code is confirmed before `L`, read-back verify passes, retries
recover, update-mode entry works (`--slow`), a wrong model code is refused before any
erase, and the other refusals hold. **Not yet run against the unit** — that needs the
per-write checklist (safety-plan.md); it costs 1 of the 10 MAIN writes.

**Rollback:** the same writer with vendor MAIN 01.00, which is byte-equal to the unit's
flash today (lan-access.md). It costs one more write (2 of 10). The alternative is to
leave the inert patch in place.

**Remaining brick risk** is the same as for any vendor update. A power cut or link loss
after the first data frame (when the erase starts) leaves MAIN without an application.
Recovery then depends on the resident loader still answering `C`/`L`/`P` after
power-up. That is Gate A, unknown until the dump.
- The update agent at 0xF0070C lies inside the erased range.
- Who answered `C`/`S` in update mode on 2026-11-05 is still open
  (loader-interface.md §4 item 6).
- The patch adds no code to the boot or update paths.
