"""DM850I image integrity: sha256 pin + bCoD header/body/attribute CRC check.

The bCoD CRC logic is lifted from tools/bcod_sum.py so the installer is self-contained
(no dependency on the dev tools tree at runtime).
"""
import hashlib
import struct
import zlib

_M = 0xFFFFFFFF


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _expected_crcs(d):
    """(header, body, attribute) CRC-32 computed from the image, or raise ValueError."""
    if d[:4] != b"bCoD":
        raise ValueError("not a bCoD image")
    hl, blen, aoff, alen = _u32(d, 0x30), _u32(d, 0x38), _u32(d, 0x50), _u32(d, 0x58)
    if aoff != hl + blen:
        raise ValueError(f"attribute offset {aoff:#x} != header+body {hl + blen:#x}")
    if aoff + alen > len(d):
        raise ValueError(f"attribute segment ends past end of file")
    h = bytearray(d[:0x70])
    h[0x2C:0x30] = bytes(4)
    return (
        zlib.crc32(bytes(h)) & _M,
        zlib.crc32(d[hl:hl + blen]) & _M,
        zlib.crc32(d[aoff:aoff + alen]) & _M,
    )


def bcod_problems(d):
    """Empty list if the bCoD header/body/attribute CRCs are all consistent."""
    try:
        want = _expected_crcs(d)
    except ValueError as e:
        return [str(e)]
    have = (_u32(d, 0x2C), _u32(d, 0x3C), _u32(d, 0x5C))
    return [
        f"{nm} CRC {h:08x}, computed {w:08x}"
        for nm, h, w in zip(("header", "body", "attribute"), have, want)
        if h != w
    ]
