"""Guided command-line installer. Plain prompts, same event stream as the GUI.

  python -m avrfix            # guided run
  python -m avrfix --updater path/to/AVR-4306_upgrade_6_0_0_4.exe --ip 192.0.2.13
"""
import argparse
import os
import sys
import tempfile

from . import acquire, discovery, identify, patch
from .errors import AvrfixError
from .events import Info, Progress, Prompt, Result, Step
from .flasher import Flasher

BANNER = """\
================================================================
 AVR-4306 network-module fix  (community, NOT a Denon product)
 Fixes the SSDP crash that drops the receiver's LAN connection.
 Use only on a receiver you own. No warranty — see DISCLAIMER.md.
================================================================"""


def _on_event(ev):
    if isinstance(ev, Step):
        print(f"\n[*] {ev.human}")
    elif isinstance(ev, Info):
        print(f"    {ev.human}")
    elif isinstance(ev, Progress):
        pct = (ev.done * 100 // ev.total) if ev.total else 0
        bar = "#" * (pct // 4)
        sys.stdout.write(f"\r    writing [{bar:<25}] {pct:3d}%")
        sys.stdout.flush()
        if ev.done >= ev.total:
            sys.stdout.write("\n")
    elif isinstance(ev, Result):
        mark = "OK " if ev.ok else "!! "
        print(f"[{mark}] {ev.detail}")


def _yes(text):
    try:
        return input(text).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _ask(prompt: Prompt):
    print()
    print(prompt.human)
    if prompt.kind == "power_cycle_retry":
        try:
            input("Press Enter once you've switched it off and on again (Ctrl-C to cancel)… ")
            return True
        except (EOFError, KeyboardInterrupt):
            return False
    return _yes("Type 'yes' to continue: ")


def obtain_patched(args):
    """Return the patched DM850I bytes (patch-only): get the owner's original, patch it."""
    src = args.updater or args.image
    if not src and args.download:
        print("[*] Downloading the official vendor updater…")
        dest = os.path.join(tempfile.gettempdir(), "avr4306_updater.bin")
        acquire.download(args.download, dest,
                         progress=lambda d, t: sys.stdout.write(f"\r    {d} bytes") or sys.stdout.flush())
        print()
        src = dest
    if not src:
        print("\nTo apply the fix I need YOUR receiver's original firmware (the patch is applied to")
        print("firmware you already own — no Denon firmware ships with this tool). See OBTAINING-")
        print("FIRMWARE.md. Give me the official AVR-4306 6.0.0.4 vendor updater (.exe), a .zip of")
        print("it, or an extracted DM850I_x.flash.bin.")
        src = input("Path to the vendor updater / image: ").strip().strip("'\"")
    print("[*] Extracting your original DM850I image…")
    original = acquire.extract_dm850i(src)
    print("[*] Applying the SSDP fix patch locally…")
    return patch.apply_patch(original)


def choose_ip(args):
    if args.ip:
        return args.ip
    print("[*] Looking for your receiver on the network…")
    hits = discovery.find_denon()
    if hits:
        for i, h in enumerate(hits):
            print(f"    {i + 1}. {h['ip']}  ({h['mac']})")
        sel = input(f"Pick 1-{len(hits)}, or type an IP: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(hits):
            return hits[int(sel) - 1]["ip"]
        if sel:
            return sel
    print("    (none found automatically — macOS may block local-network access; see README)")
    return input("Enter the receiver's IP address: ").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Guided AVR-4306 DM850 SSDP-fix installer")
    ap.add_argument("--ip", help="receiver IP (skips discovery)")
    ap.add_argument("--updater", help="path to the vendor updater .exe / .zip")
    ap.add_argument("--image", help="path to an already-extracted DM850I_x.flash.bin")
    ap.add_argument("--download", metavar="URL", help="download the vendor updater from URL")
    ap.add_argument("--src-ip", help="source IP / interface for the TFTP push (advanced)")
    ap.add_argument("--served-name", default="DM850I_0011.bcd")
    args = ap.parse_args(argv)

    print(BANNER)
    try:
        patched = obtain_patched(args)
        print(f"[OK ] Patched image ready.")
        ip = choose_ip(args)
        rep = identify.check(ip)
        if rep["blocking"]:
            print("\n[!! ] " + " ".join(rep["blocking"]))
            return 2
        fl = Flasher(ip, patched, src_ip=args.src_ip, served_name=args.served_name,
                     on_event=_on_event, ask=_ask)
        result = fl.run()
    except AvrfixError as e:
        print(f"\n[!! ] {e}")
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1

    print()
    if result.ok:
        print("=" * 60)
        print(" FIXED — your receiver survived the test that used to crash it.")
        print("=" * 60)
        return 0
    print(f"Not completed: {result.detail}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
