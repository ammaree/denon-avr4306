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
ST matches `:service:`, so it does not. This site is patched in §4 by the same cave
as the service arm.

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

## 4. Patch: two per-arm guards plus an M-SEARCH length pre-check

Do not flash this. The DM850 has no recovery path if a write fails, and the vendor
update rewrites the web pages with the code (`docs/loader-interface.md`).

Three located changes, Thumb, into two caves in the zero run `0x601CE424`–
`0x601CF090` (no pointer in the SDRAM image lands there).

### 4a. Per-arm guard (`ssdp_guard.S`, cave `0x601CE800`)

The two arms hold identical bytes and both branch to this one cave:

| | Service arm | Device arm |
|---|---|---|
| Site | `0x60049B36`, file offset `0x57D22` | `0x60049AD0`, file offset `0x57CBC` |
| Was | `subs r0, r0, r6` / `lsls r7, r0, #16` (`80 1b 07 04`) | same (`80 1b 07 04`) |
| Now | `bl 0x601CE800` (`84 f1 63 fe`) | `bl 0x601CE800` (`84 f1 96 fe`) |
| Return (r0≠0) | `0x60049B3A` | `0x60049AD4` |

On r0 == 0 the cave branches to `0x60049B76` (`movs r0, #0`, then the epilogue), so
neither reply builder is called. On r0 ≠ 0 it does the original subtract and shift
and `bx lr` back to whichever site called it, so `dial:1`, `ContentDirectory:1` and
a valid `urn:…:device:…:1` still get a reply. This stops the no-colon crash (§1, §2).

### 4b. M-SEARCH length pre-check (`msearch_guard.S`, cave `0x601CE820`)

The per-arm guard checks only for a missing colon. A **well-formed** name that is
simply long (say a 200-byte service name ending in `:1`) still produces a large,
legitimately-computed copy length — `urn_service_reply`/`urn_device_reply` memcpy it
into their `0x64`/`0x5C` frames and overrun. `receiveData` already drops a datagram
of `0x200` bytes or more, but a long name fits well under that.

So a second guard bounds the ST value length before the search is dispatched:

| | |
|---|---|
| Site | `0x60136174`, file offset `0x144360` (in `receiveData`, just before the `bl Disc_Srv_Search_Req` at `0x60136178`) |
| Was | `ldr r0, [sp, #0x274]` / `adds r3, r6, #0` (`9d 98 33 1c`) |
| Now | `bl 0x601CE820` (`98 f0 54 fb`) |

At this point `r2` holds the ST value length — the same value the arms use as the
total from which the reply "rest" copy is derived, so `r2` is ≥ the bytes that get
copied. The cave runs the two displaced instructions, then: if `r2 ≤ 0x40` it
`bx lr` to the dispatch (`0x60136178`); if `r2 > 0x40` it branches to `0x6013618A`,
`receiveData`'s own return path, dropping the datagram. `0x40` is below both reply
frames and above any well-formed UPnP ST, so no real search is lost.

### Apply

`tools/dm850/apply_ssdp_guard.py` assembles both sources with `arm-none-eabi-gcc
-mthumb -march=armv5t` when that compiler is on `PATH`, else `clang -target
arm-none-eabi`. It checks every site's byte pattern and both zero runs, writes
`build/patch/DM850I_ssdp.flash.bin`, and recomputes the three bCoD CRCs with
`tools/bcod_sum.py`. The patched image differs from the vendor image in 58 bytes:
three 4-byte BLs, the 20-byte arm cave and the 20-byte pre-check cave (each sharing
one zero byte with the run), and the two bCoD CRC words.

Offline gate, before any flash: `python3 -I tools/dm850/test_ssdp_guard.py` executes
the per-arm cave. A zero search result must branch to `0x60049B77`. A non-zero result
must leave `r0 = r0 - r6` and `r7 = r0 << 16` and return through `bx lr`. The same run
rebuilds the patched image and checks all three BLs, both caves' bytes and the CRCs,
and that the vendor image is unchanged at every site. The pre-check cave's own two
branches are exercised in the replay gate below (it uses an sp-relative load).

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
| vendor | `urn:…:device:MediaServer` (no `:N`) | reply reached, copy length **65512** into the `0x5C` frame |
| vendor | `urn:…:device:MediaServer:1` | reply reached, length 11 |
| patched | `urn:Belkin:service:basicevent` | **no reply**, type switch returns 0 |
| patched | `urn:…:service:dial:1` | reply reached, length 4 |
| patched | `urn:…:service:ContentDirectory:1` | reply reached, length 16 |
| patched | `urn:…:device:MediaServer` (no `:N`) | **no reply**, type switch returns 0 |
| patched | `urn:…:device:MediaServer:1` | reply reached, length 11 |
| vendor / patched | `urn:x:service:A×200:1` (well-formed, long) | reply reached, copy length **200** into the `0x64` frame |

The vendor overrun lengths (65521 service, 65512 device) are the low 16 bits of the
negated name pointer, confirming §1 and §2: a copy far larger than the frame. The
patched image drops exactly the two no-colon cases and leaves every well-formed
search answering with the same length. The gate is meaningful: on an unpatched image
the patched assertions fail, because those searches reach the reply.

The long well-formed name (last row) overruns on **both** images via the arm — its
name has a colon, so the per-arm guard (§4a) passes it. That is the residual the
pre-check (§4b) exists for. The harness also runs the pre-check cave directly on the
patched image: with `r2 = 0x30` it dispatches, with `r2 = 212` (the long ST) it takes
the drop path to `0x6013618A`. So the datagram never reaches the arm once the
pre-check is in place.

## 5b. Codebase audit: copy-site scan (2026-11-10)

With the whole-program codebase (docs/dm850-codebase.md), `tools/ghidra/AuditCopyArm.java`
classified **all 442 copy-routine call sites** (`memcpy` 0x60011C90, `blk_copy` 0x60011D48)
by length and destination:

| Class | Count | Meaning |
|---|---|---|
| constant length | 309 | safe |
| variable length, non-stack dest | 108 | lower risk (heap/caller buffer) |
| **variable length into a stack dest** | **25** | the SSDP-crash shape — triaged below |

Of the 25, **3 are the known SSDP-crash copies** (`urn_service_reply` ×2, `urn_device_reply`)
— the scanner finding them validates it. The others were triaged:

- **Bounded (safe):** `FUN_60070188` (checks `dst_size >= len`), `FUN_60076f94` (every copy
  guarded `if size < len return`), `FUN_600797c4` (capacity ensured before copy),
  `FUN_601548e8` (clamps the length to the buffer), `FUN_6012e084` (stack copy guarded
  `len < 0x81`, the rest heap-allocated to fit). DM850 copy code generally checks or clamps.
- **Initially suspected, resolved to bounded on full reading:** the 3-line grep window hid
  the guards; the full decompile shows each is safe —
  `FUN_60170938` clamps `n` to `0x80` (`else n = 0x80`) before the copy into a `0x80` buffer;
  `FUN_60079324` calls `FUN_60079740(buf, field[6] + n)` to **ensure capacity** before the
  append (heap buffer, not a fixed frame);
  `FUN_600701c8` copies a **fixed table string** (`strlen` of a constant from `DAT_60070214`),
  not attacker data;
  `FUN_601651b4` / `FUN_6016612c` are local-to-local copies.
- Still open, low confidence: the `n` origin in `FUN_601651b4`/`FUN_6016612c` was not pinned
  to a bound (the copy shape is innocuous and both are local-to-local, so likely bounded);
  `FUN_60170668` and the two `blk_copy` sites not fully read.

**Result: no new confirmed memory-safety bug.** The SSDP responder's missing length check
was the exception; every other variable-length copy triaged either checks, clamps, or
ensures capacity. The DM850's copy discipline is good. The scan (`AuditCopyArm.java`) makes
this reproducible, and the two low-confidence sites are the only places a second copy bug
could still hide.

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

The device-arm zero-test (`0x60049AD0`) and the M-SEARCH length pre-check are both
applied in §4 now, not proposed; the replay gate covers them. The pre-check is placed
at the dispatch guard in `receiveData` (`0x60136174`), where the ST length is already
in `r2`, rather than inside `UDP_Rec_Check_MSearch_Req`; the effect is the same —
drop before `Disc_Srv_Search_Req` — and the length is in hand there without re-deriving
it. What is still only proposed:

- Leave the module on a trusted segment. `pk_alloc` already refuses an oversize
  buffer; the TCP, DHCP, DNS and ICMP items in §3 are not located tightly enough
  to patch.

## Audit status (2026-11-10) — DM850 brought to MAIN's level

With the whole-program codebase (docs/dm850-codebase.md, ~12,361 functions) and the
code-flow doc (docs/dm850-codeflow.md), the DM850 now has the same depth of analysis as
MAIN. Audit state:

- **Memory-safety (copy class): clean.** The whole-image copy-site scan (§5b) found the 3
  known SSDP-crash copies and **no new confirmed bug**; every other variable-length copy
  checks, clamps, or ensures capacity. ARMv5T has no hardware divide (division is a library
  call that handles zero), so there is no divide-by-zero trap class either.
- **Confirmed + fixed:** the SSDP service/device no-colon crash (the LAN hang), guarded and
  gated (§1–4), versioned `dm850i-p1`, **not flashed**.
- **Still suspected, not actionable:** the NicheStack INFRA:HALT class (§3) — third-party
  object code, confirmable only by deep RE of a known-buggy stack, and **not actionable**
  because the DM850 has no proven flash delivery or recovery path (the SSDP fix itself is
  stuck on the same wall). Network-level isolation (control-bridge filter) is the standing
  mitigation.
- **Long tail (not done):** per-function naming of the ~12k functions, and per-subsystem
  logic audits of the web server / UPnP control / NicheStack internals — the same
  diminishing-returns tail as MAIN, and lower value here given the no-flash-path constraint.

Conclusion: no fix is both needed and deliverable beyond the SSDP guards already built. The
DM850's remaining real blocker is **delivery/recovery**, not more audit.
