# DM850 multiple simultaneous TCP control sessions — viability

Status 2026-11-06. Investigation only; nothing written to the unit. The goal is to
let a separate network-diagnosis project's appliance and a phone remote app both control the AVR at
the same time. Both drive the Denon control protocol over **Telnet TCP 23**
(CR-terminated ASCII, protocol v4.6a). Today the AVR accepts **one** telnet session.

## 1. Current behaviour (confirmed)

- The separate project's bench register R02: the AVR "accepts one session only" and holds a
  dead session until its TCP timeout; a second client is refused meanwhile. One run
  saw every telnet connect refused for 8 minutes while the web server still answered
  (external diagnosis notes, not in this repo).
- That is why the separate project's ADR-0001 makes the bridge the sole owner of the AVR
  session and forbids any other client (HA, the app, PuTTY) from touching port 23.

## 2. Root cause in the firmware (confirmed in the disassembly)

The telnet control server is BridgeCo's C++ "BridgeCo AG Telnet server" (strings at
`0x601B0974` ff.; `TelnetCmd`, `TelnetResponse`, `TelnetServer: InputDevice=%s`,
`Can't start TCP read thread`). It is **ARM** code, unlike the Thumb Denon app layer.
Reconstructed with `tools/dm850/dm850_mem.py` and decompiled with
`tools/ghidra/ForceArmDecompile.java` (forces ARM at an entry Ghidra had guessed as
Thumb).

Key functions:

| Address | Role |
|---|---|
| `0x600A1168` | `ServerSocket::acceptSocket` |
| `0x600CF???` (pool `0x600CF868`) | `ServerSocket::createSocket` — socket/bind/listen |
| `0x6012D8CC` | per-connection servicer (allocates the byte stream + the write/event thread, then runs the read loop, then tears both down) |
| `0x6015F084` | the telnet read/parse loop (IAC `0xFF`, cases `0xFA/0xFB/0xFD/0xFE`; forwards each command line to the sink vtable) |

**The single-session limit is deliberate, in `acceptSocket` (`0x600A1168`):**

```
if (listen_fd == -1) return 0;          // param_1+8 holds the listen fd
accepted = accept(listen_fd, &sa);      // func_0x6015bcd8
if (accepted == -1) { log; return 0; }
close(listen_fd);                       // func_0x6015c940  <-- closes the LISTENER
param_1+4 = accepted;                   // the one connection
param_1+8 = -1;                         // no listener any more
return 1;
```

The server accepts one client and immediately **closes its own listening socket**.
While that connection is up (or stuck until TCP timeout), nothing is listening on
port 23, so a second client is refused. Only after the connection is torn down
(`0x6012D8CC` frees the stream and the write thread) does the server loop back and
`createSocket` again. One server object (`param_1`) is reused per connection; the
command sink (`param_2`, the MAIN UART0 link) is a single shared object.

This is not a resource cap. The stack runs the GoAhead web server, UPnP/SSDP and
telnet at once, so a second TCP socket is not the blocker — the server simply stops
listening by design once it has a client.

## 3. What multi-session would require in the firmware

To accept two clients at once, the telnet server would have to be substantially
rewritten, not cave-patched:

1. **Keep the listener open.** Remove the `close(listen_fd)` / `listen_fd = -1` in
   `acceptSocket` and keep a real accept loop. That one change alone breaks the rest
   of the design, which assumes exactly one live connection per server object.
2. **N connection contexts.** `0x6012D8CC` fills a single server object
   (`param_1`, fields at +4 accepted fd, +0xE..+0x11 the stream/thread handles, +0x16
   the sink). A second client needs a second context and its own stream + write thread
   allocated from the heap (`func_0x6011E9A0`), plus a ThreadX thread start
   (`func_0x60156A28`) — roughly `0x60 + 0x400 + 0x2D0` bytes and ~2 threads per extra
   client.
3. **Serialise the MAIN command channel.** Both clients' command lines go to the one
   UART0 sink. Interleaving two line writers needs a mutex or a command queue in front
   of the sink; today there is none because there is only ever one writer.
4. **Broadcast events to all clients.** The AVR pushes `PW/MV/MU/SI/MS` events. The
   write/event thread (`puVar4` in `0x6012D8CC`) is bound to one connection. Events
   would have to fan out to every connected client's stream, which means a connection
   list the event source walks — new shared state with its own locking.

That is a rewrite of the server's lifecycle and new RAM structures, in hand-written
ARM, patched into a 20-year-old unit. (Recovery is now proven — power-cycle to the `#`
bootloader, `docs/dm850-delivery.md` — but a lifecycle rewrite is far riskier than the
narrow SSDP byte-patch that was flashed.) It also cannot be validated the way the SSDP guards were: the
replay harness (`tools/dm850/replay_ssdp.py`) exercises one pure function under
Unicorn, whereas this touches the socket layer, the scheduler and multi-thread timing
— an offline gate would have to emulate NicheStack and ThreadX, which is far larger
than anything built here. **High effort, high risk, weak offline assurance.**

## 4. Recommended alternative: multiplex on the bridge, not the AVR

The same user-visible result — the separate project and the phone remote app both controlling the AVR
at once — is reachable without touching AVR firmware, on a device that *is*
recoverable.

Run a **Telnet-23 multiplexer on the separate project's appliance**: a small server that
holds the one real session to the AVR (which the bridge already owns and parses,
`avr_denon` module, ADR-0001) and accepts several downstream clients. It serialises
their commands onto the single AVR session and broadcasts the AVR's events back to all
of them. The phone remote app is then pointed at the bridge's IP on port 23 instead of the AVR.

Why this is the better path:

- The bridge already maintains the AVR TCP session, parses the protocol, holds state
  and pushes events; the multiplexer is a thin front end over work it already does.
- It runs on a recoverable device (the separate project's ESP32 appliance / its host), not the
  unrecoverable AVR. A bug is a reflash, not a brick.
- It matches the separate project's existing architecture (ADR-0001, "the bridge owns every
  device session"); the AVR keeps its one session, held by the bridge.
- The command serialisation and event fan-out — the hard parts in §3 — are ordinary
  application code on the bridge, not ARM patches with no test gate.

Caveats:

- The phone remote app's core control is telnet; if it also uses the AVR's HTTP/UPnP endpoints for
  extras (artwork, browse), those aren't covered by a telnet proxy and would need
  separate handling or would still hit the AVR directly (web server is already
  multi-client).
- The bridge must present the protocol faithfully enough that the phone remote app accepts it
  (event formats, query replies). The bridge already speaks this protocol, so the gap
  is small, but it needs checking against the phone remote app.

## 5. Verdict

- **Firmware multi-session: possible but not advisable.** The limit is a deliberate
  `close(listen_fd)` after one accept, so it is understood, but lifting it means
  rewriting the telnet server's lifecycle (persistent listener, N contexts + threads,
  command serialisation, event broadcast) in ARM on a unit with no recovery path and
  no practical offline gate. Disproportionate risk for the goal.
- **Bridge-side multiplexer: the recommended route.** It delivers simultaneous
  the separate project + the phone remote app on recoverable hardware, reusing the session the
  bridge already owns, and fits the bridge's design. The work belongs in the
  separate project, not in this firmware.

## Key addresses (for any future firmware work)

- `0x600A1168` acceptSocket (the `close(listen_fd)` is the single-session cause)
- `0x600CF868` createSocket literal pool (socket/bind/listen just before)
- `0x6012D8CC` per-connection servicer; `0x6015F084` read/parse loop
- helpers: `0x6015BCD8` accept, `0x6015C940` close, `0x6011E9A0` alloc(size,flag),
  `0x60156A28` thread start, `0x6013557C` connection read
