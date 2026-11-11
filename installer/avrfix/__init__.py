"""avrfix — guided installer for the Denon AVR-4306 DM850 SSDP crash fix.

Patch-only, DM850I-only. The engine (Shell/TftpPush/flasher) is lifted from the verified
tools/dm850_writer.py; the probes from tools/dm850_probe.py. No Denon firmware is bundled —
the owner's original image is obtained locally and patched with the byte-diff in data/.
"""
__version__ = "1.0.0"
