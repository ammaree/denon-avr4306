# MAIN control-protocol front-end (UART1)

Where the host serial control protocol enters the MAIN M32C firmware, and how far it
could be traced. Addresses are in MAIN image v01.00 (`MAIN_01.00.flash.bin`, loaded at
0xF00000). Found by byte-signature search over the raw image (the CGEN disassembler
misaligns too often to walk the listing) and confirmed by executing the code in the
M32C simulator through the board shim (emulation.md), which decodes correctly.

## Which UART

UART1 is the RS-232 host-control port (via HIN202 on the FRONT unit;
schematic-notes.md). The MAIN↔SUB link is UART0, so UART1 is the right place for the
host command protocol. The sim models UART1 at the real register block (0x2E8–0x2EF),
so the shim drives the same registers the firmware uses.

## The entry point question

The true reset → startup → `main` entry **cannot be recovered from the package.** The
C-startup (NCRT0) that sets SP/SB/FB and initialises RAM is not in the application
image: the exact `ldc #imm,sp` / `ldc #imm,sb` / `ldc #imm,fb` encodings
(`d5 29/2a/2b` + 3-byte immediate) occur **zero** times in the whole 1008 KB image,
yet `[sb]`/`[fb]`-relative addressing is used throughout. Startup therefore lives in
the absent 16 KB boot block (0xFFC000–0xFFFFFF), the standard Renesas placement, along
with the reset and fixed-vector table. Recovering the real entry needs that block
dumped from the unit (re-plan.md 1b).

What *can* be located is the UART1 receive path and the ring buffers the protocol runs
through — the control-protocol front-end.

## Map

| Address | What | Evidence |
|---|---|---|
| 0xF007DD | **UART1 init** | writes U1MR(0x2E8), U1C0(0x2EC), U1BRG(0x2E9)=0x0F, U1C1(0x2ED), bit-sets U1C1 |
| 0xF009B5+ | UART1 transmit routines | write U1TB(0x2EA); fill TX ring buffer 0x319C |
| ~0xF016F4 | **UART1 transmit ISR** | touches U1TB(0x2EA), ends `reit` at 0xF01703 |
| **0xF01704** | **UART1 receive ISR** | reads U1RB(0x2EE), clears U1C1 error bits, stores byte to RX ring buffer |
| 0xF01242 | **RX dequeue** (parser input primitive) | reads RX control block 0x3196/0x31A0–0x31A6, ring wrap/empty check |
| 0xF013B6 | RX dequeue sibling | same control block |
| **0xF4B42E** | **command dispatcher** | `enter #4`; scans the token table at 0xF87C3E (i*4 stride), returns the matched command id |
| **0xF87C3E** | **command token table** | 4-byte entries `{char token[2]; u16 id}`, ~35 entries, ends ~0xF87CC6 |

### RAM

| Address | Role |
|---|---|
| 0x3196 | RX ring index / count (read 4 bytes by the ISR) |
| 0x31A0 | RX ring **write pointer** (loaded into A0) |
| 0x31A2–0x31A6 | RX ring control block (base/size) |
| 0x319C | TX ring buffer control |

## Receive ISR, instruction level (0xF01704)

```
f01704: pushm r0,r2,a0 ; enter #0x4      ; ISR prologue
f01708: <read U1RB 0x2EE> -> local        ; received byte
f0170d: mov.b -4[fb], r0l                  ; byte in r0l
f0170f: btst 7,-3[fb] ; jeq 0xF01723       ; flag/error check
f01723: <load 0x31A0 -> a0>                ; RX write pointer
f01727: <read 0x3196>                      ; index
f0172b: mov.b -2[fb], [a0]                 ; store byte into ring buffer
        <advance 0x31A0>                   ; pointer++
```

## Live confirmation (shim)

`sh tools/sim.sh rxdemo` seeds the RX write pointer (0x31A0 → scratch 0x3200) and index
(0x3196 → 0) — standing in for the startup the boot block would have run — then enters
the ISR with a byte fed on UART1 RX:

```
MEM[0031a0] <= 00 32     # seed: write pointer = 0x3200
MEM[0002ee] =>P          # U1RB read returns the fed byte 'P' (0x50)
MEM[003200] <= 50        # 'P' stored into the ring buffer
MEM[0031a0] <= 01 32     # write pointer advanced to 0x3201
```

That exercises the real firmware bytes in the simulator and confirms the ISR reads
U1RB, enqueues to the 0x31A0/0x3196 ring buffer, and advances the pointer. Without the
seed the ISR halts at the `[a0]` store because 0x31A0 is 0 — the direct consequence of
the missing startup.

## Command dispatch (0xF4B42E → table 0xF87C3E)

The dispatcher takes a pointer to the received command string (argument at 8[fb]) and
scans the token table at 0xF87C3E. Each table entry is 4 bytes: `token[0] token[1] 00
id`. The scan computes `i*4` (`shl #2`), compares the two token bytes
(0xF87C3E+i*4, 0xF87C3F+i*4) against the command string, and on a match returns the id
byte (0xF87C41+i*4) in r0; an unknown token returns 0. CR (0x0D) marks end of command.

Found by searching the image for clustered Denon command tokens (the table) and then
for references to the table address (the two refs at 0xF4B44B/0xF4B4B1 are both inside
0xF4B42E). The table is distinct from the OSD/display string table just before it
(0xF87AB0, fixed-width padded strings like `THX MODE:RIGHT`, `NIGHT:ON`).

### Token → id

```
PW 01  MV 02  CV 03  MU 04  SI 08  ZM 09  SR 0c  SV 0d  SD 0f  MS 10
PS 11  TF 13  TP 14  TM 15  Z2 0a  Z3 0b  Z4 00  VI 1b  RB 1c  SY 1d
SS 1f  NS 20  IP 21  TX 22  PD 24  RR 25  R1 26  R2 27  R3 28  R4 29
LS 2a  HD 2b  VS 2c  XS 2d
```

(The AVR-4306 serial command set: PW power, MV master volume, CV channel volume,
MU mute, SI source select, ZM/Z2/Z3/Z4 zones, MS surround mode, PS parameters,
TF/TP/TM tuner, SY system, NS net/iPod, etc.)

### Live confirmation (shim)

`sh tools/sim.sh dispdemo <TOK>` builds a `"<TOK>\r"` buffer in RAM, passes its
pointer, calls 0xF4B42E, and prints the returned id:

```
token 'PW' -> command id 0x0001      # reads f87c3e=>'P' f87c3f=>'W' f87c41=>01
token 'MS' -> command id 0x0010
token 'ZM' -> command id 0x0009
token 'VS' -> command id 0x002c
token 'QQ' -> command id 0x0000      # unknown -> no match
```

Each matches the table, run against the real firmware bytes in the simulator.

## What is not yet located

- **The per-command handlers.** The dispatcher returns a command id; the handler each
  id selects (the jump/switch that acts on `PW`, `MV`, … and their arguments) is the
  next layer out, reached by `jsr.w` PC-relative calls that carry no absolute target to
  byte-search. Follow it live by stepping on from 0xF4B42E's return with the id set, or
  dump the boot block and boot the parser in its real context.
- The real program entry (`main`) — in the boot block, as above.
