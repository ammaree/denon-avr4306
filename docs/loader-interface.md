# MAIN ↔ resident loader interface, and how the vendor tools reach the loaders

Stage 1 of [safety-plan.md](safety-plan.md). Purpose: replace assumptions about the
recovery nets with evidence, and define the **no-touch zone** that no patch may change.
Status 2026-11-05: in progress. Confidence is stated per item.

## 1. MAIN application ↔ resident blocks 0–2 (from MAIN 01.00; 00.76/00.99 same layout)

### 1.1 Handover: loader → application (confirmed)

- The application sets no stack or base registers: zero `ldc #imm,isp/sp/sb/fb`
  encodings in the whole image. The resident loader sets them, then jumps to the
  **entry pointer at 0xFFBE7C** (0xF0070C in 00.99/01.00; 0xF006F4 in 00.76).
- The entry begins `fclr i` (interrupts off) and calls the init routines.
- Correction (§1.4b): the code at this entry is MAIN's update agent, not the AV
  application. How the loader starts the application is in blocks 0–2.

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
handlers vs 8. Working hypothesis: the loader installs INTB = 0xFFBF00 (or relays through
it) for normal running, and the application's 0xFFBD7C table is a reduced set used in
its update path. **[verify from the block 0–2 dump]**

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

**Consequence:** the loader serves reads of caller-chosen ranges, including non-flash
(RAM) addresses. `S(1, 0, 0xFFC000, 0xFFFFFF)` in update mode should return blocks 0–2
with **no write** — unless Denon's loader filters that range. This would replace the
custom dump patch (safety-plan Stage 3), the riskiest planned step.

### 2.5 Update sequence (master loop `FUN_00406C50`, up to 20 images)

Per enabled image: version check `FUN_00407190` (skip with "Pass update." when the
package version string equals the version reported for that target) → target switch
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

The UI has a **"Disable pass."** checkbox: it turns off the same-version skip, so a
vendor image of the same version can be re-flashed (simplifies safety-plan Stage 2).

### 2.7 Read-only client

[tools/loader_client.py](../tools/loader_client.py) implements only update steps 1–3
plus a single `S` read, in the vendor order of §2.1: `version` (`VI?`), `check` (`C`;
answered in update mode only), `read` (`VI?` → `RBUPDATE`/`RBSTART` → 15 s → `C` ×3 →
`S(start,end)` → ACK per frame), all on port 5000 by default. Its frame builder refuses
anything but C, S, A, N; it refuses port 5001; `read` needs `--confirm-update-mode`;
connections are paced. Tested against [sim/fake_unit.py](../sim/fake_unit.py) (a local
peer implementing §2.1–2.6, `C` silent in normal mode): normal-mode `check` NG, blocks
0–2 pattern read byte-exact, 32 KB application range byte-exact with every 5th data
frame corrupted (NACK/retry). The fake encodes this document's reading of the protocol;
it does not prove the real loader behaves the same.

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

1. How MAIN builds the `VI?` reply (identity string at 0xFFBE80 is the candidate), so a
   patched build reports a new version and is not skipped.
2. Does Denon's loader erase only the `L` range, or all of blocks 3–20? Does it filter
   `S` ranges? What does it do with each mode value? (Answered by the blocks 0–2 read.)
3. "Recovering DM800" (0x40661D → `FUN_004090A0`): how a dead DM850 is reached.
4. Which control-protocol handler turns ASCII `RBUPDATE` into set_mode + jump (RB is not
   in the 0xF4B206 group; the five set_mode callers are listed in §1.4a).
5. ~~Normal-mode `C` on 5000 unanswered on the live unit.~~ **Answered:** expected. The
   vendor sends `C` only after `RBUPDATE` (update) or after `VI?` has failed (check);
   §2.1. `loader_client.py read` now follows the vendor order.
6. Who answers `C(1)` / `S(1, …)` in update mode: the update agent (§1.4b) ignores frames
   for target 1 except `U`/`X`, so it is probably the loader in blocks 0–2. Settled by
   the first `read`.
7. ~~Whether the DM850 passes `VI?` on 5000 to MAIN in normal mode.~~ **Answered:** yes,
   same reply as on port 23 (live unit 2026-11-05 21:49, lan-access.md).

Tooling: Ghidra 12.2 headless with a locally built macOS arm64 decompiler
([tools/ghidra/](../tools/ghidra/)); pe_xref.py for quick string/import lookups.
