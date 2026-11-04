# Schematic notes — processors, programming paths, service access

Source: service manual Ver. 3, schematic sheets 1–34 (PDF pages 102–135). Sheets are
vector drawings without a text layer; read from 200–300 dpi renders. Items marked
**[verify]** were not fully legible or need the datasheet.

## Sheet map

| Sheet | Page | Unit | Relevant content |
|---|---|---|---|
| 1 | 102 | 1U-3700-1 MAIN CPU (1/2) | M30879 IC506, region straps, CNVSS, TP501 |
| 21 | 122 | 1U-3698-1 DIGITAL (1/11) | DIR section (LC89057 ×3) |
| 22 | 123 | DIGITAL (2/11) | Main PLD EPM570 IC151, JTAG test point CX152 |
| 23 | 124 | DIGITAL (3/11) | **SUB CPU M30624 IC251** |
| 24 | 125 | DIGITAL (4/11) | Main DAC section |
| 32 | 133 | 1U-3698-2 ETHERNET (1/2) | **DM850 IC905**, W19B320 flash, SDRAM, PHY, link to MAIN |
| 33 | 134 | ETHERNET (2/2) | XM section (USA/Canada only) |
| 34 | 135 | 1U-3698-3 DSP | **ADSP-21366 IC506**, LH28F160, SRAM, JTAG, boot straps |

## MAIN µcom (sheet 1)

- IC506 M30879FLFP. X501 30 MHz. Reset from a supervisor circuit (RESET net).
- Region is a resistor option on P100/AN0 (MODE): USA/Canada R572 = 0; Europe/Asia
  R571 = 0; Taiwan/China/Korea 4.7 k/4.7 k; Japan 10 k/20 k. **The firmware is common;
  the 220 V EU unit is selected by R571 only.**
- Boot-mode pins: CNVSS (pin 9) has R653 10 k pull-down; R602 "OPEN" is an unfitted
  pull-up; J305/J306 "OPEN" jumpers sit on the same node. So normal boot is
  single-chip mode and the serial-programming mode is reachable by fitting R602 or
  bridging J305/J306 **[verify which jumper goes where]**. P50/CE = TERST (video-detector
  reset), P55/EPM = MUTEPOWER; both must be forced for serial I/O mode.
- TP501 "OPEN": unfitted 9-pin test header next to the UART pins. The M32C standard
  serial I/O mode uses UART1 (P66/RXD1, P67/TXD1), P64 (BUSY) and P65 (SCLK); here
  UART1 is the RS-232 port (via HIN202 on the FRONT unit) and P64/P65 are the video
  selector I²C. TP501's pins carry the UART nets **[verify pin-by-pin]**. Working
  hypothesis: TP501 + R602/J305 are the factory flash-programming interface, and the
  rear RS-232 jack may double as the programming channel.
- Link to DM850 (connector CW118, 11 pins, to ETHERNET unit): E_RXDMOEI, E_TXDMIEO
  (UART0 P62/P63), E_REQ (P17/INT5), E_SPIMOEI (P96/SOUT4), E_SPIMIEO (P97/SIN4),
  E_SPICLK (P95/CLK4), E_SPICS (P94), E_RESET (P86), MASTERM5V, MGND; E_MODE (P81)
  **[verify pin 7]**. **MAIN is the SPI master**: its SOUT4 drives the DM850's
  SPIMOSI pin, its SIN4 reads SPIMISO.
- Link to SUB: ACKSUB, MOSI, SOMI, CLKMO, RSTSUB, REQSOMI (P90–P93, P16, P87).

## SUB µcom (sheet 23)

- IC251 M30624FGPGP, X251 12 MHz, BYTE pin = GND (16-bit), RESET has a test pad.
- CNVSS (pin 7) routing not resolved from the render **[verify]**; no programming header
  seen on this sheet.
- P64/CTS1 (BUSY) and P65/CLK1 (SCLK) are marked "for emulator" in the pin table and,
  with P66/RXD1 + P67/TXD1 ("data transfer to outside"), are exactly the M16C standard
  serial I/O mode 1 pin set. They leave the sheet through 33 Ω series resistors
  (RE218, RE221) towards a connector **[verify destination]**.
- Main↔sub link on UART0 (P62/P63) + REQSOMI (P60) + CLKSIMO (P61) + ACKSIMO (P83/INT1).
- DSP link: DSPICLK/DSPOSI/DSPISO/DSPICS (P95–P97, P101) = SPI, **SUB is master**;
  FLAG0–2 from the DSP; DSPRST (P106), DSPROMRST (P105), DSPOSCON (P100), VPP (P11),
  DSPBOOT (P87 input).
- PLD control: MPLDCSMAIN, MPLDDATA, MPLDCLK, SEL0–4, and a net `SUBCPUJTAGON`.

## DSP (sheet 34)

- IC506 ADSP-21366SKBCZ, FCXO 20.815 MHz (IC505).
- Parallel port AD0–AD15 + ALE + RD + WR → address latches IC503/IC504 (74VHC573) →
  AD8–AD23; IC502 (74LVC139) decodes BANK0–3 chip selects. LH28F160 flash and the three
  CY7C1049 SRAMs hang on this bus. **The DSP is the only device that can write its
  flash**; VPP from the SUB gates the flash write-enable/RP **[verify pin]**.
- SPI slave port (MOSI, MISO, SPIDS, SPICLK; 10 k pulls R556/R587/R588) from the SUB.
- Boot straps: BOOTCFG1 (pin 29) pulled up by R568 10 k and pulled down by TR504/TR505
  when the SUB asserts `SPRST`; BOOTCFG0 (pin 30) strapped by R571 10 k. A tact switch
  **S501** on the DSP board acts on the same node. This lets the SUB (or a technician)
  re-boot the DSP in a different boot mode — the mechanism for loading a flash-writer
  over SPI and reprogramming the LH28F160. Exact strap levels vs. the ADSP-2136x
  boot-mode table **[verify on the board]**.
- **CX502 "OPEN"**: unfitted 10-pin JTAG header — TCK, GND, TDO, VCC, TMS, TRST, EMU0,
  EMU1, TDI, GND — with 0 Ω links R502/R504/R505/R507 and R501 OPEN. Fit a header and the
  DSP (and through it the flash, including the boot block) is reachable with an ADI
  emulator or OpenOCD-class tool.

## DM850 network module (sheet 32)

- IC905 BCOIC-DM850-QCL, 24.576 MHz crystal, 3.3 V/1.8 V regulators.
- Boot/code flash IC903 W19B320ABT7H (32 Mbit, 16-bit mode, BYTE# high) on NCS[0],
  address A[1..21] + A0; SDRAM IC904 IS42S16400B on NCS[1]; NOE/NWE; MEMCLK/MEMCKE.
  Flash RP#/RB# via R932 4.7 k **[verify]**.
- PHY DM9161AEP on MII; ETH_PDOWN from the DM850.
- To MAIN: SPIMOSI/SPIMISO/SPINCS[0] (slave side, series 0 Ω/47 k RR942/RR943),
  UART RXD/TXD (E_RXDMOEI/E_TXDMIEO) through 74VHC14/74VHCT08 level logic (IC909,
  IC912), E_REQ, E_MODE, E_RESET (TR903/TR904 reset driver).
- **DEBUG_RX / DEBUG_TX** (pins 80/81, a second UART) and **TMS/TCK/TDI/TDO**
  (pins 92–95) are brought out as named nets; TEST pins pulled through 47 k. The only
  unfitted part on the sheet is AS901 "OPEN"; whether the debug/JTAG nets land on
  it or on pads must be checked on the PWB drawing (manual pages 54–55) **[verify]**.
- Audio: I2S_BCLK/I2S_DATA and S/PDIF (SPDIFETHER, SPDIFUSB, MUTE*) to the DIGITAL unit
  via CY891 (9 pins).

## Programmable logic (sheet 22)

- CX152 "T.P" 7-pin FFC: TCK, TDOBUS, TMS, TDI with 1 k pulls and the note
  `TDI → TDOMAIN → TDOHDMI`: a JTAG chain through the main PLD (EPM570) and the HDMI/video
  PLD. This is the CPLD programming point; the DM850 and DSP are **not** in this chain
  (they have their own TAPs).

## Update route, confirmed against the hardware

```
PC --Ethernet--> DM850 (ARM, TCP) --UART0 + SPI(slave)--> MAIN M32C  [route 01]
                                                        MAIN --UART0--> SUB M16C  [route 01 02]
                                                                        SUB --SPI(master), BOOTCFG, VPP--> DSP --parallel bus--> LH28F160  [01 02 03]
                                 DM850 <--SPI(slave)-- MAIN            (DM850 images)  [01 0A]
```

- MAIN rewrites its own flash (resident loader in the top 16 KB, outside the package).
- SUB rewrites its own flash (resident loader in the top 8 KB; its interrupt vectors
  point there).
- DSP flash is written by DSP code; the SUB puts the DSP into the alternate boot mode
  and feeds it over SPI.
- DM850 images go MAIN → DM850 over the SPI link, so the DM850's own loader (the
  resident part of its flash) does the write.

## Hardware access points for Phase 1b (image acquisition)

| Target | Access | Fitted? |
|---|---|---|
| DSP + LH28F160 incl. boot block | CX502 JTAG (10-pin) | no — footprint only |
| DM850 + W19B320 | TMS/TCK/TDI/TDO nets, DEBUG UART | unknown landing |
| MAIN M32C | CNVSS via R602/J305/J306, TP501, UART1 (RS-232 jack) | no |
| SUB M16C | P64/P65/P66/P67 serial I/O pins (leave via RE218/RE221) | unknown landing |
| CPLDs | CX152 JTAG chain | FFC footprint |
| W19B320 / LH28F160 in-circuit | TSOP clip while the host is held in reset (E_RESET / DSPRST) | — |
