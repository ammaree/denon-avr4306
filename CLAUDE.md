# denon-avr4306 — project context

## Scope

- Reverse-engineering and a firmware fix for the **Denon AVR-4306** AV receiver (target
  firmware 6.0.0.4). The headline result is a fix for the DM850 network module's SSDP crash
  that drops the receiver's LAN connectivity (`docs/lan-hang.md`).
- Do all hardware testing on **a unit you own, on your own LAN**. No third-party equipment.

## Safety

- Hardware-safety-first: see `docs/safety-plan.md` (hard rules, per-write checklist, recovery).
  Every flash write is gated, verified, and recoverable; the DM850B bootloader is never written.
- The original Denon firmware (vendor updater, extracted images, any on-unit dumps) is Denon
  copyright and is **git-ignored — never commit it**. The repo distributes only our own patch
  and tooling (`docs/dm850-delivery.md`, patch-only model).

## Working notes

- Run anything that reaches the unit with the system Python (`/usr/bin/python3`): a package-
  manager Python may be blocked from the LAN by the OS's Local Network permission until allowed.
- The DM850 flash is written over TCP 5001 + a TFTP WRQ push on UDP 69 (no sudo needed — see
  `docs/updater-protocol.md`). It cannot be read back over the network.
