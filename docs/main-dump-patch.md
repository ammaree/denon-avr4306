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

## 5. Open before any write (delivery)

- **How it gets to the unit.**
  - The vendor updater's same-version skip compares the package version with `VI?`. A
    patched MAIN must carry another version (01.01) to be written.
  - "Disable pass." must **not** be used: it also re-writes SUB, DSP and DM850, which
    breaks hard rule 1.
  - Resource 320 holds MAIN + DM850D, and 321 holds SUB/DSP/DM850I/DM850W. Whether
    DM850D/W would be re-written depends on how their stamps are compared; `VI?`
    reports no W/D stamp.
  - Options: decompile the skip logic (`FUN_00407190`); or use the FWCV tool, which
    loads an external `.bin`, with a MAIN-only plain container; or our own writer
    (`L`/`P` frames). That decision comes before anything else.
- **Rollback:** vendor MAIN 01.00 with version 01.02 (or the FWCV container), a second
  write. The other choice is to leave the inert patch in place.
- **Remaining brick risk** is the write itself (power loss mid-write), the same as any
  vendor update, plus Gate A, which is unknown until the dump. The patch adds no code to
  boot or update paths.
