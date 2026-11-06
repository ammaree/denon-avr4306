#!/usr/bin/env python3
"""Reconstruct the DM850I runtime memory image by replaying its scatter loader.

Shared by the disassembly dump and the Unicorn replay harness. No unit contact.
The scatter facts are the same ones LoadDm850.java uses (see docs/dm850-map.md):
the file loads as-is at VA 0x400DFFF4 (file offset = VA - 0x400DFFF4), the region
table at 0x400E0194 holds four offsets-from-itself, copy records are (src,dst,len)
and ZI records are (addr,len).
"""
import os

IMAGE_BASE = 0x400DFFF4            # BinaryLoader base: file offset = VA - IMAGE_BASE
REGION_TABLE = 0x400E0194

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VENDOR = os.path.join(ROOT, 'build', 'images', 'DM850I_x.flash.bin')
PATCHED = os.path.join(ROOT, 'build', 'patch', 'DM850I_ssdp.flash.bin')


def _u32(buf, off):
    return int.from_bytes(buf[off:off + 4], 'little')


def build(image_path):
    """Return (copies, zi): copies is a list of (dst_va, bytes), zi a list of
    (addr, len). Replays the scatter table the same way the ROM loader does."""
    data = open(image_path, 'rb').read()
    if data[:4] != b'bCoD':
        raise SystemExit(f'{image_path}: not a bCoD image')

    def fileoff(va):
        off = va - IMAGE_BASE
        if off < 0 or off > len(data):
            raise SystemExit(f'VA {va:#x} outside the file')
        return off

    r8 = REGION_TABLE
    base = fileoff(r8)
    copy_lo = _u32(data, base) + r8
    copy_hi = _u32(data, base + 4) + r8
    zi_lo = _u32(data, base + 8) + r8
    zi_hi = _u32(data, base + 12) + r8

    copies = []
    p = copy_lo
    while p + 12 <= copy_hi:
        src = _u32(data, fileoff(p))
        dst = _u32(data, fileoff(p + 4))
        length = _u32(data, fileoff(p + 8))
        p += 12
        if length == 0 or src == dst:
            continue
        if (src & 3) or (dst & 3):      # relative record; this image has none live
            continue
        s = fileoff(src)
        copies.append((dst, data[s:s + length]))

    zi = []
    p = zi_lo
    while p + 8 <= zi_hi:
        addr = _u32(data, fileoff(p))
        length = _u32(data, fileoff(p + 4))
        p += 8
        if length == 0 or (addr & 3):
            continue
        zi.append((addr, length))
    return copies, zi


# The one big code+data region (region 0). VA<->file for reading code directly.
SDRAM = 0x60008000
SDRAM_FILE = 0x161EC               # 0x400F61E0 - 0x400DFFF4


def sdram_fileoff(va):
    return va - SDRAM + SDRAM_FILE


if __name__ == '__main__':
    for name, path in (('vendor', VENDOR), ('patched', PATCHED)):
        if not os.path.exists(path):
            print(f'{name}: {path} missing')
            continue
        copies, zi = build(path)
        print(f'{name}:')
        for dst, blob in copies:
            print(f'  copy {dst:#010x} len {len(blob):#x} end {dst + len(blob):#010x}')
        for addr, length in zi:
            print(f'  zi   {addr:#010x} len {length:#x} end {addr + length:#010x}')
