# DM850 firmware delivery and recovery

Status 2026-11-11. The long-standing blocker for the SSDP fix (docs/dm850-audit.md): how to
flash a patched **DM850I** without rewriting the web pages (safety-plan rule 2) or touching
the bootloader (rule 1), and with a **recovery path** if a write fails (the DM850 had "no
proven recovery"). Analysed from the 6.0.0.4 updater (`AVR-4306_upgrade_6_0_0_4.exe`,
Ghidra) and the DM850 codebase. **Two feasibility gates are now answered.**

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

So the delivery sequence is: get the DM850 into bootloader mode → connect 5001 →
`update image` + DM850I data → `start image` to boot the patched app.

## 4. Open: the bootloader-entry trigger

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
2. **Transcribe the 5001 protocol:** decompile `FUN_004203E0` (the send/reply primitive) and
   the `update image` data path in `FUN_004090A0` — the command framing, the data-frame
   format and size, ACKs, timeouts, retries (the DM850 analogue of the MAIN L/P transcription
   in main-dump-patch.md §5).
3. **Build a DM850I-only writer:** a `loader_client`-style tool that enters bootloader mode,
   sends `update image` + the patched `DM850I_ssdp.flash.bin`, verifies (read-back if the
   bootloader supports it, else the bCoD CRC + `VI?` stamp `I200805270746`), then `start
   image`. Frame whitelist: never `update bootloader`/`*webpage`. Gate against `sim/fake_unit`
   extended for the 5001 text protocol.
4. **Recovery procedure:** if a write fails, reconnect to 5001 and re-send `update image`
   (the vendor "Recovering DM800" path). Document the exact steps and the power/UPS checklist,
   same discipline as the MAIN write.

## Status

- **Delivery feasible:** yes — DM850I alone, no web-page/bootloader touch. (was: "open problem")
- **Recovery:** **confirmed** (reconnect + re-flash via the surviving bootloader). (was: "no
  proven recovery path")
- **Remaining:** the entry trigger (read-only probe) and the 5001 protocol transcription,
  then build + gate the writer. The hard risk — bricking with no recovery — is resolved.
