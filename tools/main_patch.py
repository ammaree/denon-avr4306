#!/usr/bin/env python3
"""Build a patched MAIN 01.00 flash image with the read-only DM dump hook.

  python3 -I tools/main_patch.py build/images/MAIN_01.00.flash.bin build/patch/dm_dump.bin \
      build/patch/MAIN_dm.flash.bin

Changes exactly two places (docs/main-dump-patch.md):
  0xF4B1C0..0xF4B1C3   EC 0C 8F 28 (enter #0xc; pushm r2,a0)  ->  CC <hook LE24> (jmp.a)
  0xFA9700..           erased 0xFF                           ->  hook code
Refuses to run unless the original bytes and the erased area are exactly as expected,
and checks the result differs from the original only in those ranges.
"""
import hashlib, sys

BASE = 0xF00000
SITE = 0xF4B1C0
SITE_ORIG = bytes.fromhex('ec0c8f28')
HOOK = 0xFA9700
FREE_END = 0xFFBD7B          # last erased byte before the INTB table (loader-interface §1.5)


def main():
    src, hook_path, out = sys.argv[1:4]
    img = bytearray(open(src, 'rb').read())
    hook = open(hook_path, 'rb').read()
    if hashlib.sha256(img).hexdigest()[:16] != '0fcc83501f19dd4f':
        sys.exit('refused: input is not vendor MAIN 01.00')
    if img[SITE - BASE:SITE - BASE + 4] != SITE_ORIG:
        sys.exit('refused: patch site bytes differ')
    if img[HOOK - BASE:HOOK - BASE + len(hook)] != b'\xff' * len(hook):
        sys.exit('refused: hook area is not erased')
    if HOOK + len(hook) - 1 > FREE_END or hook[:4] != SITE_ORIG:
        sys.exit('refused: hook too large or does not start with the displaced prologue')
    orig = bytes(img)
    img[SITE - BASE:SITE - BASE + 4] = b'\xcc' + HOOK.to_bytes(3, 'little')
    img[HOOK - BASE:HOOK - BASE + len(hook)] = hook
    diff = [BASE + i for i in range(len(img)) if img[i] != orig[i]]
    allowed = set(range(SITE, SITE + 4)) | set(range(HOOK, HOOK + len(hook)))
    if not set(diff) <= allowed:
        sys.exit('internal error: change outside the two patch ranges')
    open(out, 'wb').write(img)
    print(f'{out}: {len(diff)} bytes changed '
          f'({SITE:06X}..{SITE + 3:06X}, {HOOK:06X}..{HOOK + len(hook) - 1:06X}); '
          f'byte sum {sum(img) & 0xFFFFFFFF:#010x} (vendor {sum(orig) & 0xFFFFFFFF:#010x}); '
          f'sha256 {hashlib.sha256(img).hexdigest()}')


if __name__ == '__main__':
    main()
