# AVR-4306 hardware inventory (firmware-relevant)

Source: Denon service manual X0264-1 **Ver. 3** (June 2007), `denon_avr-4306_ver.3.pdf`.
Ver. 1 (`AVR-4306_AVC-4320_Service_Manual_ENG.pdf`) differs only in title page and two
FFC part numbers. Items marked **[verify]** come from general part knowledge, not the
manual, and must be checked against the part datasheet.

## Boards

| Board | Unit | Firmware-bearing parts |
|---|---|---|
| 1U-3700 | MAIN CPU | IC506 main CPU |
| 1U-3698 | DIGITAL (incl. ETHERNET and DSP sub-units) | sub CPU, DSP + flash, network module + flash, scaler, CPLDs, EEPROMs |
| 1U-3743 | AUDIO/VIDEO | M35015 OSD (mask ROM), shift registers, volume ICs |
| 1U-3703 | FRONT | PT6302 FL drivers, HIN202 RS-232 transceiver, IR receiver |
| 1U-3701 / 1U-3702 | POWER AMP / POWER SUPPLY | none |

## Programmable devices

| Ref | Part | Role | Code store | Notes |
|---|---|---|---|---|
| MA IC506 | Renesas M30879FLFP (M32C/87) | Main µcom | internal flash | Service part "MAIN CPU SUB ASSY" = pre-programmed. Flash/RAM size **[verify]** |
| DI IC251 | Renesas M30624FGPGP (M16C/62P) | Sub µcom (digital board) | internal flash | "SUB CPU SUB ASSY". 256 KB + 4 KB flash, 20 KB RAM **[verify]**. 12 MHz crystal X251 |
| DI IC506 | ADSP-21366SKBCZ (SHARC) | Audio decode / post-processing | DI IC507 LH28F160BJE (16 Mbit parallel flash, "DSP ROM SUB ASSY") | 3 × CY7C1049 SRAM (IC508–510), 20.815 MHz FCXO |
| DI IC905 | BCOIC-DM850-CQL | Network module (Ethernet, net audio, USB **[verify]**) | DI IC903 W19B320ABT (32 Mbit flash, "DM850 ROM SUB ASSY") | IS42S16400 SDRAM, DM9161AEP PHY, 25 MHz. CPU core **unknown** |
| DI IC751 | Genesis FLI2310 | Video deinterlacer/scaler | none listed | K4S643232 SDRAM. Config path **[verify]** (host register load expected) |
| DI IC151 | Altera EPM570T144 (MAX II) | Main PLD | internal config flash | Non-volatile CPLD **[verify]** |
| DI IC701 | Altera EPM570F256 (MAX II) | PLD | internal config flash | Non-volatile CPLD **[verify]** |
| DI IC754 | Lattice LC4064V (ispMACH 4000) | Video PLD | internal | Non-volatile CPLD **[verify]** |
| AV IC703 | M35015-***SP | OSD | mask ROM | No field firmware |
| DI IC204, 403, 404 | BR24L02 (2 Kbit I²C EEPROM) | HDMI input EDID | data | Write-protect lines WP1–WP3 from sub CPU |
| FR IC103, 104 | PT6302LQ-001 | VFD driver | mask (CGROM) | No field firmware |

Pin-table note: the sub CPU pin table names the main PLD as "EPM3128ATC144-10";
the Ver. 3 parts list says EPM570. Treat the parts list as current.

## Inter-processor links (from µcom pin tables)

Main µcom M30879 (MA IC506):

| Link | Pins | Peer |
|---|---|---|
| Main ↔ sub µcom | P90/CLK3, P91/SIN3, P92/SOUT3, P93 ACK, P16/INT4 REQ | M30624 UART0 (P60–P63) + P83/INT1 ACK |
| Network module | SPI: P94 CS, P95 CLK, P96 MOSI, P97 MISO; UART0 P62/P63; P86 E_RESET; P81 EMODE; P17/INT5 EREQ; P13 EPOWER | DM850 |
| RS-232 (AMX / control protocol) | UART1 P66/P67; P12 232C POWER | HIN202 on FRONT |
| iPod | UART5 P76/P80; P40 detect; P101 charge | dock connectors |
| XM radio | UART2 P70/P71; P77 REQ | XM module |
| FL display | P02–P06 (CLK, DATA, CE1, CE2, RST) | PT6302 ×2 |
| OSD | P32–P35 | M35015 |
| Video selector | P64/P65 (I²C-like) | NJW1321 |
| Tuner / RDS | P41–P47, P51 | LC72131, LC72720 |
| Shift-register expanders | audio P72–P75; video P21–P24 | TC4094 ×4 (32 outputs), BU4094 ×3 |
| Electronic volume | P56, P57, P60, P61 | TC94A32F, TC9459F |
| Front panel input | P00/P01 vol encoder, P106/P107 input encoder, P103–P105 key ADC, P82/INT0 IR | |
| Protection | P84/INT2 power-down, P83/INT1 protect, P20 temperature | |
| Sub µcom reset | P87 | M30624 RESET |

Sub µcom M30624 (DI IC251):

| Link | Pins | Peer |
|---|---|---|
| DSP host port | P95 CLK, P96 out, P97 in, P101 CS, P103–P104 FLAG0–2 | ADSP-21366 SPI **[verify]** |
| DSP control | P106 DSPRST, P105 DSPROMRST, P100 DSPOSCON, P87 DSPBOOT (in), P11 VPP (L = flash write) | DSP + LH28F160 |
| PLD control | P74 CLK, P75 DATA, P76 CS main, P77/P80/P81/P84/P86 VSEL0–4 | EPM570 / LC4064V |
| HDMI | P70/P71 I²C, P36/P37 Rx reset, P35 Tx reset, P40–P43 SCDT/INT, P44/P46/P47 EEPROM WP | SiI9031 ×2, SiI9030 |
| DIR | P90–P94, P00–P10 | LC89057W ×3 |
| DAC / ADC | P24–P33, P56, P57 | PCM1791 ×4, AK4385 ×2, PCM1804 |
| External serial | UART1 P66/P67 | "data transfer to outside" |
| Emulator | P64 BUSY, P65 SCLK | Renesas debug **[verify]** |

## Boot-mode and rewrite pins

Both Renesas µcoms carry the standard flash rewrite pins:

| µcom | CNVSS | P50/CE | P55/EPM | Manual text |
|---|---|---|---|---|
| Main M30879 | pin 9 | pin 46 "H for rewrite boot" | pin 41 "L for rewrite boot" | L = normal single-chip |
| Sub M30624 | pin 7 | pin 44 | pin 39 | same |

Serial I/O pins for standard serial I/O mode per datasheet **[verify]**. Whether these
nets reach a header or test pads must be checked on the PWB pages (54–65), which are
images in the PDF.

## Service modes (manual-documented)

| Keys held at power-on | Effect |
|---|---|
| SURROUND PARAMS + STATUS, then STATUS | Shows firmware revision info (read-only) |
| NIGHT + PURE DIRECT | Factory reset (all user settings lost) |
| DSP SIMULATION + STATUS | Video adjustment mode |

## Firmware update path

- Windows tool `AVR-4306_upgrade_6_0_0_x.exe`, wired Ethernet, PC fixed at 192.168.0.2/24
  (or DHCP), ~15 min, settings reset afterwards.
- Versions on hand (updater file dates): 6.0.0.2 (2006-08), 6.0.0.3 (2008-06), 6.0.0.4
  (2008-10). Upgrade manual dated 2008-09-12 names 6.0.0.4 as current for AVR-4306.
- Separate network-module recovery package `FWCV_4306_VR002_SETUP` (InstallShield, 2006-06).
- `SSManage4306.EXE` (2005) and `original_AVR-4306.bid` (8960 B, header `4306EU0099`):
  purpose not yet established; the .bid looks like a settings/parameter dump.
- Contents of all of the above not yet analysed.

## Control protocol (doc Ver. 4.6a)

- RS-232: DB-9 DCE, 9600 8N1, ASCII `CMD+PARAM+CR`, max 135 B.
- Ethernet: **TCP 23 (telnet), no authentication documented.** Same command set.
- Response within 200 ms; wait 4 s after `PWON`.
