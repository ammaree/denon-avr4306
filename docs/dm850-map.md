# DM850 memory and task map

Status 2026-11-06. Source is `build/images/DM850I_x.flash.bin` (2,147,328 bytes, bCoD,
name `EmbededDMP_Denon_Release`, stamp `20080527074501`). The image is not re-linked;
`tools/ghidra/LoadDm850.java` replays the scatter loader and `NameDm850.java` applies
the names below. Import base is `0x400DFFF4`, processor `ARM:LE:32:v5t`.

## 1. Header and the scatter loader

| Field | Value |
|---|---|
| Magic / version | `bCoD`, version 1 |
| Type | 2 (code) |
| Header length | `0x8C` |
| Load address | `0x400E0080` (file offset `0x8C` is the first instruction) |
| Body | `0x1FFDF4` bytes, from file `0x8C` |
| Entry | `0x400E0080`, ARM. `bl` a stack setup, then `b 0x400E00C8` via the branch at `0x400E00C4` |

`0x400E00C8` is the scatter loader (`__scatterload`). `add r8, pc, #0xC4` puts the
region table at `0x400E0194`, which is file offset `0x1A0`. The four words there are
offsets from `0x400E0194`, not `(flag, src, dst, len)` records:

| Word | Offset | Address |
|---|---|---|
| copy start | `0x15E8C` | `0x400F6020` |
| copy end | `0x15FDC` | `0x400F6170` |
| ZI start | `0x15FDC` | `0x400F6170` |
| ZI end | `0x1604C` | `0x400F61E0` |

Copy records are 12 bytes `(src, dst, len)` and ZI records are 8 bytes `(addr, len)`.
`ldm r8, {r0, r1}` does not write back, so `r8` stays on the header. A record with
length 0, or `src == dst`, is skipped. Bit 0 on an address means "add the table
base"; bit 1 means "add r9". Every live record in this image has those bits clear.

Live copies:

| Source | Destination | Length | Destination end |
|---|---|---|---|
| `0x400F61E0` | `0x60008000` | `0x1DF9D0` | `0x601E79D0` |
| `0x402D5BB0` | `0x00580000` | `0x2D08` | `0x00582D08` |
| `0x402D88B8` | `0x00540000` | `0x14` | `0x00540014` |
| `0x402D88CC` | `0x00400028` | `0x72C` | `0x00400754` |
| `0x402D8FF8` | `0x00410000` | `0x6E7C` | `0x00416E7C` |

The first destination is the SDRAM image. Its first halfword is Thumb (`ldr` from the
literal pool, `bx lr`), so the body is mixed ARM and Thumb. A file offset inside this
copy is at `VA = 0x60008000 + (file_off - 0x161EC)`.

Live ZI, cleared by the loader, not present as bytes:

| Address | Length | End |
|---|---|---|
| `0x70000000` | `0x4800` | `0x70004800` |
| `0x601E79D0` | `0x19A64` | `0x60201434` |
| `0x00540014` | `0xEF0` | `0x00540F04` |
| `0x00416E7C` | `0xCEC` | `0x00417B68` |

The fast region is the code that stays at `0x400E0080` (the reset and the scatter
loader). `0x00400028`, `0x00410000`, `0x00540000` and `0x00580000` are the other
loaded regions; this map does not name the chip blocks. `0x70000000` is only a ZI
range.

## 2. NicheStack pools

`pk_alloc` is `0x60124BA4`. It takes the size in r0.

- The word at `0x00540010` (inside the `0x00540000` region) is an IRQ flag. If it is
  non-zero, `pk_alloc` prints `pk_alloc called in IR context` (`0x601B2A5C`) and
  returns 0.
- Otherwise it compares the size with the struct at `0x601E4FC8`. The request is
  refused, with the `bigbufsiz=%d` text at `0x601B2A7C` (`pk_alloc` string + `0x20`),
  when it is above the word at `+0xC`.

That struct, as stored in the image:

| Offset | Value | Use in `pk_alloc` |
|---|---|---|
| `+0x0` | `0x32` | count |
| `+0x4` | `0xC8` | small-buffer threshold (200) |
| `+0x8` | `0x32` | count |
| `+0xC` | `0x708` | `bigbufsiz` (1800). A larger request returns 0 |

A size at or under `0xC8` is taken from the small pool when its free list is
non-empty; anything else goes through `0x60033740`. The socket-list CLI string is
`display socket list` at `0x601B2916`. The socket array base was not recovered as its
own pointer.

`nptcp.c` is the string at `0x601B115C`. Nothing in the image takes its address.
`tcp_out` (`0x6010CF24`) is the function that prints `tcp_out:mbuf-nbuf`
(`0x601B1118`) when an mbuf offset is below the threshold at `0x601EDAC0`.

## 3. Threads

Three threads are created by the wrapper at `0x6011EA9C` (ARM). r0 is the control
block, r1 the name, r2 the Thumb entry (odd address).

| Name | Creator | Entry |
|---|---|---|
| UPnP Disc Thread | `0x60049650` | `0x6004A788` |
| UPnP TCP Thread | `0x6006F938` | `0x6006FA98` |
| Swap_Spaces_Thread | `0x600459FC` | `0x600459F4` |

The Disc thread's control block is the BSS word `0x601EE220`. Its entry is the
discovery loop that reaches `Disc_Srv_Search_Req`.

Other thread names are loaded by a creator and started through the GTS stub at
`0x600E5A3C` (`blx 0x600A0CFC`). The stub is shared, so the entry is not a separate
address in the image:

| Name (string) | Creator that loads the name |
|---|---|
| NapManagerThread (`0x601AA02C`) | `0x6007B408` |
| NetCfgThread (`0x6019D778`) | `0x6007C7C4` |
| PowerManagerThread (`0x601C2ED4`) | `0x6007CF44` |
| WRCThread (`0x601A8864`) | `0x6007E4CC` |
| GenaThread (`0x601ABB34`) | `0x600806C8` |
| GenaEventThread (`0x601ABB24`) | `0x600827DC` |
| CardeaThread (`0x6019EEE8`) | `0x600824F4` |
| SnapCfgProtocolThread (`0x601B58C0`) | `0x60087F40` |
| NetReconfiguratorThread (`0x6019AE08`) | `0x600F8CC0` |
| LCDDisplayService (`0x60181968`) | `0x6010BB18` |

`SsdpRecUDP` (`0x601C84A4`) is loaded by `0x60104B9C`, the UDP receive setup, next to
the constant `0x1384` (port 5000). `DHCP client: got address %s` is printed from
`0x600D43F4`. `ThreadX/1.0` is the string at `0x601813CC`.

## 4. SSDP / UPnP responder

The format strings are a pointer table at `0x601E5188` (`ssdp:all` at `+0x44`,
`upnp:rootdevice` at `+0x50`, `uuid:` at `+0x5C`, `:device:` at `+0x1C`, `:service:`
at `+0x40`). `urn:` itself is the literal `0x601B50D4`.

`UPnPModuleImpl::receiveData` is `0x601360E0`. It rejects a datagram of 0x200 bytes
or more, copies the datagram onto the stack, then calls, in order:

| Address | Name, from the error text at `0x6019C498` |
|---|---|
| `0x60067050` | `Req_Prs_Translate_Req` |
| `0x6006FCFC` | `UDP_Rec_Check_MSearch_Req` |
| `0x6004A114` | `Disc_Srv_Search_Req` |

`Disc_Srv_Search_Req` is the only caller of the search (the Thumb `bl` at
`0x60136178`). It matches `ssdp:all`, `upnp:rootdevice`, `uuid:`, then `urn:` plus
`:device:` or `:service:`, and hands the type to `0x600496B4`. The type switch is
`0x60049A80`. The service arm (`type 7`) continues at `0x60049B1A` and the reply
copy is `0x60070A5C`. Detail of the fault is in `docs/dm850-audit.md`.

## 5. GoAhead

`GoAhead-Webs` is `0x601AA6C4`. The server sources are
`system\WebserverGoAHead\webs.c` (`0x601AAE38`) and `ringq.c` (`0x601C8238`).
The listen failure text is `Couldn't open a socket on ports %d - %d` at `0x601AAE94`.
Page handlers are the `.asp` names in the same region (`default.asp` at `0x6018AF54`,
`SurrPara_1.asp` through `SurrPara_5.asp` at `0x601979F4`).

## 6. MAIN link (UART0)

`/dev/uart0` is `0x6019A4B4` (also `0x6019A6D8` and `0x601B6F54`). `denonProtocol` is
the string at `0x6019A4D8`. `LCDDisplay.cpp` is referenced from `0x6000947C`, in the
constructor at `0x6000939A` (`LCDDisplay constructor: failed to create LCD Buffer Bitmap!`).

The send used by the parameter commands is the ARM function `0x6004DA20`. Display
dimming is `set_dim_psdim` at `0x60063BA4`:

- It matches the argument against seven packed strings at `0x601E1FF8`.
- The tokens are `0`..`6`. The value sent for each is `00`..`06`.
- It `sprintf`s (`0x60011284`) `PSDIM %s\r` (`0x6018A594`) into a 0x20-byte stack
  buffer and passes that line to `0x6004DA20`.

The query form `PSDIM ?\r` is the record at `0x6018805C` in the parameter-query
table, with flag word `0x1000`. The power logs `*****PWON*****` and
`*****PWSTANDBY*****` are at `0x601868EC` and `0x601868FC`, next to the tokens
`on` and `off`.
