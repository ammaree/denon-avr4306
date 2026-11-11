# LAN connectivity loss — root cause and firmware target

Status 2026-11-11. The "unit loses LAN IP connectivity" fault (CLAUDE.md objective) was
diagnosed in a separate network-diagnosis project in October 2026, on this same unit
(192.0.2.13). This file records the result and points the firmware work at it; it does
not re-derive it.

## RESOLVED — firmware fix flashed and verified (2026-11-11)

The patched DM850I image (`build/patch/DM850I_ssdp.flash.bin`, SSDP triple guard) was
flashed to the unit and the fix was verified on the hardware: with the edge router/AP filter
disabled, 15 Belkin `M-SEARCH` killer packets were sent to 192.0.2.13:1900 and the DM850
stayed fully responsive (ALIVE on 80/5001/23) past +40 s, where an unpatched unit hangs
within ~4 s. Flash method and recovery: `docs/dm850-delivery.md`; protocol:
`docs/updater-protocol.md`. The edge router/AP bridge-filter (below) is now **disabled** — the
firmware fix replaces the containment. The sections below are retained as the diagnosis
record; "Current mitigation" and "Firmware target" are now historical.

## Root cause (confirmed on the unit)

- The DM850 network module's whole stack hangs — no ARP, no ping, no TCP, layer 2 and up
  gone — when it receives one SSDP `M-SEARCH` whose `ST:` header is
  `urn:Belkin:service:basicevent`. The module does not answer that search; its SSDP
  responder dies while handling it. A full AC power-cycle is the only recovery.
- Isolated by replaying single packets on a freshly booted unit: the Belkin search kills
  it within ~4 s, while `upnp:rootdevice`, `ssdp:all`, DIAL (`dial-multiscreen-org`),
  MediaRenderer/MediaServer searches and HA's `ssdp:all` scan all leave it alive for
  minutes. So it is this one `ST` value, not SSDP volume and not a follow-up unicast.
- Real-world source: a UPnP-scanning smart TV on the LAN's Home Hub scan (every ~5 min) emits the
  Belkin (WeMo) and DIAL searches. The AVR's drops began once that TV was on the LAN.

Full record, with the wrong turns and the packet captures: external diagnosis notes, not
in this repo.

## Prior mitigation (network, not firmware) — now disabled

A bridge-filter rule on the AVR's AP port dropped outbound UDP 1900 to the AVR
(`hw=no` so the CPU sees it), keeping the killer packet off the unit. It was a containment,
not a fix. **Disabled 2026-11-11** once the firmware fix was flashed and verified (above);
the owner chose to leave it off. To restore it as defense-in-depth, re-enable the
bridge-filter rule on the edge router/AP.

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

**Superseded 2026-11-11:** the delivery and recovery paths were settled and the patched
DM850I was flashed and verified on the unit (see the "RESOLVED" section at the top, plus
`docs/dm850-delivery.md` and `docs/updater-protocol.md`). The text above described the
pre-flash state. Nuance it now carries: the SSDP responder is indeed in the BridgeCo
platform layer, so no *vendor* release (which rebuilt only Denon's app) ever fixed it — but
that layer ships inside the DM850I image, and a direct byte-patch of the image (the triple
guard in `DM850I_ssdp.flash.bin`) fixes it and survives a flash, which is what was done.
