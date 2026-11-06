# LAN connectivity loss — root cause and firmware target

Status 2026-11-06. The "unit loses LAN IP connectivity" fault (CLAUDE.md objective) was
diagnosed in the sibling **control-bridge** project in October 2026, on this same unit
(192.168.1.13). This file records the result and points the firmware work at it; it does
not re-derive it.

## Root cause (confirmed on the unit)

- The DM850 network module's whole stack hangs — no ARP, no ping, no TCP, layer 2 and up
  gone — when it receives one SSDP `M-SEARCH` whose `ST:` header is
  `urn:Belkin:service:basicevent`. The module does not answer that search; its SSDP
  responder dies while handling it. A full AC power-cycle is the only recovery.
- Isolated by replaying single packets on a freshly booted unit: the Belkin search kills
  it within ~4 s, while `upnp:rootdevice`, `ssdp:all`, DIAL (`dial-multiscreen-org`),
  MediaRenderer/MediaServer searches and HA's `ssdp:all` scan all leave it alive for
  minutes. So it is this one `ST` value, not SSDP volume and not a follow-up unicast.
- Real-world source: a lounge **LG OLED** TV's Home Hub scan (every ~5 min) emits the
  Belkin (WeMo) and DIAL searches. The AVR's drops began the day that TV joined the LAN.

Full record, with the wrong turns and the packet captures:
`~/DevSpace/z-projects/control-bridge/docs/research/2026-10-23-16-avr-network-deaths-spins.md`
and `…/2026-10-18-12-avr-network-hangs.md`.

## Current mitigation (network, not firmware)

A RouterOS bridge-filter rule on the AVR's AP port drops outbound UDP 1900 to the AVR
(`hw=no` so the CPU sees it). It keeps the killer packet off the unit. The AVR itself is
unchanged. This is a containment, not a fix: any new SSDP searcher that reaches the unit
with that `ST` would hang it again, which is why safety-plan rule 7 (isolated segment)
stands.

## Why this is a firmware bug

- The SSDP responder is in the **BridgeCo platform layer** (KnOS 3.0.0 / NicheStack on
  ThreadX), not Denon's application (dm850-firmware.md §1). The 2008 update rebuilt only
  Denon's application, so no release ever fixed it.
- It is a parser/responder fault on one header value: a denial of service reachable by a
  single unauthenticated multicast packet from anywhere on the L2 segment. NicheStack of
  this age also carries the INFRA:HALT class of defects (dm850-firmware.md §2).

## Firmware target (for Stage 4)

The SSDP request strings live in the DM850I image (`build/images/DM850I_x.flash.bin`,
de-inverted) around 0x1AA510, 0x1C30C9–0x1C35xx and 0x1D65xx: `M-SEARCH`,
`ssdp:discover`, `ST:`, `upnp:rootdevice`, `ssdp:all`, the `urn:…:service:…` set. The
responder that reads an incoming `ST` and walks the device/service table is the code to
find from those references. The fix is to make that path reject or safely ignore an
unknown/overlong `ST` instead of faulting.

Image facts already in hand (firmware-package.md §3.4, dm850-firmware.md §3):
- bCoD header at 0x00, code entry/load value 0x400E0080, scatter table at 0x1A0; body
  copied to SDRAM ~0x60100000 with a fast region near 0x400E0000.
- ARM32 LE, ARMv5T, GCC 3.4.0. Checksums: `tools/bcod_sum.py` (3 CRCs). Packer:
  `tools/avtool3_pack.py`.
- Delivery to the unit is the DM850 route (`01 0A`); **but** the vendor LAN update always
  runs stage 2 and rewrites DM850W, and `erase webpage`/bootloader writes are forbidden
  (safety-plan rules 1–2, loader-interface.md §2.8). A DM850-only delivery path is an
  open problem, separate from building the firmware.

**No DM850 flash has been written or dumped on this unit.** Everything above is from the
vendor image and the external diagnosis. Reproducing or rebuilding the module firmware is
analysis only until a delivery path and a recovery path for the DM850 are settled.
