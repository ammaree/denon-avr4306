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
remote attack surface), the **version/identity** storage (exact bump byte confirmed), and
the **display/dimmer** path (traced to a 4-level menu parameter; the dim-level state
variable is the one remaining item to pin). Open: the **watchdog/timing**. Not covered:
every per-command handler leaf — per
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

**Bump for p1 (confirmed, exact):** the init parsers `FUN_f00360` (0xF00360) and
`FUN_f003f6` (0xF003F6) read the identity block through the boot-block hex-digit routine
`0xFFC742` and pack ASCII pairs into the version bytes. For MAIN they read block offsets
`+0x33/+0x34` and `+0x36/+0x37` — i.e. `0xFFBEB3-B7`, the `01.00` in `Ver01.00` — giving
version bytes `0x01, 0x00`, which `VI?` renders `0100`. So the bump is one field: change
`0xFFBEB6-B7` from `"00"` to `"01"` (`Ver01.00 → Ver01.01`); `VI?` then reports `0101`. No
other change is needed for the version, and nothing else reads the string by value (the
only two abs24 refs to the block are these parsers).

## 3. Display on/off/dimming — traced (the main enhancement)

This is the owner's stated goal (CLAUDE.md). Traced 2026-11-06.

**The dimmer is a 4-level MAIN menu parameter, not a serial command.** Confirmed facts:

- **No serial/network dimmer command exists.** The protocol spec (control-bridge
  `docs/reference/Denon-AVR-4306-control-protocol-v4.6a.pdf`) has no dimmer/brightness
  command; `SS` is setup-menu navigation, `SY` is remote/panel lock. The recovered token
  table (`docs/control-protocol.md`) likewise has no display token. So adding remote
  dimmer control is **genuinely new functionality**, not exposing something hidden.
- **The dimmer is a System Setup menu item with 4 levels.** The display strings are at
  `0xF80872` and the three below it: `DIMMER:  3` (brightest), `DIMMER:  2`, `DIMMER:  1`,
  `DIMMER:  0` (off/darkest), 16 bytes each, consecutive. The front-panel/remote DIMMER
  key cycles this 0–3 level.
- The level string is selected and copied into the display buffer at `0xF17F6E`
  (→ `FUN_f1b270` at 0xF1B270, a byte-copy). So the menu reads a dim-level variable (0–3),
  indexes these four strings, and shows the line.

**Why this is lower-risk than it first looked:** the full get/set/apply machinery for the
dim level already exists (the menu sets it and the display applies it). The enhancement
hooks a new command into that existing variable and apply path — it does **not** require
writing a VFD driver from scratch.

Enhancement design for p1:

1. **Add a remote dimmer command** (a new token, or a `SY`-group sub-command) whose handler
   writes the existing dim-level variable (0–3) and calls the same apply the menu uses, so
   control-bridge and DeRemote can set brightness and off over TCP/RS-232.
2. **Confirm whether level 0 is a true display-OFF** or only darkest; if there is no true
   off, add it. Check whether the level **persists** across standby/power-cycle and, if
   not, store it with the other settings.

### Dim-level variable (pinned) and what is left

The setup-menu value byte for the dimmer is **`0x0040A6`**. The dimmer line builder
(`0xF17F30`–`0xF17F90`) reads it directly (Ghidra M16C/80 disassembly, confirmed):

```
f17f5e: CMP.B:Q #0x3,0x0040A6     ; reject level > 3
f17f62: JGTU  0xF17F82
f17f66: MOV.B:G 0x0040A6,A0        ; A0 = level (0..3)
f17f6a: SHL.W #0x4,A0              ; level * 16 (string stride)
f17f6c: ADD.L:G #0xF80872,A0        ; A0 = 0xF80872 + level*16  -> "DIMMER: N" string
f17f72: PUSH.L A0 ; PUSH.L #0x414E ; JSR 0xF1B270   ; copy 15 bytes to display buf 0x414E
```

So the mapping is inverted from the printed digit: `0x40A6 = 0` → `DIMMER: 3` (brightest),
`0x40A6 = 3` → `DIMMER: 0` (off). The printed digit is `3 - 0x40A6`.

### Trace result (2026-11-06): 0x40A6 is menu scratch, not the dimmer's own variable

Tracing `0x40A6` further **corrected the earlier read**. `0x40A6` is the setup menu's
**shared staged display value**, not a dimmer global:

- The dimmer display builder is `0xF17F4E`, entry **index 2** in a builder-pointer table at
  `0xF7E035` (`0xF17DB8, 0xF17EB8, 0xF17F4E, 0xF17F92, 0xF17FD6, …`). A second builder table
  sits at `0xF7DFF1`. Dozens of these builders each read `0x40A6`, `SHL #4`, and index their
  own string table (dimmer → `0xF80872`; another → `0xF7EE60`; …) into display buffer `0x414E`.
- Elsewhere (`0xF13650` ff.) the same byte is read with `BTST` as a **bitfield**, and other
  builders compare it against `0x11`, `1`, etc. So `0x40A6` holds whatever the active menu
  item needs — it is a scratch register, reused, **not** the dimmer level in storage.
- The dispatcher that stages `0x40A6` and indexes the builder table is **not reachable by
  value-scan**: nothing references `0xF7E035` as an abs24 or raw immediate, so the table base
  is computed (from a higher menu descriptor). Pinning the staging statically means tracing
  the System Setup menu engine from the `SS` entry down — a long manual trace, not a quick one.

So `0x40A6` is **not** a byte a command can poke to set brightness; it only reflects the
on-screen value while the dimmer item is open.

### Persistent dimmer byte: MAIN RAM 0x08A9 (pinned on the unit, 2026-11-06)

Pinned empirically, read-only (the proven update-mode `settings-save` session, no flash): two
`0x040C–0x2701` captures with only the front-panel dimmer changed between them
(`dumps/dim-bright.bin` sha `fa20a9f4…`, `dumps/dim-dark.bin` sha `e3b4500a…`). Exactly three
bytes differed:

| RAM | brightest | darkest/off | meaning |
|---|---|---|---|
| **`0x08A9`** | `0x03` | `0x00` | **the dimmer level** (3 = brightest … 0 = off) |
| `0x18FF` | `0x5B` (91) | `0x58` (88) | checksum, tracked the −3 |
| `0x2701` | `0x7C` (124) | `0x79` (121) | block checksum (last byte of the range), tracked the −3 |

So the persistent level is **`0x08A9`**, value = the displayed digit (`3` bright … `0` off),
which also explains the inversion in §3: the menu getter stages `0x40A6 = 3 − [0x08A9]` to
index the `DIMMER:N` strings. The two checksum bytes (`0x18FF`, `0x2701`) move with it, so any
writer of `0x08A9` must keep them consistent — the firmware's own setter does this, and
`settings-restore` writes whatever checksums are in the image, so going through the firmware
setter (not a raw poke) is the safe path.

### Still open: the VFD apply

The one remaining piece is the **apply** — the function the menu's confirm/front-panel DIMMER
path calls to push the new brightness to the VFD live (setting `0x08A9` alone changes the
stored value, not the panel until applied). Pin it by tracing the DIMMER key handler to the
display-controller write, or by watching what the firmware touches when the level changes.
A remote dimmer command then: set `0x08A9` (via the firmware setter, so checksums stay right)
and call the apply.

**Implication for the enhancement:** the remote dimmer command is **not** a trivial poke — the
level lives in the menu engine, reached through staging and an apply that are not yet pinned.
The version bump (§2) is the sure, low-cost content for the p1 write; the dimmer command is a
larger follow-on, unblocked by the read-only settings-RAM diff above (one short unit session)
plus the apply trace, each then gated offline before it joins a MAIN write.

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
2. **Remote dimmer command** (§3) — a larger follow-on, not a quick add. The level lives in
   the setup-menu engine (the `0x40A6` scratch only mirrors it on screen); the command must
   set the persistent byte in `0x040C–0x2701` and call the VFD apply, neither of which is
   pinned yet. Unblock with the read-only settings-RAM diff on the unit (§3) plus the apply
   trace, gate it offline, then it can join a MAIN write. Do **not** hold the version bump
   for it — ship §1 as its own p1 content if the dimmer work is not ready.
3. **Watchdog refresh** in long operations (§4) — only if §4 shows MAIN uses the watchdog.
4. **Decision on the DM-dump patch:** keep it (it is inert unless a `DM` line arrives) or
   drop it in the same write. The 01.01 image can include or exclude it.

Every item goes through an offline sim gate before the write, as the DM-dump patch did.
Budget: 1 of 10 MAIN writes used, 9 left; this plan spends 1 to deliver the version bump
and the enhancement together.

## Confirmed-safe, no action

- Command dispatcher `0xF4B42E`: unknown token → id 0 (dropped).
- Line buffers `0x4A45` / `0x528E`: index saturates at `0x86`; no overflow (§1).
