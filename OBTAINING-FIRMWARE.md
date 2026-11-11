# Getting your firmware (the one extra step)

This project ships **no Denon firmware** — only our small fix (a "patch"). To keep everything
legal and above-board, the fix is applied to the firmware **you already own**, on your own
computer. The tool does the work; you just need to point it at Denon's official AVR-4306
updater once.

## The easy way

Run the tool and let it **auto-download** the official vendor updater (when a working link is
configured), or click **Browse** and select the updater you downloaded. The tool extracts the
network-module image, checks it against a known checksum, applies the fix, and verifies the
result — all locally. If anything doesn't match, it stops and tells you.

## Getting the vendor updater yourself

If the auto-download isn't available, download the **AVR-4306 firmware updater, version
6.0.0.4** and give its file to the tool. Good sources:

- Denon's official support/downloads site (search for "AVR-4306 firmware").
- The Internet Archive (archive.org) if the original page is gone.

The file is a Windows updater (an `.exe`, often inside a `.zip`). You do **not** need to run
it — the tool only reads the network-module image out of it. You can hand the tool the `.zip`,
the `.exe`, or an already-extracted `DM850I_x.flash.bin`.

### Checksum (so you know you have the right file)

The tool verifies automatically, but if you want to check by hand, the extracted network-module
image should have this SHA-256:

```
35ba4b01829b1588abb609463eab0fb97ce8aa4b96a4ec04cd4d3981badfa44e   DM850I_x.flash.bin
```

## If your receiver is on older firmware

The fix targets the **6.0.0.4** network-module image. If your receiver is on an older overall
firmware, run **Denon's official 6.0.0.4 update first** (the normal way), then apply this fix.
Writing the patched 6.0.0.4 image is what brings your network module up to date.
