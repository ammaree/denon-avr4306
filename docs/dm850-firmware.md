# DM850 network module firmware: origin, update options, build options

Status 2026-11-05. Sources: strings and build paths in `DM850I_x` (I200805270745, the
image on the unit) and `DM850IMG_11.22` (2006-02-07), plus web search (below).

## 1. What the firmware is: BridgeCo platform + Denon application

The image is a static link of two layers, built in two places. The embedded source paths
show which is which:

| Layer | Build path in the 2008 image | Built by |
|---|---|---|
| Platform libraries | `D:\projects\release\src__denon_AVR4306-20060728-01\library\…` | BridgeCo, per-customer release for Denon, 2006-07-28, rev 5791 RC |
| Application, web server, link | `C:\model\avr-4306\denon_AVR4306_20060728_5791_RC_DE20080527\application\DMP\EmbededDmp_Denon\…`, `…\system\WebserverGoAHead\…` | Denon side, 2008-05-27, against that BridgeCo release |

The 2006-02 image shows the same split: `D:\projects\daily\albba_denonAVR4306_app-20060127-01`
(BridgeCo daily build) and `C:\model\avr-4306\denon_AVR4306_20060127_DE20060124_AVR_LPCM`.

Version strings: `denon_AVR4306-1_0_5-5791_RC`, `hal_denonAVR4306-3_1_5-5791_RC`,
`KnOS 3.0.0 (Release)`, `DMP3.0SW-DMP3.0HW (Release)`, `Board HAL EVM WAA3.0`.

**Platform (BridgeCo, binary libraries, no source with Denon's build):**

- KnOS 3.0.0 (BridgeCo OS layer) on ThreadX
- **InterNiche NicheStack** TCP/IP, BSD-derived (`networking\…\tcp\nptcp.c`, `pk_alloc`,
  `bigbufsiz`, `prep_ifaces`, `et_send`, ThreadX port `osporttx`), DHCP client, NTP
- UPnP/DLNA (MediaRenderer, ContentDirectory), streaming framework, NAP v2, Chekov HAL
  (DM850 chip support), IEC 61883 framer
- Mentor Graphics USB host stack (`mgc_*.c`), Microsoft WMA decoder
- Debug shell (`shell.c`, NicheStack CLI: socket list, `tbconn`, `ipstat`, `dcstats`,
  thread/memory/queue dumps). Its I/O is a UART (`device [uart0|uart1…]`); no network
  access to it was found.

**Denon application (`EmbededDmp_Denon`):** LCD/OSD text (`LCDDisplay.cpp`), local menu
UI and IR handling, UPnP application and HTML custom tags, USB direct play, stream status,
`denonProtocolModule` (the MAIN link), the GoAhead web server and the web pages (DM850W),
vTuner-style internet radio (`radiodenon.com/…/rsdb`).

**Answer to (a):** neither purely custom nor stock OEM. It is BridgeCo's DMP 3.0
platform, delivered to Denon as a per-customer binary release, with Denon's application
linked on top. The network stack, sockets, buffers and RTOS (what the LAN hangs most
likely involve) are in BridgeCo's layer. **The 2008 update did not change that layer:**
the 2008 image is built against the same 2006-07-28 BridgeCo release; only Denon's
application was rebuilt.

## 2. Newer or third-party firmware

- **For the AVR-4306: none.** 6.0.0.4 (DM850I 2008-05-27) is the last release.
  Denon's site no longer lists the model.
- **BridgeCo itself:** acquired by SMSC in 2011, SMSC by Microchip in 2012. The successor
  platform (JukeBlox, DM860/DM870) is a different chip. No BridgeCo SDK, source, or
  third-party firmware for the DM8xx was found in public.
- **Sibling Denon models with a DM850** (AVR-3808CI, AVR-4308CI, 2007–2008) received
  network updates with later BridgeCo builds. Their images are linked against other
  boards and Denon applications, so they cannot be flashed here. If one can be obtained,
  it is only a reference: a library diff could show which BridgeCo fixes exist.
- **NicheStack security:** all NicheStack versions before 4.3 are affected by the 14
  INFRA:HALT vulnerabilities (2021; RCE, DoS, DNS poisoning, TCP spoofing). This 2006
  build predates 4.3 by over a decade. No vendor fix will come for this unit, so the
  module should stay on a trusted LAN segment (safety-plan rule 7).

## 3. Build from source vs patch

- **Source build is not possible.** BridgeCo's libraries (KnOS, NicheStack port, HAL,
  UPnP, streaming) exist only as linked object code. Only ThreadX is now open source
  (Eclipse ThreadX, MIT), and a modern ThreadX is not the 2006 one KnOS was built
  against. Rewriting the module firmware means reimplementing the DM850 HAL (no public
  datasheet), the MAIN link, UPnP and web UI. Not realistic.
- **Patch route is possible and is the plan (safety-plan Stage 4).** Already in hand:
  bCoD header and three CRCs (`tools/bcod_sum.py`), packer (`tools/avtool3_pack.py`),
  load map (code copied to SDRAM ~0x6010xxxx, fast region 0x400E0000), ARM32 LE
  ARMv5T, GCC 3.4.0 output (C++ with symbols-like strings). Patches would be binary
  edits plus new code in free space, assembled with `arm-none-eabi-gcc`.
- **Patch targets** depend on the hang diagnosis (Stage 2): likely NicheStack buffer
  pools (`bigbufsiz`, packet buffer counts), socket/connection limits, keep-alive and
  TIME_WAIT handling, and GoAhead's connection handling. The NicheStack CLI strings
  (statistics for keep-alive drops, retransmits, buffer allocation failures) mark the
  relevant code and counters.

## Sources

- [Denon AVR-3808CI firmware update (DM850 BL/IMG/WEB/CNE components)](https://assets.denon.com/documentmaster/us/avr-3808cifirmwareupdate-web1128.pdf)
- [Denon AVR-4308CI firmware update](https://assets.denon.com/documentmaster/us/avr-4308cifirmwareupdate-web0616.pdf)
- [Audioholics: AVR-4306 firmware thread](https://forums.audioholics.com/forums/threads/denon-avr-4306-firmware-update-with-windows-vista.33971/latest)
- [Kroll: SMSC acquires BridgeCo](https://www.kroll.com/en/transactions/smsc-acquires-bridgeco)
- [DM860 product brief (Digi-Key)](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/896/DM860_PB_Ver2_8-27-08.pdf)
- [CISA ICSA-21-217-01: InterNiche NicheStack](https://us-cert.cisa.gov/ics/advisories/icsa-21-217-01)
- [Forescout: INFRA:HALT](https://forescout.com/blog/new-critical-operational-technology-vulnerabilities-found-on-nichestack)
- [Eclipse ThreadX](https://github.com/eclipse-threadx/threadx)
