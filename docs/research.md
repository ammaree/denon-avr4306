# Online research notes (Phase 1a)

Date: 2026-11-04. Facts below are from the cited documents; items marked **[verify]**
are inferred or come from a sibling part and must be checked against the exact
hardware manual.

## 1. Renesas M32C/87 (MAIN, M30879FLFP)

Source: M32C/87 Group datasheet REJ03B0127-0151 (Rev. 1.51, 2008-07-31), local copy
text-extracted; DJ Delorie, "Easy R8C/M16C/M32C/R32C Flash Programming" (2009).

- 16 MB address space. Internal ROM grows down from 0xFFFFFF: 1 MB = 0xF00000–0xFFFFFF.
  Matches the package range (0xF00000–0xFFBFFF) plus the excluded top 16 KB.
- Fixed vectors 0xFFFFDC–0xFFFFFF (reset at 0xFFFFFC); special-page vectors
  0xFFFE00–0xFFFFDB (`JMPS`/`JSRS`). All inside the excluded region → **the reset
  vector, fixed vectors and special-page table are in the resident boot block, not in
  any package.**
- Flash erase blocks are 4 KB at the top ("4-Kbyte block erase time" in the electrical
  table); the top 16 KB = four 4 KB blocks **[verify block map in hardware manual
  REJ09B0180]**. 100 erase/program cycles guaranteed — relevant to Phase 1f test
  flashing: budget the writes.
- SFRs 0x000000–0x0003FF; RAM 48 KB at 0x000400–0x00C3FF; 4 KB data flash at
  0x00F000–0x00FFFF (flash version).
- CNVSS = L → single-chip mode; CNVSS = H → boot (serial I/O) mode. PM0 reads
  `1000 0000b` with CNVSS=L.
- ID code (flash unlock key, 7 bytes) lives at 0xFFFFDF, E3, EB, EF, F3, F7, FB — the
  low bytes of the fixed vectors — i.e. **in the excluded boot block**. Not recoverable
  from the package; on the unit try all-0x00 and all-0xFF first (common tool defaults).
- Standard serial I/O mode 2 (async): 9600 8N1 auto-baud with 16 × 0x00, then
  `B0..B4` baud select, `FB` version ("VER.x.xx"), `70` status, `50` clear status,
  `F5` unlock, `A7 D0` erase all, `41` program page (256 B), `FF` read page. Protocol
  common to M16C/M32C; addresses 24-bit LE. Read page is what Phase 1b needs for the
  boot block, and it requires the unlock key.

## 2. Renesas M16C/62P (SUB, M30624FGPGP)

Source: M16C/62 Group (M16C/62P) datasheet REJ03B0001-0110Z (Rev. 1.10, 2003); M16C/62P
virtual-EEPROM application note; M16C/62A flash appendix (for serial I/O pin
conditions).

- 1 MB address space. 256 KB ROM = 0xC0000–0xFFFFF; matches the package range plus the
  excluded top 8 KB (0xFE000–0xFFFFF).
- Fixed vectors 0xFFFDC–0xFFFFF, special-page vectors 0xFFE00–0xFFFDB — again inside
  the excluded region. The 60-entry table at 0xFDF00 pointing to 0xFE110 (see
  firmware-package.md §3.2) is the application's INTB variable-vector table pointing at a
  dispatcher in the boot block **[verify by disassembling 0xFE110 once dumped]**.
- Flash blocks at the top: block 0 = 4 KB 0xFF000–0xFFFFF, block 1 = 4 KB
  0xFE000–0xFEFFF (10,000-cycle block, intended for data) **[verify full map]**. Block
  A = 4 KB data flash at 0xF000–0xFFFF, also 10,000 cycles. Other blocks 1,000 cycles.
- RAM 20 KB from 0x00400; SFR 0x00000–0x003FF.
- Serial I/O mode entry: reset released with P50 (CE) = H, P55 (EPM) = L, CNVSS = H.
  Mode 1 (clock-synchronous) if CLK1 (P65) high at reset release, mode 2 (async, UART1
  RXD1/TXD1 only) if low. The jig pin set is exactly P64/P65/P66/P67 — the pins the
  service manual marks "for emulator" / "data transfer to outside" on the SUB.
- ID code at 0x0FFFDF, E3, EB, EF, F3, F7, FB — in the excluded block 0.
- Boot ROM: standard serial I/O mode is unusable if the boot ROM area has been
  rewritten in parallel mode; only user ROM is rewritable serially.

## 3. ADSP-21366 (DSP)

Source: ADSP-21362/3/4/5/6 datasheet (RS mirror, 12 pages).

| BOOT_CFG1–0 | Mode |
|---|---|
| 00 | SPI slave boot |
| 01 | SPI master boot |
| 10 | Parallel port boot via 8-bit EPROM |
| 11 | Reserved |

- Schematic: BOOT_CFG1 pulled up (R568) and switchable low by TR504/TR505 under SUB
  control; BOOT_CFG0 strapped by R571. If R571 is a pull-down, normal boot = `10`
  (parallel port, from LH28F160) and the SUB can force `00` = SPI slave boot — which is
  the only mode in which the SUB's SPI master port can feed the DSP a flash-writer.
  **[verify R571 end on the board]**.
- Datasheet notes that on secured parts "emulation features and external boot modes
  are only available after the correct key is scanned" via JTAG — check whether this
  part is a secured variant before relying on CX502 JTAG.
- Loader stream: boot kernel of 256 instructions, then blocks with a 3-word header
  (tag, count, address). The 2136x tag list and the exact 8-bit PROM packing are in the
  ADSP-2136x Hardware Reference and the VisualDSP++ Loader manual. **analog.com and its
  CDN refused or timed out from this network**, so EE-177, EE-345, EE-223 and the
  hardware reference are still to be fetched (try another network or a mirror).

## 4. BridgeCo DM850 (network module)

Sources: EDN, CES 2006-01-05 (eDMP reference design); BridgeCo press releases 2005
(DM1200/DM1500), DM860/DM870 product briefs; Design & Reuse (DM870, 2008).

- DM850: "proprietary ARM-based, DSP-enhanced" processor; interfaces to Wi-Fi,
  HomePlug, USB and Ethernet PHYs; I2S and S/PDIF out; **SPI slave to the host with a
  proprietary XML-based protocol**; RTOS + eDMP firmware stack (TCP/IP, USB, MP3/WMA,
  DTCP-IP/WMC DRM). Matches the image name "EmbededDMP_Denon_Release" and the
  MAIN↔DM850 SPI link.
- Siblings DM1200/DM1500 (2005) and DM860/DM870 (2008) use ARM926EJ-S cores. The DM850
  image uses `blx` immediate (ARMv5T+), so an ARM9E-class core is consistent
  **[verify; no DM850 datasheet found online]**.
- BridgeCo was acquired by SMSC (2011), later Microchip. No DM850 datasheet, SDK or
  memory map is public. The firmware strings (`armIntSet/Clr/Trg`, `MtxBootSel`,
  `ptuVersion`, "KnOS/3.2", ThreadX 1.0, GCC 3.4.0) are the available reference.
- The image's own header (`bCoD`, see firmware-package.md §3.4) carries a 32-bit value
  0x400E0080 in the code images; candidate load/entry address.

## 5. Prior art

No public reverse-engineering, dump or protocol write-up for the AVR-4306/AVC-4320 was
found. Public material is limited to the service manual, the 6.0.0.x updaters and the
"DENON Flash Rom Writer Compact Version" (FWCV_AVR4306_V0010) manual — the latter
corresponds to the local `RECOVERY Firmware Network AVR-4306.zip` (InstallShield
package, not yet unpacked here).

## 6. Consequences for the plan

1. Nothing in the packages contains a reset vector or interrupt vector for MAIN or SUB;
   the resident boot blocks must be dumped from the unit (serial I/O mode, needs the ID
   code) before any byte-exact rebuild is complete.
2. Flash endurance is 100 cycles (M32C/87) — count every test flash.
3. The DSP flash boot block (first 32 KB) and the DM850 flash are reachable only via
   JTAG (CX502, unfitted) or in-circuit reads; the DM850 JTAG landing is still unknown.
4. The FWCV recovery package should be unpacked next: it may carry the DM850IMG and the
   recovery protocol, and it is the only vendor tool that talks to a unit whose
   application firmware is dead.

## Sources

- Renesas M32C/87 datasheet REJ03B0127-0151 (mirror: static.datasheets.com/doc/3628951)
- Renesas M16C/62P datasheet REJ03B0001-0110Z (mirror: datasheets.com/renesas/m30624fgpfp)
- DJ Delorie, Easy R8C/M16C/M32C/R32C Flash Programming, people.redhat.com/dj/m32c/flash-guide.pdf
- M16C/62P virtual EEPROM app note, webpages.charlotte.edu/~jmconrad/ECGR6185-2007-01/labs/virtual_eeprom_m16cap.pdf
- ADSP-2136x datasheet mirror, nonprod.docs.rs-online.com/443d/0900766b80de1aa5.pdf
- EDN, BridgeCo eDMP/DM850 at CES 2006, edn.com/?p=4081102
- phys.org, BridgeCo DM1200/DM1500 (2005); Design & Reuse, DM870 (2008); DigiKey DM860/DM870 product briefs
- Audioholics forum thread on AVR-4306 firmware 6.0.0.2 (Denon Canada distribution)
