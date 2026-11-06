#!/usr/bin/env python3
"""Assemble tools/dm850/ssdp_guard.S and apply it to a copy of DM850I.

The vendor image is not modified. The patched copy is written under build/patch/
(git-ignored) and its three bCoD CRCs are recomputed. Nothing is sent to the unit.

  python3 -I tools/dm850/apply_ssdp_guard.py
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC_S = os.path.join(HERE, 'ssdp_guard.S')
IMAGE = os.path.join(ROOT, 'build', 'images', 'DM850I_x.flash.bin')
OUT = os.path.join(ROOT, 'build', 'patch', 'DM850I_ssdp.flash.bin')

# Big-copy mapping: file offset = 0x161EC + (VA - 0x60008000).
SDRAM = 0x60008000
FILE_DELTA = 0x161EC - SDRAM
SITE = 0x60049B36          # subs r0, r0, r6; lsls r7, r0, #16
CAVE = 0x601CE800          # zero run 0x601CE424, length 0xC6C
SITE_BYTES = bytes.fromhex('801b0704')   # little-endian 1b80, 0407


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


def assemble(obj):
    """Prefer arm-none-eabi-gcc; clang's arm-none-eabi target is the fallback."""
    gcc = ['arm-none-eabi-gcc', '-mthumb', '-march=armv5t', '-c', SRC_S, '-o', obj]
    clang = ['clang', '-target', 'arm-none-eabi', '-mthumb', '-march=armv5t',
             '-c', SRC_S, '-o', obj]
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


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    obj = os.path.join(ROOT, 'build', 'patch', 'ssdp_guard.o')
    blob = os.path.join(ROOT, 'build', 'patch', 'ssdp_guard.bin')
    cc = assemble(obj)
    cave = text_bytes_file(obj, blob)
    if len(cave) < 16 or len(cave) > 32:
        raise SystemExit(f'cave is {len(cave)} bytes, expected a short Thumb fragment')
    bl = enc_bl(SITE, CAVE)
    image = bytearray(open(IMAGE, 'rb').read())
    so, co = file_off(SITE), file_off(CAVE)
    if image[so:so + 4] != SITE_BYTES:
        raise SystemExit(f'site {SITE:#x} is {image[so:so+4].hex()}, expected {SITE_BYTES.hex()}')
    if any(image[co + i] != 0 for i in range(len(cave))):
        raise SystemExit(f'cave at {CAVE:#x} is not a zero run')
    image[so:so + 4] = bl
    image[co:co + len(cave)] = cave
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import bcod_sum
    fixed = bcod_sum.fix(bytes(image))
    probs = bcod_sum.check(fixed)
    if probs:
        raise SystemExit('CRC check failed: ' + '; '.join(probs))
    open(OUT, 'wb').write(fixed)
    print(f'assembler {cc}')
    print(f'cave {CAVE:#x} ({len(cave)} bytes) site {SITE:#x} BL {bl.hex()}')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
