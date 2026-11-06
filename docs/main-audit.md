# MAIN firmware audit (bugs, fixes, enhancements)

Status 2026-11-06. Target: MAIN M32C application, image `MAIN_01.00.flash.bin` (loaded
at 0xF00000). Purpose: find what is worth batching into the **next** MAIN flash write,
which will also carry the `01.00 → 01.01` version bump (docs/VERSIONS.md), so one of the
remaining write cycles (1 of 10 used) both versions and improves the unit rather than
spending a cycle on the version alone.

Method: Ghidra with the `M16C/80:LE:16:default` language (decodes M32C), `SeedMain.java`
to seed the vector tables, plus the byte-signature and M32C-simulator work already in
`docs/control-protocol.md`. Confirmed = read in the disassembly/decompile. Scoped = the
location is established but the change is not yet specified.

## Coverage

Audited in depth: the serial/network **command ingress and parse path** (the main
remote attack surface) and the **version/identity** storage. Located and scoped, needing
one focused follow-up decompile before any change: the **display/dimmer** path and the
**watchdog/timing**. Not covered: every per-command handler leaf — per
`docs/control-protocol.md` those need per-command live tracing and the boot block, and
are out of scope for this pass.

## 1. Ingress parser is bounded — no overflow (confirmed, security)

The headline result, and a contrast with the DM850 SSDP bug (docs/dm850-audit.md): the
MAIN command parser does **not** have the unbounded-copy class of defect.

Both receive assemblers cap the per-line byte index and saturate it:

| Path | Function | Buffer | Index | Cap |
|---|---|---|---|---|
| Rear RS-232 (UART1) | `FUN_f4ba26` (0xF4BA26) | `0x4A45` | `0x5277` | `if (idx < 0x86) idx++; else idx = 0x86` |
| DM850 link (UART0) | `FUN_f4bbf2` (0xF4BBF2) | `0x528E` | `0x5317` | same, saturates at `0x86` |

The per-line step `FUN_f45eec` (0xF45EEC) then clears `0x87` bytes of the buffer before
the next line. So the line buffers are ~`0x87` (135) bytes and the write index can never
exceed `0x86` (134): a command line longer than that is truncated, not overflowed. The
dispatcher `0xF4B42E` returns id 0 for an unknown token (confirmed in the sim,
`docs/control-protocol.md`), so a malformed command is dropped, not mis-dispatched.

**Consequence:** the path telnet/TCP → DM850 → UART0 → MAIN, and the rear RS-232 port,
cannot be driven into a MAIN buffer overflow the way the DM850 SSDP responder could. No
MAIN parser fix is needed. (This does not clear the DM850's own stack above MAIN; that is
the SSDP work.)

## 2. Version / identity (confirmed location)

MAIN's identity string lives in the block at **0xFFBE80** (application flash, below the
0xFFC000 boot block, so writable):

```
MAIN:SUB::DSP:::::::AVR4306M:Ver00:01:0000:MAIN:Ver01.00:0000:SUB::Ver00.01:0000:DSP::Ver00.01:0000:...:BIG-DENON
```

`Ver01.00` is at **0xFFBEB0**. The block is read by init code at **0xF00360** and
**0xF003F6** (abs24 references; the only two in the image). The SUB/DSP `Ver00.01` here
are template defaults — the real SUB (`00.50`) and DSP (`00.04`) values `VI?` reports come
from those modules at runtime, not this block.

**Bump for p1:** change `Ver01.00 → Ver01.01` at 0xFFBEB0. **Before the write**, decompile
the init parser at 0xF00360 to confirm how the `VI?` MAIN field `0100` is derived from the
block (whether it reads `Ver01.00` or the `Ver00:01` packed field), so the bump actually
changes what `VI?` reports. This is a bounded, one-function follow-up.

## 3. Display on/off/dimming (scoped — the main enhancement)

This is the owner's stated goal (CLAUDE.md). Findings:

- There is **no serial/network dimmer command**: the recovered token table
  (`docs/control-protocol.md`) has no `DIM`/display token. The front-panel dimmer
  (BRIGHT/DIM/DARK and off) is handled **internally** — a front-panel key sets the VFD
  brightness; nothing on RS-232 or the network can set it today.
- The on-screen/front text strings are the OSD table near 0xF87AB0 (surround modes, `RSZ`
  resize, radio genres); these are display *content*, not the brightness control.

Enhancement options (each needs the VFD-driver path located first):

1. **Add a dimmer command** to the control protocol so control-bridge and DeRemote can set
   display brightness and off over TCP/RS-232. Highest value, fits the broader goal of
   richer remote control.
2. **A true display-OFF** state, and **persisting** the dim level across power cycles /
   standby if it currently resets.

**Next step (follow-up decompile):** find the VFD driver and the dimmer state byte by
xref from the front-panel key scan and the OSD write path, then specify the change and an
offline (sim) gate — the same discipline as the DM-dump patch. Until that is done, no
display change is write-ready. This is the one piece that should gate the timing of the
p1 write: ideally p1 = version bump **+** the dimmer enhancement, so the cycle delivers
both.

## 4. Watchdog / timing (open — affects what p1 must include)

Whether MAIN runs the M32C watchdog, and its timeout, is **not yet established**
(flagged in `docs/main-dump-patch.md`). It matters now because the DM-dump patch already
on the unit blocks the main loop for ~76 ms per `DM` reply at 9600 baud. If a
short-timeout watchdog exists, that patch — and any new blocking code — could trip a
reset. Resolve by decompiling the init (watchdog setup) and the main loop; if MAIN does
use a watchdog, the p1 batch should add a refresh inside any long operation.

## 5. Settings reset on write (known, not an app-layer bug)

A MAIN flash write resets user settings to defaults (observed 2026-11-06,
`docs/lan-access.md`): vendor update-agent behaviour, not an application defect. It is
handled by the `settings-save`/`settings-restore` tooling, which must be run after every
MAIN write. Not a target for a code change.

## Recommendation: what to batch into the MAIN p1 write

One write, version-bumped, carrying every change that is gated and ready:

1. **Version bump `01.00 → 01.01`** (§2) — makes a patched unit self-identifying and
   retroactively versions the DM-dump patch already present. Confirm the `VI?` source
   first (§2 follow-up).
2. **Display/dimmer enhancement** (§3) — once the VFD path is decompiled and an offline
   gate exists. This is the reason to do the audit now: batch it with the version bump.
3. **Watchdog refresh** in long operations (§4) — only if §4 shows MAIN uses the watchdog.
4. **Decision on the DM-dump patch:** keep it (it is inert unless a `DM` line arrives) or
   drop it in the same write. The 01.01 image can include or exclude it.

Every item goes through an offline sim gate before the write, as the DM-dump patch did.
Budget: 1 of 10 MAIN writes used, 9 left; this plan spends 1 to deliver the version bump
and the enhancement together.

## Confirmed-safe, no action

- Command dispatcher `0xF4B42E`: unknown token → id 0 (dropped).
- Line buffers `0x4A45` / `0x528E`: index saturates at `0x86`; no overflow (§1).
