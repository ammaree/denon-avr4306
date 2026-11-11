# No-flash workaround — stop the crashes without touching firmware

The receiver's network module crashes when it receives one specific **SSDP `M-SEARCH`** packet
(UDP port 1900) — a UPnP/DLNA discovery request with a malformed service name, typically sent by
a smart TV, media player, or "cast" device on your network. If you **keep that packet away from
the receiver**, it stops crashing. This changes nothing on the receiver and is fully reversible.

This is the zero-risk option. It is a *network-side band-aid*, not a cure: if a new UPnP device
later reaches the receiver on UDP 1900, it can still hang it. The [firmware fix](../README.md)
removes the cause. Pick whichever you're comfortable with.

First, find your receiver's **IP address** (and ideally its **MAC**, which starts `00:05:CD` for
Denon/D&M) — it's on the receiver's Network setup screen, or in your router's device/DHCP list.
Give it a **DHCP reservation / static IP** so it doesn't move.

## Option A — block UDP 1900 to the receiver (most targeted, recommended)

Add one firewall rule on your router: **drop UDP traffic with destination port 1900 going to the
receiver's IP.** Nothing else on your network is affected.

- **OpenWrt** (Network → Firewall → Traffic Rules): protocol UDP, destination the AVR's IP, dest
  port 1900, action **drop**. Or `uci`/`iptables`: `iptables -I FORWARD -p udp -d <AVR-IP> --dport 1900 -j DROP`.
- **MikroTik / RouterOS**: a bridge-filter or IP-firewall rule dropping UDP dport 1900 to the
  AVR. Bridge filter (if the AVR is on the bridge): `/interface bridge filter add chain=forward
  action=drop mac-protocol=ip ip-protocol=udp dst-port=1900 ...` targeting the AVR; or
  `/ip firewall filter add chain=forward action=drop protocol=udp dst-port=1900 dst-address=<AVR-IP>`.
- **pfSense / OPNsense**: a firewall rule on the LAN: protocol UDP, destination = AVR IP/alias,
  destination port 1900, action **block**.
- **Consumer routers** without per-device firewall rules: use Option B or C instead.

> Note: SSDP is normally a **multicast** protocol (to `239.255.255.250:1900`). The killer packet
> has also been seen as a **unicast** request straight to the receiver. Block **both** — a rule
> on the receiver's IP covers unicast; also disabling UPnP (Option B) or VLAN isolation (Option
> C) covers the multicast path. Combining A + B is belt-and-braces.

## Option B — disable UPnP / SSDP on your router (quick, coarser)

Most routers have a **UPnP** on/off toggle (often under NAT/Forwarding or Advanced). Turning it
off stops the router relaying SSDP discovery and usually stops the crashes. Trade-off: other
devices that rely on **UPnP automatic port-forwarding** (some games, P2P apps) may need manual
port-forwards afterwards. It does not affect normal internet use.

## Option C — put the receiver on its own VLAN / isolated segment (most robust)

If you have a managed switch or a router with VLANs, place the receiver on a **VLAN that doesn't
carry UPnP/SSDP multicast** from your TVs and media devices. Several owners report this ends the
problem completely. It's the most work but the most thorough network-side fix.

## What you're NOT losing

The receiver barely uses UPnP usefully anyway (Denon's own notes say these AV components aren't
UPnP-compliant). Blocking SSDP to it does not affect normal control (the Denon app, telnet/IP
control on port 23, web page, AirPlay where present) — those don't depend on it answering SSDP
discovery.
