# DM850 audit

Status 2026-11-06. Disassembly of `build/images/DM850I_x.flash.bin` after the scatter
map in `docs/dm850-map.md`. Addresses are runtime VAs in the SDRAM copy. Confirmed
means the instruction sequence was read. Suspected means the pattern is there and the
faulting instruction was not.

Nothing here is written to the unit. The patched file produced by
`tools/dm850/apply_ssdp_guard.py` stays in `build/patch/`.

## 1. Confirmed: SSDP service search with no version colon

`docs/lan-hang.md`: one M-SEARCH whose `ST` is `urn:Belkin:service:basicevent` kills
the DM850 within about four seconds. `ssdp:all`, `upnp:rootdevice`, DIAL
(`urn:dial-multiscreen-org:service:dial:1`) and ContentDirectory
(`urn:schemas-upnp-org:service:ContentDirectory:1`) do not. The bytes `Belkin` and
`basicevent` are not in the image. The difference that the instructions actually
test is the colon after the service name.

`UPnPModuleImpl_receiveData` (`0x601360E0`) copies the datagram and calls
`Disc_Srv_Search_Req` (`0x6004A114`). That function matches `urn:` (4 bytes at
`0x601B50D4`) and then `:service:` (the table slot at `0x601E5188+0x40`). Belkin,
DIAL and ContentDirectory all match, and all three are type 7.

The type switch `0x60049A80` is a byte table at `0x60049A98`. Type 7 lands at
`0x60049B1A`. From there, with r4 pointing at the text after `urn:`
(`Belkin:service:basicevent`):

1. `strstr` (`0x600123A4`) for `:` finds the colon after the domain. r6 becomes that
   address plus 9, which is the service name (`basicevent`). The 9 is the length of
   `:service:`.
2. `strstr` for `:` is called again, on the service name (`0x60049B32`).
3. The next instruction, `subs r0, r0, r6` at `0x60049B36`, subtracts with no test
   of r0.

`strstr` returns 0 when it reaches the NUL before the needle
(`add r0, r2` with r2 already 0, at `0x600123C2`). `dial:1` and `ContentDirectory:1`
have a colon, so r0 is that colon and the length is 4 or 16. `basicevent` has no
colon, so r0 is 0 and `subs` computes `0 - r6`. The following `lsls`/`lsrs` keep the
low 16 bits. That halfword is the length passed to `urn_service_reply` (`0x60070A5C`).

`urn_service_reply` does `sub sp, #0x64` and then `memcpy` (`blx 0x60011C90` at
`0x60070A7E`) of that length from the service name into `sp+4`. The comparison just
above it (`cmp r6, r0` at `0x60070A76`) checks a different argument, the caller's
length plus one, against a table count. It does not check this length against
`0x64`.

The length is the low 16 bits of the negation of the name pointer. For a pointer in
the SDRAM stack that is not in the last `0x60` bytes of its 64K page, the copy is
larger than the frame. The return address and whatever follows the frame are
overwritten, and the network thread does not come back (no ARP, no ping). That is
the unbounded copy.

## 2. Confirmed: the same subtract on a device URN

Type 5 of the same switch (`0x60049AB4`) does the same pair of `strstr` calls for a
`urn:DOMAIN:device:NAME` value, adding 8 (`:device:`) instead of 9. The second
`subs r0, r0, r6` is at `0x60049AD0`, again with no test of r0.
`urn_device_reply` (`0x60070974`) does `sub sp, #0x5C` and `memcpy`s that length at
`0x60070998`. A device ST with no colon after the name takes this path. The Belkin
ST matches `:service:`, so it does not.

## 3. Suspected: NicheStack before 4.3

The image is the 2006-07-28 BridgeCo NicheStack (`nptcp.c` at `0x601B115C`,
`osporttx.armc` in the path at `0x6019AC90`). `docs/dm850-firmware.md` records that
every NicheStack before 4.3 is in the INFRA:HALT set. The functions below are the
ones the strings identify. The reassembly, DHCP, DNS and ICMP faults were not
separated out of them.

| Area | What was read | Condition that would reach it |
|---|---|---|
| TCP output | `tcp_out` at `0x6010CF24`. The copies at `0x6010CF50` and `0x6010CFB8` use an mbuf length that has just been compared (`cmp r2, #0xA`, then `cmp r2, r0`). `tcp_out:mbuf-nbuf` is printed when the offset is below the word at `0x601EDAC0`. | A TCP segment whose mbuf offset fails that comparison. The copy itself is bounded in the instructions read. |
| DHCP | `dhcp_client_log` at `0x600D43F4` prints `DHCP client: got address %s` (`0x601CD5D8`). | A DHCP offer the client accepts. The option-length walk was not found. |
| DNS | `DNS timeout` (`0x601CD89C`) and `DNS error %d` (`0x601CD8A8`) have no pointer and no Thumb literal. | A DNS reply, path not located. |
| ICMP | The string `ICMP` at `0x601B1F23` has one word reference and no Thumb literal. | An ICMP datagram, receive function not located. |
| Allocator | `pk_alloc` (`0x60124BA4`) refuses a size above `bigbufsiz` (`0x708` at `0x601E4FD4`) and refuses a call when the word at `0x00540010` is set. | Not a missing check. Recorded so it is not re-read as one. |

## 4. Patch: ignore a service name with no colon

Do not flash this. The DM850 has no recovery path if a write fails, and the vendor
update rewrites the web pages with the code (`docs/loader-interface.md`).

Located change, Thumb, in the service arm:

| | |
|---|---|
| Site | `0x60049B36`, file offset `0x57D22` |
| Was | `subs r0, r0, r6` / `lsls r7, r0, #16` (`80 1b 07 04`) |
| Now | `bl 0x601CE800` |
| Cave | `0x601CE800`, file offset `0x1DC9EC` |

The cave is inside the zero run `0x601CE424`–`0x601CF090`. No pointer in the SDRAM
image lands in that run. `tools/dm850/ssdp_guard.S` is the source. The apply script
assembles it with `arm-none-eabi-gcc -mthumb -march=armv5t` when that compiler is on
`PATH`, and otherwise with `clang -target arm-none-eabi`. It checks the site bytes
and the zero run, writes `build/patch/DM850I_ssdp.flash.bin`, and recomputes the
three bCoD CRCs with `tools/bcod_sum.py`.

On r0 == 0 the cave branches to `0x60049B76` (`movs r0, #0`, then the epilogue).
`disc_srv_schedule` (`0x600496D6`) returns immediately when that result is 0, so
`urn_service_reply` is not called. `dial:1` and `ContentDirectory:1` still take the
original subtract and shift, and still get a reply. The device arm in §2 is not
patched.

Offline gate, before any flash: `python3 -I tools/dm850/test_ssdp_guard.py` executes
the assembled cave. A zero search result must branch to `0x60049B77`. A non-zero
result must leave `r0 = r0 - r6` and `r7 = r0 << 16` and return to `0x60049B3A`.
The same run checks the patched image's site, cave bytes and CRCs, and that the
vendor image is unchanged.

### Replay gate (built, passing)

`tools/dm850/replay_ssdp.py` runs the real responder under Unicorn and is the
replay gate. It reconstructs both images with `tools/dm850/dm850_mem.py` (the same
scatter replay as `LoadDm850.java`), enters the type switch (`0x60049A80`) with
`r0` = URN type and `r1` = the text after `urn:` exactly as `Disc_Srv_Search_Req`
calls it, and runs the real service arm and `urn_service_reply` up to the copy.
`strstr` and `memcpy` are stubbed in Python, so nothing outside the arm executes
and no oversized write actually runs; the length the responder would hand `memcpy`
is what is measured. It needs Unicorn, so it runs from the project venv:

    python3 -m venv build/venv
    build/venv/bin/pip install unicorn==2.1.4 capstone==5.0.7
    build/venv/bin/python tools/dm850/replay_ssdp.py

Measured, and asserted by the script:

| Image | ST | Result |
|---|---|---|
| vendor | `urn:Belkin:service:basicevent` | reply reached, copy length **65521** into the `0x64` frame |
| vendor | `urn:…:service:dial:1` | reply reached, length 4 |
| vendor | `urn:…:service:ContentDirectory:1` | reply reached, length 16 |
| patched | `urn:Belkin:service:basicevent` | **no reply**, type switch returns 0 |
| patched | `urn:…:service:dial:1` | reply reached, length 4 |
| patched | `urn:…:service:ContentDirectory:1` | reply reached, length 16 |

The vendor Belkin length (65521) is the low 16 bits of the negated service-name
pointer, confirming §1: a copy far larger than the frame. The patched image drops
exactly that one case and leaves the two legitimate searches answering with the
same lengths. The gate is meaningful: on an unpatched image the patched-Belkin
assertion fails, because Belkin reaches the reply.

The device arm (§2) is **not** patched. The same harness, driving type 5 with
`urn:schemas-upnp-org:device:MediaServer`, still reaches `urn_device_reply` with a
length over its `0x5C` frame on both images. That is recorded, not fixed; the §5
device-arm proposal would need the same guard.

## 5. Proposed, not applied

### Display on/off/dimming

Dim is already a MAIN command. `set_dim_psdim` (`0x60063BA4`) maps `0`..`6` to
`PSDIM 00`..`PSDIM 06` and sends the line through `denon_link_send` (`0x6004DA20`)
on `/dev/uart0`. The query is `PSDIM ?\r` at `0x6018805C`. Power on/off is the pair
of logs at `0x601868EC` / `0x601868FC` next to the tokens `on` and `off`; the
function that builds that line was not separated from the shared send.

A change to dimming is a change to which token `set_dim_psdim` is called with, or a
new caller of `0x6004DA20` with a `PSDIM` line. LCD text itself is the constructor
at `0x6000939A` (`LCDDisplay.cpp`). The offline gate is the same shape as §4: run
`set_dim_psdim` under Unicorn with each token `0`..`6` and a stub for `0x6004DA20`,
and require the buffer to be `PSDIM 00\r` through `PSDIM 06\r` and nothing for any
other argument.

### Network hardening

From §1 and §3, in order, none of it applied:

- The same zero-test in the device arm at `0x60049AD0`, so a `urn:…:device:` value
  with no version colon takes the ignore path instead of `urn_device_reply`.
- Drop an M-SEARCH in `UDP_Rec_Check_MSearch_Req` (`0x6006FCFC`) when the ST length
  is past the size of the reply frame (`0x64`), before `Disc_Srv_Search_Req`.
- Leave the module on a trusted segment. `pk_alloc` already refuses an oversize
  buffer; the TCP, DHCP, DNS and ICMP items in §3 are not located tightly enough
  to patch.

Each of those wants the Unicorn replay from §4, with one extra datagram for the
device arm (`urn:schemas-upnp-org:device:SomeDevice` with no trailing colon) that
must return 0 and leave the stack intact.
