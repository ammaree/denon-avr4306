# Safety — read this before you run the fix

This tool writes new firmware to the **network module** inside your Denon AVR-4306. That is
the part that gives the receiver its network/IP features. The rest of the receiver (sound,
front panel, remote) is a separate chip and is **not** touched.

## Before you start

- Use it only on **a receiver you own**, on your own network.
- Have the receiver **on** and connected to the same network as your computer (wired is best).
- **Stable power.** The write takes about a minute. If you have a UPS, use it. Don't run this
  during load-shedding or a thunderstorm.
- Give it 5–10 minutes and don't rush it.

## What is normal during the fix

- **The receiver's network will drop for about a minute while it writes.** This is expected —
  the tool says so on screen. Watch the progress; don't touch anything.

## If something goes wrong

- If the write is interrupted (a network glitch, you cancelled), the module may stop
  responding. **This is recoverable and is NOT a brick.** The module's own start-up program
  (its "bootloader") is never written by this tool, by design.
- To recover: **switch the receiver fully off at the wall, wait about 10 seconds, switch it
  back on, and run the tool again.** It will pick up where it left off. The tool also walks you
  through this automatically.

## The one real danger

- **Losing mains power *while it is writing* is the only thing that can truly break the
  module.** That's why stable power matters. Don't switch the receiver off during the write.

## Honest limits

- This fix was developed and verified on **one** AVR-4306 and one firmware version (6.0.0.4).
  Other regions or hardware revisions are untested. The tool checks your device and your
  firmware before it writes anything, and refuses if they don't match what it expects.
- There is **no warranty**. You use this at your own risk. See `DISCLAIMER.md`.
