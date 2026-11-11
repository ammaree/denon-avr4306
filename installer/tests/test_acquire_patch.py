#!/usr/bin/env python3
"""Offline test of the patch-only pipeline: extract the owner's DM850I from the vendor updater,
apply the byte-diff, and confirm the result is the known-good patched image. Uses the local
(git-ignored) vendor images; skips gracefully if they are not present.

  /usr/bin/python3 -I installer/tests/test_acquire_patch.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.dirname(HERE)
REPO = os.path.dirname(INSTALLER)
sys.path.insert(0, INSTALLER)

from avrfix import acquire, image, patch, resources  # noqa: E402


def main():
    orig_path = os.path.join(REPO, "build", "images", "DM850I_x.flash.bin")
    if not os.path.exists(orig_path):
        print("SKIP: no local original image (build/images/DM850I_x.flash.bin)")
        return
    original = open(orig_path, "rb").read()
    assert image.sha256(original) == resources.original_sha256(), "local original sha mismatch"

    # patch applies cleanly and reproduces the known-good patched image
    patched = patch.apply_patch(original)
    assert image.sha256(patched) == resources.patched_sha256(), "patched sha mismatch"
    assert image.bcod_problems(patched) == [], "patched image failed bCoD CRC"

    # a wrong original is rejected
    bad = bytearray(original)
    bad[0x1000] ^= 0xFF
    try:
        patch.apply_patch(bytes(bad))
        raise AssertionError("patch accepted a wrong original")
    except Exception as e:
        assert "does not match" in str(e), e

    # acquire extracts the same original from the vendor updater, if present
    acquired = None
    for exe in (os.path.join(REPO, "build", "pkg_6.0.0.4", "AVR-4306_upgrade_6_0_0_4.exe"),
                os.path.join(REPO, "build", "pkg", "AVR-4306_upgrade_6_0_0_4.exe")):
        if os.path.exists(exe):
            acquired = acquire.extract_dm850i(exe)
            assert image.sha256(acquired) == resources.original_sha256(), "acquired sha mismatch"
            break

    print(f"OK: patch {len(patch.resources.load_patch()['runs'])} runs -> patched sha "
          f"{resources.patched_sha256()[:12]}…; "
          f"acquire {'verified from vendor updater' if acquired else '(no local updater, skipped)'}")


if __name__ == "__main__":
    main()
