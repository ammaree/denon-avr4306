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

### 1.5 Free space for patches (confirmed)

One contiguous erased run **0xFA969A–0xFFBD7B (337,634 bytes)**. Everything from
0xFFBD7C up is the INTB table and the header block of §1.2 — not free.

## 2. How the vendor tools reach the units (6.0.0.4 updater; FWCV is the same engine)

Analysis with [tools/pe_xref.py](../tools/pe_xref.py) (string/import cross-references
over the system objdump).

### 2.1 Entry into update mode (confirmed)

Connection state machine at 0x405D90:

1. TCP connect to the unit, **port 23** (DM850 telnet → control protocol).
2. Send **`RBUPDATE\r`**, expect **`RBSTART`** (function 0x41E8E0); close.
3. TCP connect, **port 5000** (update transfer channel; the port answers on the live
   unit with no banner).
4. First exchange on 5000: 0x41D270(1, 3).

FWCV additionally has **`RBNORM\r`** (back to normal mode).

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

### 2.3 Serial path (code exists; target still open)

Both tools populate COM1–COM8 and 9600–115200 bps lists and contain a real COM open
(CreateFileA 0x41BCE0, SetCommTimeouts 0x41BD3E, SetCommState 0x41BDA5 in the updater).
Open: whether this path reaches MAIN's loader through the rear RS-232 jack (UART1), and
whether the UI exposes it outside a factory mode.

## 3. bCoD and AVTOOL3 (solved — see tools)

- AVTOOL3 container: rebuilt byte-for-byte for all 10 vendor containers
  ([tools/avtool3_pack.py](../tools/avtool3_pack.py)). Sum = 32-bit byte sum of the true
  flash bytes; the DSP field uses another checksum (unknown, kept verbatim).
- bCoD header: three zlib CRC-32s — header 0x00–0x6F (0x2C zeroed), body, attribute
  segment ([tools/bcod_sum.py](../tools/bcod_sum.py)); 7/7 vendor images.

## 4. Open (Stage 1 exit gate)

1. P/L/S/C/D frame format on port 5000; is there a read/verify command that returns
   flash contents (would dump blocks 0–2 with no write)?
2. Same-version skip: where it reads the version (identity string vs header).
3. Does the loader honour partial address ranges, or erase blocks 3–20 wholesale?
4. Serial path target (§2.3).
5. "Recovering DM800" (0x40661D): how a dead DM850 is reached (expected: MAIN drives
   E_MODE/E_RESET; DM850B runs the TFTP client).
6. VME/CPLD stage: where it is triggered, how to guarantee it is skipped.
7. What the application's update path does after `RBUPDATE` up to `jmp 0xFFC09F`, and
   whether the loader can be entered when the application is broken (needs blocks 0–2).

Tooling note: full decompilation would speed items 1–6 (Ghidra 12.2 needs JDK 25 and a
locally built macOS decompiler); targeted disassembly with pe_xref.py works meanwhile.
