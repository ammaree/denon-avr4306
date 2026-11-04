# AVR-4306 firmware package analysis

Source: the three Windows updaters `AVR-4306_Up(grade|date)_6_0_0_{2,3,4}.exe`.
Tools: [tools/pe_map.py](../tools/pe_map.py), [tools/avtool3_split.py](../tools/avtool3_split.py).
Reference hashes: [ref/sha256.txt](../ref/sha256.txt). The images themselves are not in
this repo.

## 1. Updater executable

32-bit Windows PE, 9,428,992 bytes in every version, identical code (`.text`, `.rdata`,
`.data` match byte for byte); only the resource section differs. Imports `WS2_32`,
`iphlpapi` (Ethernet transfer). PE build timestamps: 6.0.0.2 2006-08-03, 6.0.0.3
2008-06-04, 6.0.0.4 2008-09-17.

The firmware is carried as three resources of type `BINARY`, language 1041 (Japanese):

| Resource | Size | Contents |
|---|---|---|
| 320 | 1,046,048 | MAIN µcom image + DM850D |
| 321 | 5,077,856 | SUB µcom + DSP + DM850I + DM850W |
| 351 | 2,104,704 | DM850IMG 11.22 (identical in all three versions) |

Dialog, bitmap and string resources are the tool's UI. No overlay after the sections.

## 2. Container: "AVTOOL3 B007"

Each resource is a text header followed by the payloads back to back.

```
AVR4306       \r\n
AVTOOL3 B007  \r\n
0001    AMP     0011    AVR4306 00.01   <pkgsum> <n> 00000007 00000004 00000003 \r\n
<id>    <name>  <ver>   <sum>   <start> <end>   <end>   <flash>  00000004 <t> <m> 00000000 <route> [<stamp>]\r\n
... one line per image ...
MW:ON  \r\n  BP:OFF \r\n  PV:OFF \r\n  (two blank lines)  HEADER END    \r\n
<payload 1><payload 2>...
```

Fields are 8-character fixed-width ASCII. Confirmed meanings:

| Field | Meaning | Evidence |
|---|---|---|
| id | image number: 01 MAIN, 02 SUB, 03 DSP, 0A DM850 | names |
| ver | image version | MAIN 00.99 → 01.00 in 6.0.0.4 |
| sum | 32-bit sum of the bytes of the image **after XOR 0xFF** | matches all 9 images; package sum = sum of image sums |
| start, end | flash address range written | sizes equal payload lengths exactly, no remainder |
| flash | total flash size of that device | 0x100000 MAIN, 0x40000 SUB, 0x200000 DSP, 0x400000 DM850 — match the parts |
| route | processors the image passes through: `01`, `0102`, `010203`, `010A` | see §5 |
| stamp | DM850 build stamp `I|W|D` + YYYYMMDDhhmm | matches the stamp inside the image |
| t, m | unknown; t = 1 (MAIN/SUB), 2 (DSP), 6 (DM850); m = 3, 00020005 (DM850 code), 00040004 (DM850 web) | |
| MW/BP/PV | unknown flags | |

**Every payload in the 6.0.0.x updaters is stored bit-inverted (XOR 0xFF).** After
inversion the erased-flash regions read 0xFF, the DM850 headers and web pages read as
plain ASCII, and the DM850 code disassembles as ARM. The older FWCV recovery package
uses the same container with **plain** payloads (checksum over raw bytes) — see
[update-tools.md](update-tools.md).

## 3. Images

| Image | Version | Flash range | Payload | Used (after inversion) | Processor / format |
|---|---|---|---|---|---|
| MAIN | 00.99 (6.0.0.2/3), 01.00 (6.0.0.4) | 0xF00000–0xFFBFFF | 1,032,192 | up to 0xFA969A (~694 KB), rest erased | Renesas M32C/87 (M30879FLFP) internal flash. Top 16 KB 0xFFC000–0xFFFFFF (fixed vectors, reset) **not in the package** |
| SUB | 00.50 | 0x0C0000–0x0FDFFF | 253,952 | up to 0xE2438 (~137 KB), rest erased | Renesas M16C/62P (M30624FGPGP) internal flash. Top 8 KB 0xFE000–0xFFFFF **not in the package** |
| DSP | 00.04 | 0x008000–0x1FFFFF | 2,064,384 | code from 0x010000, last data 0x11FC0B, several erased gaps | ADSP-21366 boot image in LH28F160 flash. First 32 KB (0x0–0x7FFF, boot kernel) **not in the package** |
| DM850I | stamp I200608010743 / I200805270745 | 0x000000–0x20C3FF | 2,147,328 | all | BridgeCo DM850 ARM firmware, "EmbededDMP_Denon_Release" |
| DM850W | stamp W200608010743 / W200805270745 | 0x000000–0x0953FF | 611,328 | all | Web UI pages container "DenonAVR4306_Webpages" |
| DM850D | stamp W200605310440 | 0x000000–0x0033FF | 13,312 | 504 bytes | Same container, single `/index.htm` placeholder page |
| DM850IMG | 11.22, stamp 20060207042633 | 0x000000–0x201BFF | 2,104,320 | all | Older full DM850 firmware; only in resource 351, unchanged across versions — probably the recovery/base image |

### 3.1 MAIN — M32C/87

- Address range and flash size match the M30879FL (1 MB flash at 0xF00000–0xFFFFFF).
- Inverted image contains many tables of 4-byte little-endian pointers whose values lie in
  0xF0D58E–0xF3Cxxx (code area), e.g. 39 entries at 0xF7D6AC, 62 at 0xF7D7F3, 295 at
  0xF7DBB1, 104 at 0xF83228. 24-bit addresses in 32-bit slots is the M32C convention.
- No pointer tables appear in the raw (non-inverted) data, which is what showed the
  inversion.
- **Confirmed M32C by disassembly** (GNU binutils 2.43 `m32c-elf-objdump -m m32c`,
  see §8): functions open with `enter #n` (EC) and close with `exitd` (FC) / `rts` (DF)
  + `nop` (DE); 16,503 of 16,890 `jsr`/`jmp` targets fall inside 0xF00000–0xFFFFFF.
  Signature counts over the code area: 684 × `FC EC` (exitd;enter), 676 × `FC DE EC`,
  219 × `DF DE EC`; only 4 × M16C `7C F2`. Code occupies 0xF00000–0xFA969A; the rest is
  erased flash.
- 00.99 → 01.00: 307,737 of 1,032,192 bytes differ, from offset 58 onward: a full rebuild,
  not a patch.

### 3.2 SUB — M16C/62P

- Address range and flash size match the M30624FG (256 KB flash at 0xC0000–0xFFFFF).
- **Confirmed M16C by disassembly** (`m32c-elf-objdump -m m16c`): the image starts
  `enter #1; mov.b:z #0,-1[fb]; … cmp.b:s #3,-1[fb]; jgeu; shl.w; inc.b; jmp.b` — a
  loop with FB-relative locals — and the code area holds 564 × `7C F2` (enter),
  676 × `7D F2` (exitd), 251 × `7D F2 7C F2`, and no M32C `FC DE EC` / `DF DE EC`
  sequences. `jsr`/`jmp` targets stay inside 0xC0000–0xFFFFF (4,358 of 4,685). Code
  occupies 0xC0000–0xE2438.
- Pointer tables of 4-byte entries with 20-bit values 0x0C37xx–0x0DAFxx (code area).
- Table at 0xE15E8: `0C0000 0CFFFF 0D0000 0DFFFF 0E0000 0EFFFF ...` — flash block
  boundaries, i.e. SUB contains flash-programming code.
- Table of 60 entries at 0xFDF00, all `0x0FE110` — points **into the excluded top 8 KB**.
  The interrupt vectors of the application appear to be owned by the resident boot
  block, which dispatches to the application.
- Unchanged across the three releases.

### 3.3 DSP — ADSP-21366

- Inverted image: 0xFF (erased) from flash 0x8000 to 0xFFFF except a 2-byte `00 04` at
  0x8000; code/data from 0x10000.
- Clear 6-byte (48-bit) word structure: a 12-byte repeating pair at inverted offset
  0x80FC — `00 A0 02 00 3E 01` / `7D 00 09 00 00 06` with the fifth byte stepping
  7D, 86, 8A, 9E, A1 — and the lag-12 byte-equality is the highest of lags 4/6/8/12.
  48-bit words are the SHARC instruction width; byte order within the word, and the
  boot-stream block headers (32-bit), still need the ADSP-2136x loader format to
  confirm.
- 60 % of the body is zero and 10 % erased — sparse, as expected for a loader stream
  with zero-fill blocks.
- Unchanged across the three releases.

### 3.4 DM850I / DM850IMG — BridgeCo DM850, ARM

Strings in the inverted image:

- `BridgeCo AG, Switzerland`, `Copyright 2000-2005 by BridgeCo AG, Duebendorf`,
  chip list `DM830 DM850 DM1000 DM1200 DM1500/DM1800`
- `GCC: (GNU) 3.4.0`, `GNU C 3.4.0 -g` — compiled with GCC 3.4.0 (ARM target)
- `ThreadX/1.0` RTOS; HTTP server banner `KnOS/3.2 bridgeCo-DMP/3.0 DLNADOC/1.00`
- `BridgeCo AG Telnet server`, UPnP MediaRenderer/ContentDirectory, WMA, MP3,
  Shoutcast, Rhapsody, `RSDB` (settings database in flash)
- Register names `armIntSet/Clr/Trg`, `MtxBootSel`, `ptuVersion`

Disassembly of the inverted image at offset 0x88 with `llvm-objdump` (ARM, little
endian) is clean ARM32: `bl`, `mov sp, r0`, `ldm/stm` copy loops, and a `blx`
immediate (ARMv5T or later).

Image header (inverted, 0x88/0x8C bytes, `bCoD` magic, version 1, 14-char build stamp,
name at 0x70): length at 0x38, a 32-bit value at 0x34 = 0x400E0080 in the code images
(load/entry address candidate), checksum-like words at 0x2C and 0x3C.

DM850I 2006 → 2008: 1,649,601 bytes differ — a new build. DM850IMG 11.22 (Feb 2006) is
an older build still, 2,104,320 bytes.

### 3.5 DM850W / DM850D — web pages

Same `bCoD` header, name `DenonAVR4306_Webpages`, then a file table at 0x88 of
`(name_offset, data_offset, length)` 32-bit triples relative to 0x88, then names and
data. DM850W holds the browser UI (`/TopMenu.asp`, `/MainZone_*.asp`, `/NetAudio_*.asp`,
`/SurrPara_*.asp`, `/SysSetMenu.asp`, `/Tuner.asp`, … about 169 files). DM850D is one
`/index.htm` showing "DENON". W 2006 → 2008 differs only in the 10 bytes of the build
stamp.

## 4. What each release changed

| Release | MAIN | SUB | DSP | DM850I | DM850W | DM850D | DM850IMG |
|---|---|---|---|---|---|---|---|
| FWCV VR002 (2006-06) | 00.76 | — | — | — | — | — | "11.22" (2005-11-22 build) |
| 6.0.0.2 (2006-08) | 00.99 | 00.50 | 00.04 | 2006-08-01 | 2006-08-01 | 2006-05-31 | "11.22" (2006-02-07 build) |
| 6.0.0.3 (2008-06) | same | same | same | **2008-05-27** | stamp only | same | same |
| 6.0.0.4 (2008-10) | **01.00** | same | same | same | same | same | same |

So 6.0.0.3 was a network-module fix and 6.0.0.4 a main-µcom fix. The 6.0.0.4 package
is the latest for every component.

## 5. Update route (from the `route` field)

| Image | route | Reading |
|---|---|---|
| MAIN | `01` | written by MAIN itself (CPU rewrite of its own flash; resident loader in 0xFFC000–0xFFFFFF) |
| SUB | `01 02` | MAIN → SUB; SUB rewrites itself (resident loader in 0xFE000–0xFFFFF; vectors point there) |
| DSP | `01 02 03` | MAIN → SUB → DSP flash; SUB drives DSPROMRST / VPP / DSPBOOT (pin table) |
| DM850* | `01 0A` | MAIN → DM850 |

Physically the Ethernet port belongs to the DM850, so the bytes enter there and reach
MAIN over the SPI/UART link (M30879 P94–P97, P62/P63, EREQ, EMODE). The `01` at the
head of every route says MAIN is the controller of the whole procedure.
**To confirm on the schematic:** the DM850–MAIN link, whether DM850 can be reflashed by
MAIN or only by itself, and where the SUB→DSP flash write path runs.

## 6. Region

`original_AVR-4306.bid` starts `4306EU0099`: EU model, and `0099` matches MAIN 00.99.
The updater packages carry one MAIN image for all regions; the µcom reads the
destination from the MODE pin (P100/AN0) at run time. A 220 V unit uses the same
firmware as a 120 V one.

## 7. Open items

1. Full annotation of MAIN (M32C) and SUB (M16C) disassembly.
2. Confirm the DSP boot-stream layout against the ADSP-2136x loader format.
3. Decode the `bCoD` header fully (load address, checksums) and the DM850 memory map.
4. Recover the three resident boot blocks (MAIN top 16 KB, SUB top 8 KB, DSP first
   32 KB) — not in any package; must come from the unit.
5. Transfer protocol between the updater and the unit: strings decoded in update-tools.md; framing still needs the tool's code.

## 8. Toolchain

GNU binutils 2.43 built for `m32c-elf` (M16C and M32C decoders), installed at
`~/.local/opt/binutils-m32c-2.43/bin/`. Build on macOS needed `--with-system-zlib`,
`--disable-werror`, `MAKEINFO=true`. Tarball signature verified against the GNU keyring.

```bash
~/.local/opt/binutils-m32c-2.43/bin/m32c-elf-objdump -D -b binary -m m16c --adjust-vma=0xC0000  SUB.inv.bin
~/.local/opt/binutils-m32c-2.43/bin/m32c-elf-objdump -D -b binary -m m32c --adjust-vma=0xF00000 MAIN.inv.bin
```

Both decoders are CGEN-based and incomplete: 18 % (M16C) / 14 % (M32C) of instructions
print as `*unknown*`, including common ones such as M16C `JSR.A abs20` (FD xx xx xx)
and `PUSH.W #imm16` (7D E2 xx xx). The unknown rate therefore does not discriminate
the two ISAs ([tools/isa_score.sh](../tools/isa_score.sh)); the prologue/epilogue
signatures do ([tools/isa_signatures.py](../tools/isa_signatures.py)). For Phase 1d the
decoder gaps must be filled (Renesas M16C/M32C software manuals) or a different
disassembler used.
