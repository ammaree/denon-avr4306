# MAIN code flow and RAM map

Status 2026-11-06, iteration 1. Human-readable companion to the Ghidra codebase
(docs/main-codebase.md) and the annotation map (docs/main-names.tsv, applied to the
project by `tools/ghidra/ApplyNames.java`). Grows each RE iteration. Addresses are in the
full image `MAIN_01.00.full.bin` (0xF00000-0xFFFFFF).

## Image layout

| Region | Contents |
|---|---|
| `0xF00000-0xFFBFFF` | Application: AV control, serial protocol, setup menu, update agent |
| `0xFFC000-0xFFFFFF` | Resident boot block: reset, startup, the vendor loader, fixed vectors |
| `0xFFBE80` | Identity block (model, `Ver01.00`); VI? version source |
| `0xFFBF00` | Application interrupt vector table (64 entries) |
| `0xFFFFDC-0xFFFFFF` | M32C fixed vectors; RESET (`0xFFFFFC`) -> `0xFFC000` |

## Boot / entry flow

```
RESET vector 0xFFFFFC -> boot_reset_entry 0xFFC000 (resident loader / startup)
  -> C-startup (sets SP/SB/FB, inits RAM)
  -> jump to app_cold_boot_entry 0xF00000 (normal boot; no app checksum, loader-interface.md)
       -> application init, then the main loop
```

The update agent (a separate resident task that handles vendor flash updates) has its own
UART1 path (`agent_uart1_rx_isr` 0xF01704, `agent_rx_dequeue` 0xF01242) and INTB table at
`0xFFBD7C`; it is not the AV application (control-protocol.md correction).

## Application init + super-loop (`app_cold_boot_entry` 0xF00000)

The firmware is a classic **super-loop**. `app_cold_boot_entry` 0xF00000:

```
if (RAM 0x0400 != 0x1B) { RAM 0x0400 = 1; flag = cold }  else { flag = warm }  // init marker
app_init 0xF04190(flag)                                                        // + more init
... one-time init ...
main_loop 0xF0003D:
  do {
    loop_tick_01 0xF09284; loop_tick_02 0xF0419C; loop_tick_03 0xF0A32A;
    loop_tick_04_pwr_zone 0xF0227A; loop_tick_05 0xF06BD6; ... (17 ticks total) ...
    loop_tick_17 0xF732D4;
    FSET I;                                   // enable interrupts
    r0 = clamp(RAM 0x0400 - 3, 0..0xC);       // mode selector
    INDEXWD / JMPI  -> indexed mode dispatch   // per-mode work
  } while (1);
```

So each pass runs 17 fixed subsystem ticks, re-enables interrupts, then does an
indexed-by-mode dispatch keyed on RAM `0x0400`. The serial command engine, the setup menu
and the display are driven from these ticks and the mode dispatch. The 17 tick functions
are named `loop_tick_01..17` (roles to be identified in later iterations); `loop_tick_04`
is the power/zone tick (`0xF0227A`, previously mislabeled as a PW sub-handler).

**Correction:** `0xF02332` (`pwr_is_on`) is a one-line power-state query — `return (0x320C
& 0x10) != 0` — called from ~30 sites, not the full PW command handler. The earlier trace
(control-protocol.md) reached it as the leaf of the PW path, but it is a shared query.

## Serial control protocol flow (the main external surface)

Two byte-serial links feed the same command engine: UART1 is the rear RS-232 port, UART0 is
the DM850 network link (so telnet/TCP commands arrive here).

```
UART1 RX ISR / UART0 RX ISR
  -> uart1_rx_assemble 0xF4BA26  (line buffer 0x4A45, index 0x5277, saturates at 0x86)
     uart0_rx_assemble 0xF4BBF2  (line buffer 0x528E, index 0x5317, saturates at 0x86)
  -- on CR (0x0D): mark line ready --
  -> cmd_per_line_step 0xF45EEC   (main-loop step, per ready line)
       -> cmd_token_dispatch 0xF4B42E   via tok_table 0xF87C3E     (2 chars -> id)
       -> cmd_process 0xF4B1C0          (id -> internal via id_to_internal 0xF87BE2 -> handler)
       -> cmd_build_response 0xF46172   -> response via response_strings 0xF84E10
       -- then clears the line buffer (0x87 bytes) --
```

Bound: the RX index saturates at `0x86`, so neither line buffer overflows — the remote
attack surface (telnet -> DM850 -> UART0, and rear RS-232) is not overrun-able at MAIN
(docs/main-audit.md §1). Unknown token -> id 0 -> dropped.

Example handler: `handle_PW` 0xF02332 (power), which drives the power/zone state bytes and
calls `pw_sub_a`/`pw_sub_b`. Most other handlers are inline status queries in `cmd_process`.

## Front-panel setup menu / display flow

```
setup-menu display dispatch
  -> menu_builder_table 0xF7E035 [item index] -> a line builder, e.g.
       menu_line_build_dimmer 0xF17F4E (index 2)
         reads staged value menu_staged_value (RAM 0x40A6, 0..3)
         string = dimmer_strings 0xF80872 + level*16   -> "DIMMER: N"
         disp_copy 0xF1B270 -> display line buffer (RAM 0x414E)
```

The menu's **staged value** (RAM `0x40A6`) is a shared scratch byte: each item's value is
staged into it before its line builder runs; the dimmer stages `3 - level`. Many builders
read it (`menu_value_bits` 0xF1360C treats it as a bitfield; `menu_group_build*` read it as
a value). The dispatch that stages it and the builder table are runtime-indexed, so the
setter/apply are not statically reachable (docs/main-audit.md §3).

## RAM map (pinned so far; RAM is not in the Ghidra flash image)

| RAM | Name | Role |
|---|---|---|
| `0x08A9` | cfg_dimmer_level | Persistent dimmer level, 0=off..3=brightest (settings block; pinned on the unit) |
| `0x18FF`, `0x2701` | settings checksums | Track changes to the settings block `0x040C-0x2701` |
| `0x40A6` | menu_staged_value | Setup menu's shared current-item value (scratch) |
| `0x414E` | disp_line_buffer | Setup-menu display line buffer |
| `0x4A45` | uart1_line_buffer | UART1 (rear RS-232) received-line buffer (~0x87 B) |
| `0x528E` | uart0_line_buffer | UART0 (DM850 link) received-line buffer |
| `0x5277` / `0x5317` | rx line index | UART1 / UART0 line length, saturates at `0x86` |
| `0x320B`/`0x320C`/`0x320F` | power/zone state | Read/written by `handle_PW` |

## Not yet traced (next iterations)

- The main loop body and the task/ISR schedule (from `app_cold_boot_entry`).
- The remaining command handlers (MV, SI, MS, tuner, zones) — leaf handlers beyond PW.
- The setup-menu dispatch (what stages `0x40A6` and the confirm/apply path) and the
  front-panel/IR key input queue (the route for a remote dimmer command, main-audit.md §3).
- The SUB/DSP link protocol and the VFD output path.
