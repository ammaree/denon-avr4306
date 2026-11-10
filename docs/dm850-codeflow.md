# DM850 code flow and architecture

Status 2026-11-10, iteration 1. Companion to the DM850 codebase (docs/dm850-codebase.md),
the annotation map (docs/dm850-names.tsv) and the memory/task map (docs/dm850-map.md).
Grows each RE iteration. ARM VAs in the reconstructed image.

## Stack and layout

The DM850 is BridgeCo's networking module running **ThreadX** (RTOS) + **NicheStack**
(TCP/IP) + **KnOS** and the BridgeCo platform (UPnP, streaming, GoAhead web server), with
Denon's application on top (docs/dm850-firmware.md). Image: ARMv5T, GCC 3.4.0, 2.1 MB.

```
bCoD entry dm850_reset 0x400E0080
  -> scatterload 0x400E00C8  (copy code/data to SDRAM 0x60008000 etc., clear ZI)
  -> KnOS / ThreadX init -> start the threads below
```

## Threads (docs/dm850-map.md §3)

| Thread | Entry / creator | Role |
|---|---|---|
| UPnP Disc | `upnp_disc_thread` 0x6004A788 | SSDP discovery: receives M-SEARCH, builds replies |
| UPnP TCP | `upnp_tcp_thread` 0x6006FA98 | UPnP control/eventing over TCP |
| Swap_Spaces | `swap_spaces_thread` 0x600459F4 | memory/space management |
| NapManager, NetCfg, PowerManager, WRC, Gena, GenaEvent, Cardea, SnapCfgProtocol, NetReconfigurator, LCDDisplay | started via the GTS stub 0x600E5A3C | config, eventing, web-remote-control, the display service |

All created through the ThreadX wrapper `threadx_create` 0x6011EA9C.

## Network surfaces (the LAN-facing attack surface)

### SSDP / UPnP discovery — audited, the LAN-hang fault

```
SSDP datagram (UDP 1900)
  -> upnp_receiveData 0x601360E0   (reject >=0x200, copy onto stack)
       -> req_prs_translate 0x60067050     (parse headers)
       -> udp_check_msearch 0x6006FCFC      (M-SEARCH validity; 0=continue)
       -> disc_srv_search_req 0x6004A114    (match ssdp:all/rootdevice/uuid/urn, classify ST)
            -> disc_srv_type_switch 0x60049A80  (service arm idx7, device arm idx5)
                 -> urn_service_reply 0x60070A5C / urn_device_reply 0x60070974
```

This is the path that crashes on a service/device `ST` with no version colon
(docs/dm850-audit.md §1-2); the fix is the guard caves `cave_urn_guard` 0x601CE800 and
`cave_msearch_guard` 0x601CE820 (built, gated, not flashed).

### Telnet control server (port 23) — single session by design

```
ServerSocket listen -> serversocket_accept 0x600A1168
  accept() one client, then CLOSE the listener (param_1+8 = -1)   <-- single-session cause
  -> telnet_conn_service 0x6012D8CC  (per-connection: stream + write thread)
       -> telnet_read_loop 0x6015F084 (IAC negotiation; forward command lines to the sink)
```

The sink forwards Denon control lines to MAIN. Because the listener is closed after one
accept, a second client is refused until the first disconnects (docs/dm850-multisession.md).

### GoAhead web server (port 80)

`GoAhead-Webs`; the `.asp` page handlers drive the same control command set. Not yet traced
to function level (next iteration).

## MAIN link (/dev/uart0)

```
control action -> denon_link_send 0x6004DA20   (send a Denon ASCII line to MAIN)
display dim     -> set_dim_psdim 0x60063BA4     (map 0..6 -> PSDIM 00..06 -> denon_link_send)
```

So the DM850 is a protocol bridge: LAN (SSDP/UPnP/web/telnet) in, Denon control lines to
MAIN out over UART0.

## NicheStack (TCP/IP) — the suspected INFRA:HALT surface

`pk_alloc` 0x60124BA4 (buffer allocator), `tcp_out` 0x6010CF24, `dhcp_got_addr` 0x600D43F4.
The pre-4.3 NicheStack INFRA:HALT class (TCP reassembly, DHCP, DNS, ICMP) is suspected
(dm850-audit.md §3) but not yet traced to instructions — an audit target now that the
codebase resolves these paths.

## Not yet traced (next iterations)

- The GoAhead `.asp` handlers and the web command path.
- The UPnP control/eventing (SOAP) parsing beyond discovery.
- The NicheStack receive paths (reassembly/DHCP/DNS/ICMP) for the §3 audit.
