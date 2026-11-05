#!/usr/bin/env python3
"""Check / fix the BridgeCo 'bCoD' image header used by every DM850 image.

Layout (little-endian 32-bit words; validated on all seven DM850 images on hand:
DM850I 2006/2008, DM850IMG, FWCV DM850 11.22, DM850W 2006/2008, DM850D):

  0x00  'bCoD'            0x04  header version (1)
  0x08  build stamp, 14 ASCII digits YYYYMMDDhhmmss + 2 spaces
  0x18  type (2 = code, 0 = web pages)
  0x2C  CRC-32 of header bytes 0x00-0x6F with this field zeroed
  0x30  header length (0x8C code, 0x88 web)    0x34  load address (0x400E0080 code)
  0x38  body length                            0x3C  CRC-32 of the body
  0x50  attribute-segment offset (= header length + body length)
  0x58  attribute-segment length               0x5C  CRC-32 of the attribute segment
  0x70  image name, NUL-terminated
The attribute segment is the text '[START_OF_ATTR_NAME_SPACE] ... [END_OF_ATTR_NAME_SPACE]'
(default settings database). The file is padded with 0xFF to a 1 KB multiple.
CRC-32 = zlib.crc32 (IEEE 802.3, reflected, init/xorout 0xFFFFFFFF).

Usage (python3 -I):
  bcod_sum.py check <image.bin> ...
  bcod_sum.py fix <in.bin> <out.bin>      recompute the three CRCs after a patch
"""
import struct, sys, zlib

M = 0xFFFFFFFF


def u32(d, o):
    return struct.unpack_from('<I', d, o)[0]


def fields(d):
    hl, blen, aoff, alen = u32(d, 0x30), u32(d, 0x38), u32(d, 0x50), u32(d, 0x58)
    return hl, blen, aoff, alen


def expected(d):
    """Return (hdr_crc, body_crc, attr_crc) computed from the image, or raise."""
    if d[:4] != b'bCoD':
        raise ValueError('no bCoD magic')
    hl, blen, aoff, alen = fields(d)
    if aoff != hl + blen:
        raise ValueError(f'attribute offset {aoff:#x} != header+body {hl + blen:#x}')
    if aoff + alen > len(d):
        raise ValueError(f'attribute segment ends at {aoff + alen:#x}, file is {len(d):#x}')
    h = bytearray(d[:0x70])
    h[0x2C:0x30] = bytes(4)
    return (zlib.crc32(bytes(h)) & M, zlib.crc32(d[hl:hl + blen]) & M,
            zlib.crc32(d[aoff:aoff + alen]) & M)


def check(d):
    """Return a list of problems; empty means the header is consistent."""
    try:
        want = expected(d)
    except ValueError as e:
        return [str(e)]
    have = (u32(d, 0x2C), u32(d, 0x3C), u32(d, 0x5C))
    return [f'{nm} CRC {h:08x}, computed {w:08x}'
            for nm, h, w in zip(('header', 'body', 'attribute'), have, want) if h != w]


def fix(d):
    d = bytearray(d)
    hc, bc, ac = expected(d)          # body/attr first: they do not depend on 0x2C
    struct.pack_into('<I', d, 0x3C, bc)
    struct.pack_into('<I', d, 0x5C, ac)
    struct.pack_into('<I', d, 0x2C, expected(d)[0])
    return bytes(d)


def main(argv):
    if len(argv) >= 2 and argv[0] == 'check':
        bad = 0
        for p in argv[1:]:
            d = open(p, 'rb').read()
            probs = check(d)
            bad += bool(probs)
            name = d[0x70:0x88].split(b'\0')[0].decode('ascii', 'replace')
            print(f"{'OK  ' if not probs else 'FAIL'} {p}  {d[8:22].decode('ascii', 'replace')} "
                  f"{name}  {'; '.join(probs)}")
        return 1 if bad else 0
    if len(argv) == 3 and argv[0] == 'fix':
        out = fix(open(argv[1], 'rb').read())
        open(argv[2], 'wb').write(out)
        print(f'{argv[2]}: CRCs recomputed; check: {check(out) or "OK"}')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
