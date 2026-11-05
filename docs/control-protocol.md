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

## Per-command handlers (0xF4B1C0 → … → 0xF02332 for PW)

The command processor at **0xF4B1C0** takes the id and reaches a handler in three more
steps (all confirmed by executing the real bytes in the sim):

1. **id → internal command number**, via the M32C `indexws` jump-table idiom at
   **0xF4B1FD** (`indexws.b -2[fb]` then an indexed load) through a second table at
   **0xF87BE2** (word entries). Example: PW id 0x01 → internal 14; ZM id 0x09 →
   internal 15.
2. **internal number → handler**, via a `cmp.w #N / jeq` switch starting at
   **0xF4B206**. Internal 14 (`cmp.w #14` at 0xF4B208) → `jeq 0xF4B21A` →
   `jsr.a 0xF02332`.
3. **handler** 0xF02332 is the **power (PW) handler**: it reads/writes the power/zone
   state bytes at RAM 0x320B/0x320C/0x320F (`btst 5,0x320C`, …) and calls sub-handlers
   0xF0227A and 0xF03FC8 that drive the actual power control.

The parser is split into command **groups**: the dispatcher (0xF4B42E) is called from
four sites — 0xF45F48, 0xF461A2, 0xF4B1F7, 0xF4B24D — each a sub-processor with its own
`indexws`/switch for a group of commands (power/zone, source, tuner, response queries,
…). The 0xF4B24D path, for queries, selects a response string from the tables at
0xF84E10 (null-terminated, id-prefixed: `iRadio`, `mServer`, `SDEFL`, …).

### Resolve a handler (repro)

The id → handler jump is exercised directly by seeding the id at -2[fb] and running from
0xF4B1FD; the sim then follows the indexed remap and switch to the real target:

```
id 0x01 (PW) -> internal 14 -> jsr.a 0xF02332   # power handler
```

## Full chain

```
UART1 RX ISR 0xF01704  ->  RX ring buffer 0x31A0/0x3196
  ->  dequeue 0xF01242
  ->  command processor 0xF4B1C0  (+ group sub-processors 0xF45F48 / 0xF461A2)
      ->  token->id      dispatcher 0xF4B42E   via table 0xF87C3E
      ->  id->internal   indexws   0xF4B1FD    via table 0xF87BE2
      ->  internal->handler switch 0xF4B206
          ->  handler, e.g. PW = 0xF02332  ->  power state 0x320B/0x320C/0x320F
                                                + sub-handlers 0xF0227A / 0xF03FC8
```

## Full command table (0xF87C3E)

34 commands, PW…XS (id 0x2e onward is the accent/charset table, not commands). `id` is
the token table value; `internal` is the remap via table 0xF87BE2 (indexed by id). The
AVR-4306 serial command set.

| tok | id | internal | meaning |
|---|---|---|---|
| PW | 0x01 | 0x0e | power |
| MV | 0x02 | 0x01 | master volume |
| CV | 0x03 | 0x05 | channel volume |
| MU | 0x04 | 0x0a | mute |
| SI | 0x08 | 0x09 | source select |
| ZM | 0x09 | 0x0f | main zone |
| SR | 0x0c | 0x13 | record source |
| SV | 0x0d | 0x24 | video select |
| SD | 0x0f | 0x141 | digital/analog select |
| MS | 0x10 | 0x07 | surround mode |
| PS | 0x11 | 0x07 | surround parameter |
| TF | 0x13 | 0x17 | tuner frequency |
| TP | 0x14 | 0x19 | tuner preset |
| TM | 0x15 | 0x00 | tuner mode |
| Z2 | 0x0a | 0x21 | zone 2 |
| Z3 | 0x0b | 0x22 | zone 3 |
| Z4 | 0x00 | 0x00 | zone 4 |
| VI | 0x1b | 0x27 | — |
| RB | 0x1c | 0x28 | — |
| SY | 0x1d | 0x00 | system |
| SS | 0x1f | 0x00 | speaker setup |
| NS | 0x20 | 0x00 | net / iPod |
| IP | 0x21 | 0x00 | — |
| TX | 0x22 | 0x00 | — |
| PD | 0x24 | 0x137 | — |
| RR | 0x25 | 0x138 | — |
| R1–R4 | 0x26–0x29 | 0x00 | — |
| LS | 0x2a | 0x13d | — |
| HD | 0x2b | 0x00 | HDMI |
| VS | 0x2c | 0x00 | video select |
| XS | 0x2d | 0x00 | — |

## Dispatch architecture (why there is no flat handler table)

The dispatcher (0xF4B42E) is called from four sites, and they are **nested**, not peers:

- 0xF45F48 compares the id against ids directly (0x1c, 0x25, 0x2b, …) and calls the
  group processor 0xF4B1C0.
- 0xF4B1C0 calls the dispatcher, remaps id→internal (`indexws` at 0xF4B1FD, table
  0xF87BE2), then the switch at 0xF4B206 dispatches internal numbers. Most arms are
  **inline status queries** (`btst` on a state byte, return the bit); internal 14 (PW)
  is the one that calls out — `jsr.a 0xF02332`.
- 0xF461A2 calls the dispatcher, then a shared argument/value helper 0xF4B8FC, then
  0xF463EF.
- 0xF4B24D (inside the 0xF4B1C0 function) handles the query/response path, selecting
  response strings from 0xF84E10.

So a given command is routed through several of these levels depending on its id, its
argument, and runtime state (current zone, mode). The handler is not a single
table-indexed address; it is the leaf of nested id/internal switches. `indexws` + table
0xF87BE2 remaps for one group only — which is why many commands map to internal 0 (not
handled there) or to large values (0x141, 0x137…) that are indices into other
structures, not switch arms.

### What this means for enumeration

A clean, complete token→handler table is **not statically recoverable** from the
package: the leaf handler for most commands depends on the top-level command loop (which
sits in the absent boot block) and on runtime state. The reliable way to get a specific
command's handler is per-command live tracing — seed the full command and the parse
state and run it in the sim, as done for PW (→0xF02332). The token→id and id→internal
tables above are exact; the handler leaf below them is per-command work.

## What is not yet located

- **Most per-command handler leaves** — per the architecture above; obtained by
  per-command live trace or by dumping the boot block so the real command loop runs.
- The real program entry (`main`) — in the boot block, as above.
