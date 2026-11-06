# MAIN ↔ resident loader interface, and how the vendor tools reach the loaders

Stage 1 of [safety-plan.md](safety-plan.md). Purpose: replace assumptions about the
recovery nets with evidence, and define the **no-touch zone** that no patch may change.
Status 2026-11-05: in progress. Confidence is stated per item.

## 1. MAIN application ↔ resident blocks 0–2 (from MAIN 01.00; 00.76/00.99 same layout)

### 1.1 Handover: loader → application

Corrected from the block 0–2 dump (§5). Reset sets ISP = 0xC3FF and INTB = 0xFFBF00,
then branches on the mode word. Mode 0x0C is the only case that jumps through the
pointer at 0xFFBE7C (0xF0070C in 00.99/01.00). That pointer still addresses the update
agent, not the AV application (§1.4b). Every other mode except 4 jumps to the fixed
address 0xF00000.

### 1.2 Application header block 0xFFBE7C–0xFFBFFF (confirmed layout, meaning inferred)

The top 0x184 bytes of the package range form a contract with the loader:

| Address | Content |
|---|---|
| 0xFFBE7C | 4-byte entry pointer |
| 0xFFBE80 | ASCII identity: `MAIN:SUB::DSP:::::::AVR4306M:Ver00:01:0000:MAIN:Ver01.00:0000:SUB::Ver00.01:0000:DSP::Ver00.01:0000:` … `:BIG-DENON` |
| 0xFFBF00–0xFFBFFF | 64 × 4-byte vector table (application handlers; unused → 0xFFC0BC) |

The identity string carries the MAIN version. It is the likely source for the updater's
"Request information of target" and its same-version skip — **a patched build must
change this string and the AVTOOL3 header version together** (to confirm in the tool).

The 0xFFBF00 table differs from the application's own INTB table (§1.3): about 20
handlers vs 8. Confirmed from the dump (§5): reset does `ldc #0xFFBF00,intb` before
the mode branch. The agent's `ldc #0xFFBD7C,intb` at 0xF007B0 replaces it on the
mode 0x0C path.

### 1.3 Application INTB table (confirmed)

`ldc #0xFFBD7C,intb` at 0xF007B0. Used vectors: 12 → F01806, 13 → F01BB0, 17 → F01748,
18 → F0176A, 19 → F016E2, 20 → F01704 (UART1 RX — the control-protocol RX ISR found in
Phase 1, a consistency check), 35 → F017AE, 36 → F017CA. All others → 0xFFC0BC, a default
handler inside the resident block 2.

### 1.4 Calls from the application into the resident blocks (confirmed sites)

| Target | Sites | Reading |
|---|---|---|
| `jsr.a 0xFFC742` | 12 × 0xF00369–0xF00460 | loader service |
| `jsr.a 0xFFD544` | 0xF00895 | loader service |
| `jsr.a 0xFFC0BE` | 0xF34564, 0xF3459E | loader service (next to the default ISR at 0xFFC0BC) |
| `jmp.a 0xFFC09F` | 0xF00A73, 0xF00A8A, 0xF0102D, 0xF01ACA, 0xF35580 | handover into the loader, no return |

Every `jmp.a 0xFFC09F` site is preceded by `bset 3 / bclr 3 / bclr 1` on SFR 0x0057
(FMR0, flash memory control 0 **[verify SFR name]**): flash reset and exit from
CPU-rewrite mode before the jump. The routine at 0xF00640–0xF006B0 performs the
enter-CPU-rewrite sequence (FMR01 set, FMR02 toggled). So the application drives the
flash controller and uses loader services — evidence of runtime flash writes, most
likely user settings in data-flash block A (no settings EEPROM is fitted on the MAIN
board). **Wear consequence:** block A is rated 100 cycles; how often it is written (each
standby? only on change?) must be established before any wear budget is trusted.

### 1.4a How the application hands over to the loader (decompiled, Ghidra M16C/80)

Ghidra's M16C/80 processor module decodes the M32C/87 image correctly (validated on the
UART1 RX ISR 0xF01704 and dispatcher 0xF4B42E, both matching the Phase 1 emulator
results). All five `jmp.a 0xFFC09F` sites were decompiled:

- **RAM 0x0400 is a mode word** shared with the loader. `set_mode` = 0xF00156 (stores
  the value if < 0x1C), `get_mode` = 0xF00166. Callers of set_mode: 0xF32336, 0xF354CE,
  0xF3557C, 0xF37BA2, 0xF4C41D.
- **0xF008E4** handles loader frames received on UART1 (the rear RS-232 port) and replies
  `A`/`N` on U1TB. Frame byte 3 selects a mode (1→4, 2→5, 3→6, 4→7, 5→8, 8→0x0B, 9→0x0E,
  10→0x0C, 11→0x0D); it ACKs, counts down 100 ticks, resets the flash controller
  (FMR0 bits 3/1) and jumps to 0xFFC09F.
- **0xF01A12** is the same without the UART1 reply (the DM850-link path), with
  6→0x0A and 7→0x09 added.
- **0xF3557C** calls set_mode, then jumps (front-panel/state-machine path in 0xF3512A).
- **The application writes no flash on any of these paths.** The jump is warm (RAM
  survives), which is why the updater can read the parameter RAM afterwards.
- At start-up **0xF4C326** reads the mode word: values 0x18/0x19/0x1A are acted on and
  cleared with set_mode(0); it also checks the parameter area's last word at RAM 0x2700.

What Denon's loader does with each mode value is in blocks 0–2 and still unknown.

### 1.4b The code at the entry pointer is an update agent, not the AV application (decompiled 2026-11-05)

`0xF0070C` (entry pointer at 0xFFBE7C) runs: `0xF007B0` (INTB = 0xFFBD7C), `0xF007B6`
(UART0/1/3 at BRG 0x0F, timers A0/A1), then an endless state machine on RAM 0x2D66. It
never calls the AV application. The 0xFFBF00 table, by contrast, points into the
application (vector 20, UART1 RX → 0xF4BA26, next to the control-protocol dispatcher
0xF4B42E). Reading: Denon's loader enters the application through its own path
(unknown, in blocks 0–2) and enters this agent through 0xFFBE7C. §1.1 therefore
describes the agent's start-up, not the application's.

Agent frame handling (`0xF01038`, parser `0xF013A2` with frame length per type):

| Mode word 0x0400 | Frames acted on | Effect |
|---|---|---|
| ≠ 0x0C | `U` | `0xF00A96`: ACK, then UART baud from byte 3 (1→0x60, 2→0x30, 3→0x20, 4→0x0F) |
| ≠ 0x0C | `X` | `0xF008E4`: byte 3 selects mode 4–0x0E, ACK/NACK, flash reset, `jmp 0xFFC09F` |
| ≠ 0x0C | `RBNORM\r` (parsed when the AA checksum fails) | `0xF00FA0`: sends `RBSTART\r`, mode 0, flash reset, `jmp 0xFFC09F` |
| ≠ 0x0C | anything else | frame flagged (0x3190 bit 4), not answered |
| 0x0C (DM850 relay) | `U`, `X`, `C`, `L`, `P`, `I` | `C` → reply `AA 'C' 0A ck`; `L`/`P` feed the DM850 write path; `I` → 0x36-byte info frame with `OK`/`NG` |

`RBNORM` is therefore a software exit from the agent; the vendor manual still says
power-cycle, and this tool keeps that rule. The agent writes no flash itself; every
path that leaves it resets the flash controller and jumps into the loader.

### 1.5 Free space for patches (confirmed)

One contiguous erased run **0xFA969A–0xFFBD7B (337,634 bytes)**. Everything from
0xFFBD7C up is the INTB table and the header block of §1.2 — not free.

## 2. How the vendor tools reach the units (6.0.0.4 updater; FWCV is the same engine)

Analysis with [tools/pe_xref.py](../tools/pe_xref.py) (string/import cross-references
over the system objdump).

### 2.1 Ports and the two vendor sequences (decompiled, corrected 2026-11-05)

An earlier reading of 0x405D90 was wrong: that code is "Check communication", and
`FUN_0041E8E0` wraps `VI?` (`FUN_0041EA60`), not `RBUPDATE` (`FUN_0041E8B0` →
`FUN_0041E910`). Connect calls (`FUN_0041C8E0(ip, port)`) by site:

| Port | Sites | Use |
|---|---|---|
| 23 | 0x405DE7 | "Check communication" first try: `VI?` |
| 5000 | 0x405E42, 0x407F55, 0x4080CC, 0x408CC2 | control lines (`VI?`, `RBUPDATE`) **and** AA loader frames on the same port |
| 5001 | 0x40615F, 0x40664E, 0x4092BD, 0x409339 | DM850 bootloader channel ("Checking DM800", "Recovering DM800", per-image DM850 loop `FUN_004090A0`) |

**Check communication** (`FUN_00405CB0`): port 23, `VI?` → OK. Only if `VI?` fails:
port 5000, `C(1)` with a 3 s timeout → OK. So `C` is the fallback for a unit that is
already in update mode, not a normal-mode check.

**Update** (`FUN_00407C60`, "Updating start..."), all on port 5000:

1. `FUN_00407EA0`: connect, `VI?`, parse the versions (`FUN_0041ED80`), close.
2. `FUN_00408050`: connect, `RBUPDATE\r`, wait `RBSTART` (3 tries), log "Reboot(Update
   Mode)...", **wait 15 s** (`FUN_00409ED0(0x0F)`, 1 s ticks), close.
3. `FUN_00408170`: connect, `C(1)` with a 6 s timeout and 3 retries (`FUN_0041D270`).
4. `FUN_004081C0`: target information (`FUN_0041D3F0(1, …)`); then the per-image steps.

MAIN's route is `01` (firmware-package.md §5), so the target switch `FUN_00407350`
makes no hop and sends no `X` frame before MAIN is read or written.

FWCV additionally has **`RBNORM\r`**. MAIN's update agent (§1.4b) accepts it.

`RB` is a control-protocol token in MAIN (Phase 1 token table: RB → id 0x1C → internal
0x28). **Update mode is entered by a command that the running MAIN application parses
and acts on.** Consequence for the no-touch zone: UART0 RX path, parser 0xF4B1C0,
dispatcher 0xF4B42E, token table 0xF87C3E, remap 0xF87BE2, switch 0xF4B206 and the RB
handler must stay byte-identical in every patch, or the normal update route is lost.

### 2.2 DM850 loader commands (strings + code sites confirmed; semantics from strings)

`start image`, `start bootloader`, `start tftp client`, `update bootloader`,
`update image`, `update image cne`, `erase image`, `update webpage`, `erase webpage`
(code at 0x41F1CF–0x42016F). `tftp` client set-up at 0x4210B9 (UDP socket, bind to an
ephemeral port, then sendto/recvfrom at 0x421147/0x421189).

### 2.3 Serial path (code exists; same protocol; target still open)

Both tools populate COM1–COM8 and 9600–115200 bps lists and contain a real COM open
(CreateFileA 0x41BCE0, SetCommTimeouts 0x41BD3E, SetCommState 0x41BDA5 in the updater).
The frame senders decompiled in §2.4 write through `WriteFile`/`ReadFile` +
`ClearCommError` (a COM handle); the session-start sender uses the TCP object. So the
serial path speaks the **same AA-framed loader protocol**. Open: whether MAIN's loader
listens on UART1 (rear RS-232) and whether the UI exposes the COM path outside a
factory mode.

### 2.4 µcom loader protocol (port 5000 / COM) — decompiled with Ghidra 12.2

Frames start `0xAA`, then a type letter, then the target ID (1 = MAIN, 2 = SUB,
3 = DSP, 0x0A = DM850, 0x0B = CPLD). Multi-byte fields are **big-endian**. The checksum
is the low byte of the sum of all preceding frame bytes (`FUN_0041AC80`).

| Frame | Layout | Use (decompiled caller) |
|---|---|---|
| `C` | `AA 'C' tgt ck` (4 B) | connect / target information; reply type `C` (`FUN_0041D270`) |
| `S` | `AA 'S' tgt sub start32 end32 ck` (13 B) | **read memory range start..end**; unit streams `D`/`P` frames (`FUN_0041A2C0`) |
| `L` | `AA 'L' tgt sub w16 start32 end32 ck` (15 B) | begin load of an image range (erase/program); start/end are the AVTOOL3 header start/end columns (`FUN_0041A070`) |
| `P` | data frame, payload ≤ 0x400 (≤ 0x100 for tgt 3/4/5/7) | image data to the unit, and read data from it |

Reply frames (`FUN_0041ACA0`): `AA <type> tgt …`, type `A` ACK, `N` NACK, `C` info,
`D` data, `E` error, `P` packet; `D`/`P` carry a 16-bit BE length at bytes 4–5; total
= length + 11.

Uses of `S` found:

- **Verify** (`FUN_00419560`, called from `FUN_004076A0`): `S(tgt, 0, image start,
  image end)`, then the received bytes are compared byte-for-byte with the image file.
  Verify is a **read-back**, not a checksum.
- **Parameter backup** (`FUN_004192D0` via `FUN_00407A60`): `S(1, 0, 0x040C, 0x2701)` —
  MAIN **RAM** 0x040C–0x2701 — saved as `parameter.bin`. Restore (`FUN_00407B90` →
  `FUN_004191D0`) writes 0x22F6 bytes back to the same RAM range. Cross-check: the
  SSManage file `original_AVR-4306.bid` is 8,960 B = 10-byte header `4306EU0099` +
  0x22F6 B — the same parameter block.

~~Consequence: the loader serves reads of caller-chosen ranges.~~ **Tested on the unit
2026-11-05 (lan-access.md): it does not.** MAIN 01.00's update-mode responder ignores
start/end; the sub-byte (byte 3) selects the area:

| Sub | Streams | Size |
|---|---|---|
| 0 | flash 0xF00000–0xFFBFFF (application, blocks 3–20) | 1,032,192 B |
| 1 | RAM 0x0400–0xC3FF | 49,152 B |

So blocks 0–2 cannot be read this way; the read-only patch (safety-plan Stage 3
fallback) is the remaining route. The updater's "parameter backup" with sub 0 and RAM
addresses would also return flash; the working settings read is SSManage's sub 1.

### 2.5 Update sequence (master loop `FUN_00406C50`, up to 20 images)

This is the **RS-232** loop (§2.8). Per enabled image: version check `FUN_00407190`
(skip with "Pass update." when the package version string equals the version reported
for that target; only if "Pass the update of the same version." is set) → target switch
`FUN_00407350` if the processor changes → parameter backup (MAIN) → load image into a
4 MB 0xFF-filled buffer and re-check its byte sum (`FUN_00409AE0`) → write: target 0x0B
goes to the CPLD/VME player only for images named `CPLD`/`CPLDA`/`CPLDL`; all others
`FUN_00419260` = `L` then data → post-step by per-image mode (verify read-back etc.) →
parameter restore.

**VME/CPLD stage (answered):** reached only through an image whose name is CPLD, CPLDA or
CPLDL. No vendor package contains one and avtool3_pack.py can only emit vendor image
names, so it cannot run for our builds.

### 2.6 Session sequence, reply details, exit

From the updater state machine (0x405CB0), `FUN_0041E910`, `FUN_0041EA60` and the vendor
manual (Upgrade Manual 2008-09-12, §3.7–3.9):

1. **Check communication**: `VI?` on port 23; `C` on 5000 only if that fails (§2.1).
   In normal mode `C` on 5000 gets no answer (live unit 2026-11-05).
2. **Request Version**: `VI?\r` on 5000, reply starts `VI`. `VI` is a control-protocol
   token (id 0x1B). This reply is the unit-side version used by the same-version skip.
   Live reply: `VI01:0100;02:0050;03:0004;0A:B200510231011…,I200805270745…;`.
3. **Reboot(Update Mode)**: `RBUPDATE\r` on 5000, expect `RBSTART`, up to 3 tries, then
   15 s wait.
4. Per image: `[01:MAIN] Updating start` → parameter backup (`S` of RAM) → **Erasing**
   (during `L`) → data → verify read-back → parameter restore.
5. **Exit:** the manual tells the user to switch the unit off after "Update completed",
   remove the connection, and switch it on. A failed update is handled the same way:
   power off, check cable, power on, retry. There is no explicit "return to
   application" command on the MAIN side.

Frames on TCP 5000 are raw (`FUN_004203E0` = `send()`), no encapsulation.

Data frame layout (decoder `FUN_0041E760`): `AA type tgt status len16 addr32 payload ck`,
status 0 = only, 1 = first, 2 = middle, 3 = last. After each data frame the PC sends ACK
`AA 'A' tgt ck` (`FUN_00419870`) or NACK `AA 'N' tgt ck` (`FUN_004198C0`).

~~The UI has a "Disable pass." checkbox: it turns off the same-version skip.~~
Corrected in §2.8: "Disable pass." turns off the checks of the LAN loops only, and
DM850W/DM850D are never checked.

### 2.7 Read-only client

[tools/loader_client.py](../tools/loader_client.py) implements only update steps 1–3
plus `S` reads, in the vendor order of §2.1: `version` (`VI?`), `check` (`C`;
answered in update mode only), `read` (`VI?` → `RBUPDATE`/`RBSTART` → 15 s → `C` ×3 →
one `S` per `--range` → ACK per frame), all on port 5000 by default. Default: `--sub 1`,
SSManage's settings read (returns all RAM; settings at 0x040C–0x2701; update-tools.md
§3a). `--sub 0` returns the application flash. Files are named by the addresses
actually received. `--in-update-mode` skips `VI?`/`RBUPDATE` for a unit not yet
power-cycled. Its frame builder refuses anything but C, S, A, N; it refuses port 5001;
`read` needs `--confirm-update-mode`; connections are paced. The fake
([sim/fake_unit.py](../sim/fake_unit.py)) now follows the unit's observed behaviour
(`C` silent in normal mode, `S` range ignored, sub 0/1 areas); against it: normal-mode
`check` NG, settings read and 1 MB application read byte-exact with every 7th data frame
corrupted (NACK/retry). Used on the unit 2026-11-05 (lan-access.md).

The client also has a MAIN-only **`write`** command (Option C, main-dump-patch.md §5),
built 2026-11-06. Read-only `frame()` is unchanged (C/S/A/N only); `write` uses separate
`frame_l`/`frame_p` builders hard-wired to target 1, gated by a two-image sha256 whitelist
and `--confirm-write`. It follows the vendor order `C` → `I` → `L` → `P` of §2.8 (the `I`
model code must be 0x0011 or it aborts before any erase) with a full `S` sub-0 read-back
verify. The fake grew the matching `I`/`L`/`P` write side; `sim/test_main_write.py` checks
the frame bytes and drives `write` end to end against the fake. Used on the unit
2026-11-06 to deliver the DM-dump patch (lan-access.md).

The client is no longer read-only. Beyond `version`/`check`/`read`/`dmdump`/`write` it has
(all simulator-tested, `sim/test_tools.py` / `make sim-toolstest`):
- **`status`** — read-only VI? parsed per processor, plus a normal-mode `C` probe to report
  normal vs update mode.
- **`settings-save`** / **`settings-restore`** — the SSManage flows (update-tools.md §3a).
  Save = `S` sub 1 then slice 0x040C–0x2701; restore = `L` **sub 1** + `D` of the 8,950-byte
  body to parameter **RAM** (not flash, no MAIN wear). Both exit by X(1,2,1)+RBNORM
  (`frame_x_normal`, `RBNORM`), or `--power-cycle-exit`.
- **`verify`** — `S` sub-0 read-back, or the DM dump, compared byte-for-byte to a reference.
- **`rollback`** — `write` restricted to the vendor image.
- A structured per-run log in `dumps/session-log.jsonl`.

`frame()` is still C/S/A/N only; `L`/`P`/`D`/`I`/`X` have their own MAIN-only builders.

### 2.8 Updater control flow and what one run writes (decompiled 2026-11-06)

Ghidra decompile plus disassembly checks of the 6.0.0.4 updater. Dialog control IDs
were mapped to their labels from the dialog resource (dialog 102).

**Start mode** (`FUN_00403560`):
- With a command-line argument `/NN` the tool runs in **user mode**. It reads
  `<exe dir>_NN\UpdateInformation_NN.txt` with the keys `IPAddress`, `Skip` and `Drive`
  (`FUN_0040B170`, `FUN_0040B460`).
- Without an argument it runs in **factory mode**: the title gets `<Factory Mode>`, and
  dialog 102 shows every control.

**Container flags** (`FUN_00404B90`; strings `MW:`, `BP:`, `PV:`, `ON` at 0x448B80,
0x448B7C, 0x448B78, 0x4487C4):

| Flag | When ON, it enables |
|---|---|
| `MW` | the All/Select radio (0x408/0x409) |
| `BP` | "Backup the setting of the product." (0x417 → 0x18C) |
| `PV` | "Pass the update of the same version." (0x41E → 0x190) |

Every vendor container has MW:ON, BP:OFF, PV:OFF.

**Per-image fields** (8-character columns of an image line):
- `t` (column 0x48): load check and post-write step.
- `m` (column 0x50) picks the loop that handles the image:
  - bit 0: RS-232 loop;
  - bit 1: LAN µcom loop;
  - bit 2: LAN DM850 loop.
- Byte 2 of `m` is the DM850 action: 1 bootloader, 2 image, 3 image + cne, 4 webpage.
- Vendor values: MAIN/SUB/DSP m = 3; DM850I 0x00020005; DM850W and DM850D 0x00040004.

**Update button** (`FUN_004044C0`):
- **RS-232:** `FUN_004066B0` → loop `FUN_00406C50` (bit-0 images), one stage. It skips
  same-version images only if "Pass the update…" is set, which needs PV:ON.
- **LAN, stage 1:** `FUN_00407C60` runs on the package loaded at Check communication
  (resource 320: `FUN_00405CB0` → `FUN_0040C850(0x140)`). It runs the µcom loop
  `FUN_00408310` (bit 1), then the DM850 loop `FUN_004090A0` (bit 2, TCP 5001).
- **LAN, stage 2:** if stage 1 succeeded (0x40452E), `FUN_0040C850(0x141)` loads
  resource 321, re-selects its images and runs `FUN_00407C60` again, without repeating
  `VI?`. **Nothing in the UI stops stage 2.**

**Skip checks on LAN** (`FUN_00408890`, same code as `FUN_00407190`):
- Plain string equality: the package version with the '.' removed is compared with the
  `VI?` field. For DM850 the stamp is compared with `VI?` field 1 or field 2. Higher and
  lower versions are both written.
- **µcom loop:** checked only for images named MAIN, SUB or DSP, and only while
  "Disable pass." (0x42B → 0x194) is clear (0x4083F1, esi = 0).
- **DM850 loop:** checked only for DM850B and DM850I, under the same condition
  (0x40924E, ebp = 0).
- **DM850W and DM850D are never checked.** For each one present, every LAN run sends
  `erase webpage` (`FUN_0041FEE0`) and `update webpage` (`FUN_0041FD90`).
- User mode sets "Disable pass." (`FUN_0040B860`), so a user-mode run writes every image
  in 320 and 321. "Pass the update…" (0x190) affects only the RS-232 loop and the
  `VI?` requirement in `FUN_00408050`.

**What one vendor LAN run writes** on a unit already at 6.0.0.4:

| Mode | Stage 1 (resource 320) | Stage 2 (resource 321) |
|---|---|---|
| Factory mode, defaults | MAIN skipped; **DM850D** written (placeholder page) | SUB, DSP, DM850I skipped; **DM850W** written |
| User mode | **MAIN, DM850D** | **SUB, DSP, DM850I, DM850W** |

**MAIN write frames** (`FUN_00419260` → `FUN_0041A070`, `FUN_0041A7E0`):
- **`L`:** `AA 4C 01 00 vh vl start32 end32 ck`. The version word comes from the header
  ("01.00" → 0x0100). An ACK is expected within 6 s on the TCP path (`FUN_0041D600`;
  the COM path `FUN_0041A070` allows 10 s), with up to 3 retries.
- **Before `L`:** after `C`, the vendor sends `I` = `AA 49 01 00000000 00000000 ck`
  (`FUN_0041D3F0`), expects a 54-byte `I` reply, and checks that bytes 5–6 (model code)
  equal the container's `0011` (`FUN_00407C60`, 0x407D81).
- **After the last `P`:** 5 s wait (`FUN_00409ED0(5)`, 0x40876C) before the post-write step.
- **Data:** then `P` frames of 0x400 bytes (BE address, status 1/2/3, layout as in
  §2.6).
  - For target 1 every frame is sent, erased ones included. All-0xFF middle frames are
    skipped only for targets 3/4/5/0x0B. MAIN takes 1,008 frames.
  - ACK timeouts: first frame 60 s (the tool shows "Erasing…", so the erase happens on
    the first data frame), middle frames 6 s, last frame 60 s. Each frame gets 3 retries.
- **After the write:** MAIN on LAN gets a "Sum" check by default (radio 0x407,
  `FUN_00408E40`). "Verify" (0x406) is the `S` read-back.

## 3. bCoD and AVTOOL3 (solved — see tools)

- AVTOOL3 container: rebuilt byte-for-byte for all 10 vendor containers
  ([tools/avtool3_pack.py](../tools/avtool3_pack.py)). Sum = 32-bit byte sum of the true
  flash bytes; the DSP field uses another checksum (unknown, kept verbatim).
- bCoD header: three zlib CRC-32s — header 0x00–0x6F (0x2C zeroed), body, attribute
  segment ([tools/bcod_sum.py](../tools/bcod_sum.py)); 7/7 vendor images.

## 4. Open (Stage 1 exit gate)

Answered: frame format (§2.4), read command exists (`S`, §2.4), VME stage cannot run
(§2.5), ranges are sent explicitly from the header (§2.4 `L`).

Also answered: exit from update mode = power cycle (§2.6); the application writes no
flash when handing over (§1.4a); the unit-side version for the skip comes from `VI?`
(§2.6); the serial path speaks the same protocol and MAIN serves loader frames on UART1
(§1.4a, 0xF008E4).

1. How MAIN builds the `VI?` reply (identity string at 0xFFBE80 is the candidate; it is
   referenced from 0xF00360 and 0xF003F6, next to the loader-service calls). No longer
   needed for delivery: the skip is equality only and can be bypassed (§2.8).
2. Does Denon's loader erase only the `L` range, or all of blocks 3–20? Still open.
   Mode values and the `S` dispatch are in §5: sub 0/1/2 are sent on without a range
   test; sub 3 requires both ends in 0xF00000–0xFFFFFF.
3. "Recovering DM800" (0x40661D → `FUN_004090A0`): how a dead DM850 is reached.
4. Which control-protocol handler turns ASCII `RBUPDATE` into set_mode + jump (RB is not
   in the 0xF4B206 group; the five set_mode callers are listed in §1.4a).
5. ~~Normal-mode `C` on 5000 unanswered on the live unit.~~ **Answered:** expected. The
   vendor sends `C` only after `RBUPDATE` (update) or after `VI?` has failed (check);
   §2.1. `loader_client.py read` now follows the vendor order.
6. ~~Who answers `C(1)` / `S(1, …)` in update mode.~~ **Answered (§5):** the mode-4
   updater copied to RAM 0xA000. Its frame byte is `C`/`X`/`U`/`I`/`L`/`S`/`E`. The
   update agent does not serve an `S` of MAIN flash. Which application path sets mode
   4 for `RBUPDATE` is still item 4.
7. ~~Whether the DM850 passes `VI?` on 5000 to MAIN in normal mode.~~ **Answered:** yes,
   same reply as on port 23 (live unit 2026-11-05 21:49, lan-access.md).

Tooling: Ghidra 12.2 headless with a locally built macOS arm64 decompiler
([tools/ghidra/](../tools/ghidra/)); pe_xref.py for quick string/import lookups.
`tools/ghidra/SeedLoader.java` is the pre-script that seeds the reset vector and the
five services below before auto-analysis of `build/loader/MAIN_full.bin`.

## 5. Resident loader, from the dump

Read 2026-11-06 from the unit, twice, both sha256 `80ec3239…`
(`dumps/dm-20261106-102403/main_FFC000_FFFFFF.bin`, git-ignored). Analysed as the top
16 KB of `build/loader/MAIN_full.bin` (processor M16C/80:LE:16:default). Addresses
below are instruction addresses in that image. objdump mis-decodes this block
(firmware-package.md §8); the listing used here is Ghidra's.

### 5.1 What reset does before the branch

Reset vector 0xFFFFFC = 0xFFC000. `0xFFC000`:

| Address | Effect |
|---|---|
| 0xFFC000 | `fclr i` |
| 0xFFC002 | R3 = 0. This is the cold-boot marker. The warm entry plants a different value (§5.2). |
| 0xFFC004 | PRCR bit 1, PM0 = 0x80, PM1 = 0, PRCR bit 1 off, PRCR bit 0, CM0 = 4, CM1 = 0x20, MCD = 0x12. Then TCSPR (0x035F): bit 7 cleared, then bits 0, 1, 2, 3 and 7 set. |
| 0xFFC03C | ISP = 0xC3FF (top of RAM) |
| 0xFFC041 | INTB = 0xFFBF00. This loads the header vector table. It does not read the table. |
| 0xFFC046 | `cmp.w #0x4649, R3` / `jeq 0xFFC050`. Cold boot (R3 = 0) falls through. |
| 0xFFC04C | `jsr.a 0xFFD6FA` — port-direction init (P0–P10 and the pull-up bytes). Not a mode input. |
| 0xFFC050 | R0 = mode word at RAM 0x0400 |
| 0xFFC055 | Same `cmp.w #0x4649, R3`. Cold boot falls through. |
| 0xFFC05B | `jsr.a 0xFFD772`, and 0xFFC05F stores R0 back to 0x0400. |

`0xFFD772` is the cold-boot mode source. It calls `0xFFD7C2`, which programs AD0CON2
(0x0394) = 0x01, AD0CON1 (0x0397) = 0x38, AD0CON0 (0x0396) = 3, then 4, then 5, starts
each conversion (ADST, bit 6) and waits for it to clear. 0x01 in AD0CON2 is
sample-and-hold with the analog port left at AN_0–AN_7 (M32C/87 hardware manual,
AD0CON2 bits APS1:APS0). Channel field 3/4/5 is AN_3/AN_4/AN_5, pins P10_3/P10_4/P10_5,
the front-panel key ADCs (hardware.md). The 16-bit results are read from AD03/AD04/AD05
(0x0386/0x0388/0x038A) and masked to 10 bits.

Each sample becomes a code:

| Code | 10-bit sample |
|---|---|
| 0 | 0x000–0x02A |
| 1 | 0x02B–0x080 |
| 2 | 0x081–0x0D4 |
| 3 | 0x0D5–0x127 |
| 4 | 0x128–0x17C |
| 5 | 0x17D–0x1D5 |
| 6 | 0x1D6–0x22B |
| 7 | 0x22C–0x280 |
| 8 | 0x281–0x2D6 |
| 9 | 0x2D7–0x32B |
| 10 | 0x32C–0x380 |
| 11 | 0x381–0x3D5 |
| 0xFF | 0x3D6–0x3FF |

`0xFFD772` walks 5-byte records at 0xFFD8C1. Bytes 1–3 are the three codes; byte 4 is
the mode it returns. A record whose byte 4 is 0 ends the walk and returns 0.

| AN_3 | AN_4 | AN_5 | Mode stored at 0x0400 |
|---|---|---|---|
| 0x00 | 0x00 | 0xFF | 0x02 |
| 0x06 | 0x08 | 0xFF | 0x0F |
| 0x03 | 0x08 | 0xFF | 0x01 |
| 0x03 | 0x06 | 0x03 | 0x03 |
| 0x06 | 0x04 | 0xFF | 0x04 |
| — | — | — | 0x00 (no match) |

Nothing else is an input. The header bytes 0xFFBE7C–0xFFBFFF are not read. No digital
port pin is sampled. CNVSS is not read. There is no timeout: the 12,000-iteration loop
later on is the width of an output pulse.

### 5.2 The branch, and the warm entry

`0xFFC064` compares R0 with 0x0C, then with 4.

| Mode | Where it goes |
|---|---|
| 0x0C | 0xFFC072. P13 (P1 bit 3) driven high, P86 (P8 bit 6, E_RESET) driven low for 12,000 loops of three `nop`s, then high. `jmp.a 0xFFC0BE`. |
| 4 | Same pin pulse, then the same `jmp.a 0xFFC0BE`. 0xFFC06D writes 4 back to 0x0400 first. |
| anything else | `jmp.a 0xF00000` at 0xFFC099. The mode word is left as it is. A `jmp.b` at 0xFFC09D loops on that jump if it were ever returned to. |

`0xFFC0BE` splits the two loader modes:

- Mode 4: `smovf.w` copies R3 = 0x0B0A words (0x1614 bytes), 0xFFC0E4–0xFFD6F7, to RAM
  0xA000, then `jmp.a 0x00A000`. That image is the updater. It is entirely inside
  block 2, which an application erase does not touch.
- Mode 0x0C: `mov.l #0xFFBE7C, A0` / `jmpi.a [A0]`. The pointer on this unit is
  0xF0070C, the update agent. The pointer is not tested.

Warm entry `0xFFC09F` (every `jmp.a 0xFFC09F` from the application, and the updater's
own exit at 0xFFC2B1): interrupts off, R0–R3 and A0/A1 cleared, SB = 0, FB = 0, then
`mov.w #0x4649, R3` and `jmp.w 0xFFC004`. Both compares against 0x4649 are taken, so
port init and `0xFFD772` are skipped and the RAM mode word stands. 0x4649 is the
marker; its bytes are `49 46`.

`0xFFC0BC` is `reit`, the target of every fixed vector except reset.

### 5.3 No check of the application before the jump

There is no checksum, marker test, or entry-pointer test on the way to 0xF00000 or
through 0xFFBE7C. A failed check has no path, because the check is not there.

The mode-4 updater does check the window of an `L` (0xFFC3CE) and of an `S` whose
sub is 3 (0xFFC54A). For `L`, sub 0 requires both ends in 0xF00000–0xFFFFFF, sub 1 in
0x0400–0xC3FF, and sub 2 in 0x0402–0x2701. `S` sub 3 requires both ends in
0xF00000–0xFFFFFF. A window outside its test, or any other `L` sub, sets the step
byte 0x2D67 to 2, and 0xFFC599 sends `N` (0x4E). It stays in the updater. That is a
request check, not a check of the image already in flash. The `I` reply at 0xFFC634
reads the identity string at 0xFFBE80 and packs ASCII hex through `0xFFC742`; it does
not compare a sum.

`S` dispatch at 0xFFC495: sub 0/1/2 go to states 6/7/8 with no range test. Sub 3 is
the test above. That is why the 2026-11-05 `S` with sub 0 and RAM addresses still
streamed the application (lan-access.md).

### 5.4 Entering the updater with no application running

Cold reset always starts at 0xFFC000. It overwrites 0x0400 from the key table before
it branches, so leftover RAM does not matter and the application is not running yet.

The only cold-boot result that enters the updater is the row AN_3 = 6, AN_4 = 4,
AN_5 = 0xFF, which stores mode 4. On a 10-bit scale that is 0x1D6–0x22B on P10_3,
0x128–0x17C on P10_4, and 0x3D6–0x3FF on P10_5 (the idle end of that ladder). The
button names are not in this dump.

There is no timeout, and no single strap, that selects mode 4. A blank application
with any other key state takes `jmp.a 0xF00000`. Erased flash there is `und`, whose
vector is 0xFFC0BC (`reit`). That does not re-enter the updater.

Mode 0xC is not in the cold-boot table. It happens only when the warm entry finds it
already in RAM, and it then depends on the header pointer.

### 5.5 What each mode value in §1.4a and §1.4b does

At 0xFFC064 the loader itself distinguishes three cases. Everything §1.4a plants in
0x0400 before `jmp.a 0xFFC09F` lands in one of them:

| Value | Set by (§1.4a / §1.4b) | Loader |
|---|---|---|
| 4 | frame byte 1; also the cold-boot chord in §5.4 | Updater in RAM (§5.2). |
| 0x0C | frame byte 10. The agent's "DM850 relay" mode (§1.4b). | Jump through 0xFFBE7C into the agent. |
| 5 | frame byte 2 | `jmp.a 0xF00000`, value kept. |
| 6 | frame byte 3 | same |
| 7 | frame byte 4 | same |
| 8 | frame byte 5 | same |
| 9 | frame byte 7 on the DM850-link path | same |
| 0x0A | frame byte 6 on that path | same |
| 0x0B | frame byte 8 | same |
| 0x0D | frame byte 11 | same |
| 0x0E | frame byte 9 | same |
| 0x18, 0x19, 0x1A | not planted by the loader; the application acts on them at 0xF4C326 | If one of these is already in RAM at the warm entry, the loader still jumps to 0xF00000. |

The updater's own `X` exit (0xFFC285) writes a mode and jumps to 0xFFC09F: sub 2 → 5,
sub 3 → 6, sub 0x0A → 0x0C, sub 0x0B → 0x0D. Any other sub leaves the mode word
unchanged and still jumps.

`0xF00000`, where every non-4 non-0x0C value arrives:

1. Mode 0x1B is rewritten to 1 (0xF00004).
2. `0xF04190` stores a flag. Mode 0 is then replaced by `0xF04048` (0xF00020), a
   second copy of the same ADC walk, table at 0xF7D504: (6,4,FF)→0x14, (1,1,FF)→0x18,
   (1,3,FF)→0x19, (1,2,FF)→0x1A, (2,3,FF)→1, else 0. On a cold reset the loader has
   already consumed (6,4,FF) as mode 4, so the application's 0x14 row runs only when
   mode 0 was left in RAM and that chord is held.
3. `0xF4C326`. Modes 1 and 2, and the flag byte 0x54F1 when it is 1, call
   `0xF01D24`. Modes 0x18/0x19/0x1A clear the low two bits of 0x08E3; 0x18 then
   clears the whole byte and 0x19 sets bit 0. All three then `set_mode(0)`.
4. After the init calls and `fset i`, a jump table at 0xF00097 (index = mode − 3,
   clamped to 6 when the index is not 0..11). Each arm returns to 0xF00083 and reads
   the mode again.

| Modes that reach the table | Arm |
|---|---|
| 3 | 0xF000ED |
| 5, 6, 7, 8, 0x0D, 0x0E | 0xF000B9. Toggles bit 0 of 0x547B, then five calls. |
| 0x0B | 0xF000D7. Same toggle, three calls. |
| 0, 1, 2, 9, 0x0A, and every mode ≥ 0x0F (the clamp) | 0xF00103, the long call list. 0x18/0x19/0x1A arrive here as 0, after step 3. |
| 4, 0x0C | 0xF000AF, but the loader does not send these to 0xF00000. |

`jsr.a 0xFFD544` (the application's call at 0xF00895) is not the boot branch. It maps
the mode word onto the byte at 0x2D68: 4→1, 5→2, 6→3, 7→4, 8→5, 9→7, 0x0A→6, 0x0B→8,
0x0C→0x0A, 0x0D→0x0B, 0x0E→9. Mode 0x0F and anything outside 4..0x0E leave 0. The
byte is what the agent puts in an ack frame (0xF011F4) and what it compares against a
received frame (0xF01330, 0xF014C8).

### 5.6 ID code

The seven ID bytes are the bytes at 0xFFFFDF, 0xFFFFE3, 0xFFFFEB, 0xFFFFEF, 0xFFFFF3,
0xFFFFF7, 0xFFFFFB. On this unit each one is 0xFF.

The reset vector is 0xFFC000, stored `00 C0 FF FF` at 0xFFFFFC, so it is not the erased
value that skips the serial programmer's ID check. Every other fixed vector is
0xFFC0BC (`reit`), except the word at 0xFFFFE4 is stored `BC C0 FF 00`: its top byte,
0xFFFFE7, is 0x00. That address is not one of the seven ID bytes. The 24-bit target is
still 0xFFC0BC.
