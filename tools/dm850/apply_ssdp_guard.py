#!/usr/bin/env python3
"""Assemble the DM850 SSDP guards and apply them to a copy of DM850I.

Three BLs into two caves (docs/dm850-audit.md §4), none sent to the unit:

- ssdp_guard.S cave (0x601CE800) — the per-arm guard. Both the service arm
  (0x60049B36, §1) and the device arm (0x60049AD0, §2) hold the same two bytes and
  BL here. On the non-zero path it does the original subtract and returns via bx lr
  to whichever site called it; on the zero path (a URN name with no version colon)
  it branches to 0x60049B77 (movs r0,#0 and the type-switch epilogue), so neither
  reply builder runs.
- msearch_guard.S cave (0x601CE820) — the dispatch pre-check. receiveData BLs here
  (0x60136174) just before Disc_Srv_Search_Req; it drops an M-SEARCH whose ST value
  length (r2) is over 0x40, which keeps both reply copies inside their frames. This
  is the second line of defence in front of the per-arm guards.

The vendor image is not modified. The patched copy is written under build/patch/
(git-ignored) and its three bCoD CRCs are recomputed.

  python3 -I tools/dm850/apply_ssdp_guard.py
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
IMAGE = os.path.join(ROOT, 'build', 'images', 'DM850I_x.flash.bin')
OUT = os.path.join(ROOT, 'build', 'patch', 'DM850I_ssdp.flash.bin')

# Version stamp (docs/VERSIONS.md). The bCoD build stamp at header 0x08 is 14 ASCII
# digits YYYYMMDDhhmmss; VI? reports it to the minute as `I` + YYYYMMDDhhmm. Patched
# builds advance the minute by the patch revision so a flashed unit is self-identifying.
# Vendor 20080527074501 -> VI? I200805270745. Rev 1 (this build) -> I200805270746.
STAMP_OFF = 0x08
VENDOR_STAMP = b'20080527074501  '
PATCHED_STAMP = b'20080527074601  '    # rev 1: minute 45 -> 46

# Big-copy mapping: file offset = 0x161EC + (VA - 0x60008000).
SDRAM = 0x60008000
FILE_DELTA = 0x161EC - SDRAM

# Each guard: a cave assembled from one source, and the sites that BL to it. Every
# site in a guard must hold the same `site_bytes` (the instructions being replaced).
GUARDS = [
    {'name': 'urn', 'src': 'ssdp_guard.S', 'cave': 0x601CE800,
     'site_bytes': bytes.fromhex('801b0704'),          # subs r0,r0,r6; lsls r7,r0,#16
     'sites': {'service': 0x60049B36, 'device': 0x60049AD0}},
    {'name': 'msearch', 'src': 'msearch_guard.S', 'cave': 0x601CE820,
     'site_bytes': bytes.fromhex('9d98331c'),          # ldr r0,[sp,#0x274]; adds r3,r6,#0
     'sites': {'dispatch': 0x60136174}},
]


def file_off(va):
    return va + FILE_DELTA


def enc_bl(pc, target):
    off = target - (pc + 4)
    if off % 2 or not (-(1 << 24) <= off < (1 << 24)):
        raise SystemExit(f'BL from {pc:#x} to {target:#x} is out of range')
    s = (off >> 24) & 1
    i1 = (off >> 23) & 1
    i2 = (off >> 22) & 1
    imm10 = (off >> 12) & 0x3FF
    imm11 = (off >> 1) & 0x7FF
    j1 = (~(i1 ^ s)) & 1
    j2 = (~(i2 ^ s)) & 1
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = 0xD000 | (j1 << 13) | (1 << 12) | (j2 << 11) | imm11
    return struct.pack('<HH', hw1, hw2)


def assemble(src_path, obj):
    """Prefer arm-none-eabi-gcc; clang's arm-none-eabi target is the fallback."""
    gcc = ['arm-none-eabi-gcc', '-mthumb', '-march=armv5t', '-c', src_path, '-o', obj]
    clang = ['clang', '-target', 'arm-none-eabi', '-mthumb', '-march=armv5t',
             '-c', src_path, '-o', obj]
    which = subprocess.call(['sh', '-c', 'command -v arm-none-eabi-gcc >/dev/null'])
    cmd = gcc if which == 0 else clang
    subprocess.check_call(cmd)
    return cmd[0]


def text_bytes_file(obj, blob):
    """Pull .text out of the ELF. The cave is one section, including its literal."""
    d = open(obj, 'rb').read()
    if d[:4] != b'\x7fELF':
        raise SystemExit(f'{obj} is not an ELF object')
    e_shoff = struct.unpack_from('<I', d, 32)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', d, 46)

    def shdr(i):
        return struct.unpack_from('<IIIIIIIIII', d, e_shoff + i * e_shentsize)

    str_off, str_size = shdr(e_shstrndx)[4], shdr(e_shstrndx)[5]
    for i in range(e_shnum):
        h = shdr(i)
        name = d[str_off + h[0]:str_off + str_size].split(b'\0', 1)[0]
        if name == b'.text' and h[1] == 1:
            raw = d[h[4]:h[4] + h[5]]
            open(blob, 'wb').write(raw)
            return raw
    raise SystemExit(f'{obj} has no .text section')


def build_cave(guard):
    """Assemble one guard's source and return (cave_bytes, assembler_name)."""
    base = os.path.join(ROOT, 'build', 'patch', guard['name'] + '_guard')
    cc = assemble(os.path.join(HERE, guard['src']), base + '.o')
    cave = text_bytes_file(base + '.o', base + '.bin')
    if len(cave) < 10 or len(cave) > 48:
        raise SystemExit(f"{guard['name']} cave is {len(cave)} bytes, expected a short fragment")
    return cave, cc


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    image = bytearray(open(IMAGE, 'rb').read())
    # Version uptick (before the CRC fix, which covers the header stamp).
    if bytes(image[STAMP_OFF:STAMP_OFF + len(VENDOR_STAMP)]) != VENDOR_STAMP:
        raise SystemExit(f'build stamp is {bytes(image[STAMP_OFF:STAMP_OFF+16])!r}, '
                         f'expected the vendor stamp {VENDOR_STAMP!r}')
    image[STAMP_OFF:STAMP_OFF + len(PATCHED_STAMP)] = PATCHED_STAMP
    placed = []
    assemblers = set()
    # Guard against two caves overlapping.
    occupied = []
    for guard in GUARDS:
        cave, cc = build_cave(guard)
        assemblers.add(cc)
        co = file_off(guard['cave'])
        span = (co, co + len(cave))
        for (lo, hi) in occupied:
            if span[0] < hi and lo < span[1]:
                raise SystemExit(f"{guard['name']} cave overlaps another cave")
        occupied.append(span)
        if any(image[co + i] != 0 for i in range(len(cave))):
            raise SystemExit(f"cave at {guard['cave']:#x} is not a zero run")
        image[co:co + len(cave)] = cave
        for site_name, site in guard['sites'].items():
            so = file_off(site)
            if image[so:so + 4] != guard['site_bytes']:
                raise SystemExit(f"{guard['name']}/{site_name} site {site:#x} is "
                                 f"{image[so:so+4].hex()}, expected {guard['site_bytes'].hex()}")
            bl = enc_bl(site, guard['cave'])
            image[so:so + 4] = bl
            placed.append((guard['name'], site_name, site, guard['cave'], bl, len(cave)))
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import bcod_sum
    fixed = bcod_sum.fix(bytes(image))
    probs = bcod_sum.check(fixed)
    if probs:
        raise SystemExit('CRC check failed: ' + '; '.join(probs))
    open(OUT, 'wb').write(fixed)
    print(f'assembler {" ".join(sorted(assemblers))}')
    print(f'version stamp {VENDOR_STAMP.strip().decode()} -> {PATCHED_STAMP.strip().decode()} '
          f'(VI? I{PATCHED_STAMP[:12].decode()})')
    for gname, sname, site, cave, bl, clen in placed:
        print(f'  {gname}/{sname} site {site:#x} -> cave {cave:#x} BL {bl.hex()}')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
