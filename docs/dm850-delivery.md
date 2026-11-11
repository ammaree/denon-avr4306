# DM850 firmware delivery and recovery

Status 2026-11-11. The long-standing blocker for the SSDP fix (docs/dm850-audit.md): how to
flash a patched **DM850I** without rewriting the web pages (safety-plan rule 2) or touching
the bootloader (rule 1), and with a **recovery path** if a write fails (the DM850 had "no
proven recovery"). Analysed from the 6.0.0.4 updater (`AVR-4306_upgrade_6_0_0_4.exe`,
Ghidra) and the DM850 codebase. **DONE: the patched DM850I was flashed and the SSDP fix
verified on the unit 2026-11-11 — see the Status section at the end. Sections 1–5 are the
analysis that led there; the key correction since is that the TFTP transfer is a host→DM850
PUSH (WRQ), not a pull.**

## 1. DM850I can be written alone (delivery is safe)

The web-page rewrite is **not** inherent to writing DM850I. The updater's DM850 loop
(`FUN_004090A0`, TCP 5001) processes each image by its flags; the `erase webpage` +
`update webpage` calls (`FUN_0041FEE0`/`FUN_0041FD90`) fire only for **DM850W/DM850D**
images present in the container (loader-interface.md §2.8). A writer that sends **only the
DM850I `update image`** sequence touches neither the web pages (rule 2) nor the bootloader
(rule 1). This is the same shape as the MAIN "own L/P writer" solution.

## 2. Recovery is confirmed and robust (the key de-risker)

The "Recovering DM800" function (`FUN_004065B0`) is short and decisive: on a DM850 that is
in bootloader mode it simply **reconnects to port 5001 and re-runs the write loop**
(`FUN_004090A0`) to re-flash the image. So **the DM850 bootloader survives a failed image
write and accepts a re-flash.** This is a real recovery net — unlike MAIN, whose Gate A
(does the resident loader recover a blank app?) is still uncertain. A failed DM850I write is
recoverable by reconnecting and writing again, as long as the bootloader (DM850B, which we
never write) is intact.

## 3. The protocol: text commands on port 5001

The DM850 bootloader speaks **ASCII command strings** over the 5001 socket, not the
AA-framed µcom protocol. `FUN_0041FBC0(cmd)` sends a NUL-terminated string via
`FUN_004203E0(cmd, len)` and checks the reply. The command vocabulary (strings in the
updater, 0x41F1CF–0x42016F):

| Command | Effect |
|---|---|
| `start bootloader` | reboot the DM850 into **bootloader mode** ("Reboot(Bootloader Mode)...") — listens on 5001 |
| `start image` | reboot into the **application** ("Reboot(Application Mode)...") |
| `update image` | **flash DM850I** (the one we want) |
| `update image cne` | flash DM850I with a cne variant |
| `erase image` | erase the DM850I region |
| `update bootloader` / `erase webpage` / `update webpage` | **forbidden** (rules 1–2) — never sent |
| `start tftp client` | TFTP download path (alternative transfer) |

**The image bytes go over TFTP, not 5001 — as a PUSH.** `FUN_00420FF0` creates a UDP socket,
binds an ephemeral local port, and sets its destination to the **DM850 at port 69**
(`getservbyname("tftp")`); `FUN_004207C0` then emits opcode **2 (WRQ)** + filename + `octet`
and `FUN_00420A90` emits opcode **3 (DATA)** blocks. So the **DM850 is the TFTP server** on
UDP 69 and the host is the **client that writes (pushes)** the image to it — not a pull.
(Earlier revisions of this file said "the updater is the server; the DM850 pulls"; that was
wrong, corrected by the decompile and confirmed on the unit 2026-11-11.) The 5001 text channel
orchestrates.

So the delivery sequence is (verified on the unit): bootloader `#` on 5001 → `erase image`
(`ok`) → `update image` (the unit erases + auto-arms its TFTP receiver, printing
`start tftp client`) → the host **pushes** `DM850I_<code>.bcd` to the DM850 by TFTP WRQ →
the unit returns `ok` → `start image` to boot the patched app. Full map:
docs/updater-protocol.md.

## 4a. On-unit read-only probes (2026-11-11) — entry resolved

Two read-only probes on the unit (`tools/dm850_probe.py`, connect/recv only, no commands):

- **The 5001 shell exists and is a `>` line shell.** Connecting to 5001 returns `>`; a bare
  newline returns `\r\n>`. This is exactly the vendor bootloader shell (`>` prompt, `\r\n`
  terminated commands) — RO test 2 confirmed.
- **5001 is served by the running DM850 image, at ~40 s into boot.** A clean off→on watch
  logged all ports **closed** while off, then (clean boot): port **80 at t=38.6 s**, then
  **5001/5000/23 together at t=40.3 s**. So 5001 is not a separate early bootloader window —
  the image brings up the `>` shell alongside the web (80) and telnet (23) servers.
- **Reconciles the old "5001 closed" reading.** On 2026-11-05 the DM850 was hung (the SSDP
  crash) when probed, so every port was down. Healthy and bridge-off, it serves 5001 fine.

**Entry mechanism (resolved):** connect to the image's 5001 `>` shell (reliably up ~40 s
after power-on), then send `start bootloader` to reboot into the flash bootloader for
`update image` + TFTP. The writer's `--enter-bootloader` does exactly this. Sending
`start bootloader` reboots the module (takes LAN control down until done), so it belongs to
the gated write phase, not a read-only probe.

## 4. The bootloader-entry trigger (background)

"Checking DM800" (`FUN_004060B0`) connects to 5001 with a 5 s wait and up to 3 retries, and
a state check (`FUN_004200B0` sends the handshake command strings). It does **not** send
`start bootloader` first — so the DM850 is expected to already be (or be entering) bootloader
mode. The remaining question is exactly what opens that window: the strings `RESETFLOW`,
`STATE RESET`, `STATE L_RESET`, `Reboot(Update Mode)...` and the retry/Sleep pattern are
consistent with the **bootloader listening briefly at boot/reset**, which the updater catches
after a reset. Candidates, to confirm on the unit (read-only):

1. A power-cycle opens the bootloader's boot window; connect to 5001 during it.
2. The MAIN update agent's mode 0x0C ("DM850 relay", loader-interface.md §1.4b) signals the
   DM850 to reboot into bootloader mode over the MAIN↔DM850 link.
3. `start bootloader` sent over the running image's own channel (web/telnet/UPnP), then it
   reboots into bootloader mode.

This is the one piece still to pin before a writer can be built; it is a read-only probe
(power-cycle, then watch whether 5001 opens), not a flash.

## 5. Plan

1. **Probe the entry (read-only):** power-cycle the unit and connect to TCP 5001 during the
   first seconds of boot; if it accepts, the bootloader listens at boot (candidate 1) and no
   trigger is needed. Record the boot-window timing. If not, test candidate 3 (`start
   bootloader` over the web/telnet) and candidate 2.
2. **Transcribe the orchestration:** the 5001 command channel is raw ASCII `send()`
   (`FUN_004203E0`) + reply — already understood. Pin the exact command sequence and the
   handshake order (`STATE RESET;`/`RESETFLOW`, then `start tftp client`/`update image`) and
   the TFTP filename/model code the DM850 requests (`<model>_%04X.bcd`), by decompiling the
   `update image` branch of `FUN_004090A0` and the TFTP server loop (`FUN_00420FF0` ff.).
3. **Build a DM850I-only writer:** a tool that (a) enters bootloader mode, (b) is a **TFTP
   client that pushes (WRQ)** the patched `DM850I_ssdp.flash.bin` to the DM850 on UDP 69, (c)
   sends the 5001 orchestration commands, (d) verifies functionally (`VI?` reads `I unknown`
   for DM850I, so confirm via the SSDP survival test + the bCoD CRC, not the stamp), then
   `start image`. Command whitelist: never `update bootloader`/`*webpage`. Gate against
   `sim/fake_dm850.py` (a 5001 `#` responder + a TFTP server that receives the WRQ).
4. **Recovery procedure:** if a write fails, reconnect to 5001 and re-send `update image`
   (the vendor "Recovering DM800" path). Document the exact steps and the power/UPS checklist,
   same discipline as the MAIN write.

## Status — DONE (flashed & verified 2026-11-11)

- **Delivery:** done — DM850I alone, no web-page/bootloader touch.
- **Recovery:** confirmed and exercised — a power-cycle returns the unit to the `#` bootloader
  (the app image being erased/invalid); the DM850B bootloader is never addressed and survived
  every cycle. A failed/aborted TFTP leaves the unit hung until a power-cycle.
- **Writer: `tools/dm850_writer.py`** — port-5001 `#` shell + **TFTP client that pushes (WRQ)**
  the image to the DM850 on UDP 69, hard command whitelist (`erase image`, `update image`,
  `start tftp client`, `start bootloader`, `start image` only — never `update bootloader`/
  `*webpage`), image sha256 pin, `--confirm-write`, and a `--probe-wrq`/`--wrq-only` mode that
  confirms the unit ACKs the WRQ without writing data. Offline test: `sim/test_dm850_writer.py`
  against `sim/fake_dm850.py` (now a TFTP server receiving the WRQ).
- **On the unit:** `erase image`→`ok`, `update image`→auto-arm, WRQ accepted (ACK block 0),
  all 4195 DATA blocks (2,147,328 B) ACKed, `ok`, `start image` → app booted (80/23/5000 up,
  5001 `>`). Then verified fixed: survived 15 Belkin `M-SEARCH` killer packets (ALIVE past
  +40 s). Build identity is confirmed functionally — `VI?` shows `I unknown` for DM850I
  (placeholder), not the bCoD stamp (docs/VERSIONS.md).
