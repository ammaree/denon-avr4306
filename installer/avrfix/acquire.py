"""Obtain the owner's own original DM850I image (patch-only model).

The repo ships no Denon firmware. The owner supplies their vendor updater (the official
AVR-4306 6.0.0.4 update tool) — a Windows `.exe`, a `.zip` containing it, an already-
extracted `DM850I_x.flash.bin`, or lets the tool auto-download the official updater. We walk
the PE resources / AVTOOL3 container (logic lifted from tools/extract.py), de-invert, pull the
DM850I component, and verify it against the expected sha256. Nothing here is Denon code.
"""
import hashlib
import os
import struct
import zipfile

from . import resources
from .errors import AcquireError, ShaMismatch


# ---- PE resource + AVTOOL3 container parsing (lifted from tools/extract.py) ----------------
def _pe_binary_resources(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    rrva, _ = struct.unpack_from("<II", d, opt + 96 + 8 * 2)
    secs = []
    for i in range(nsec):
        _nm, vsz, va, rsz, rp = struct.unpack_from("<8sIIII", d, opt + optsz + 40 * i)
        secs.append((va, vsz, rp, rsz))

    def r2o(rva):
        for va, vsz, rp, rs in secs:
            if va <= rva < va + max(vsz, rs):
                return rva - va + rp
        return None

    if not rrva:
        return
    base = r2o(rrva)

    def rsrc_name(e):
        if e & 0x80000000:
            o = base + (e & 0x7FFFFFFF)
            n = struct.unpack_from("<H", d, o)[0]
            return d[o + 2:o + 2 + 2 * n].decode("utf-16le")
        return e

    def walk(off, path):
        _, _, _, _, nn, ni = struct.unpack_from("<IIHHHH", d, off)
        for i in range(nn + ni):
            nm, tgt = struct.unpack_from("<II", d, off + 16 + 8 * i)
            p = path + [rsrc_name(nm)]
            if tgt & 0x80000000:
                yield from walk(base + (tgt & 0x7FFFFFFF), p)
            else:
                drva, dsz = struct.unpack_from("<II", d, base + tgt)
                fo = r2o(drva)
                if fo is not None:
                    yield p, fo, dsz

    for path, fo, dsz in walk(base, []):
        if path and path[0] == "BINARY":
            yield d[fo:fo + dsz]


def _split_avtool3(blob):
    """Return list of (name, crc_int, payload) for each component in the container."""
    hend = blob.index(b"\r\n", blob.index(b"HEADER END")) + 2
    lines = blob[:hend].decode("ascii").split("\r\n")
    recs = []
    off = hend
    for ln in lines:
        if not ln.strip() or ln.startswith(("AVR", "AVTOOL", "HEADER")) or ":" in ln:
            continue
        f = [ln[i:i + 8].strip() for i in range(0, len(ln), 8)]
        if f[0] in ("0001",):
            continue
        name, crc = f[1], int(f[3], 16)
        start, end = int(f[4], 16), int(f[5], 16)
        size = end - start + 1
        recs.append((name, crc, blob[off:off + size]))
        off += size
    return recs


def _dm850i_from_blob(blob):
    """Extract and de-invert the DM850I component from one AVTOOL3 container blob, or None."""
    recs = _split_avtool3(blob)
    inverted = None
    for _name, crc, payload in recs:
        if (sum(payload) & 0xFFFFFFFF) == crc:
            inverted = False
            break
        if (sum(b ^ 0xFF for b in payload) & 0xFFFFFFFF) == crc:
            inverted = True
            break
    if inverted is None:
        return None
    for name, _crc, payload in recs:
        if name == "DM850I":
            return bytes(b ^ 0xFF for b in payload) if inverted else payload
    return None


def _dm850i_from_updater_bytes(d):
    if d[:4] == b"bCoD":  # already an extracted image
        return d
    blobs = []
    if d[:2] == b"MZ":
        blobs = [b for b in _pe_binary_resources(d) if b[:7] == b"AVR4306"]
    elif d[:7] == b"AVR4306":
        blobs = [d]
    for blob in blobs:
        img = _dm850i_from_blob(blob)
        if img is not None:
            return img
    return None


def extract_dm850i(source_path):
    """Extract the DM850I image from a vendor updater (.exe), a .zip of one, or an extracted
    image. Verify it against the expected original sha256. Return the image bytes, or raise."""
    if not os.path.exists(source_path):
        raise AcquireError(f"file not found: {source_path}")
    data = open(source_path, "rb").read()
    img = None
    if zipfile.is_zipfile(source_path):
        with zipfile.ZipFile(source_path) as z:
            for info in z.infolist():
                if info.filename.lower().endswith((".exe", ".bin")):
                    img = _dm850i_from_updater_bytes(z.read(info))
                    if img is not None:
                        break
    else:
        img = _dm850i_from_updater_bytes(data)
    if img is None:
        raise AcquireError(
            "could not find a DM850I image in that file. Point me at the official AVR-4306 "
            "6.0.0.4 vendor updater (.exe), a .zip containing it, or an extracted "
            "DM850I_x.flash.bin."
        )
    have = hashlib.sha256(img).hexdigest()
    if have != resources.original_sha256():
        raise ShaMismatch(
            f"the extracted DM850I does not match the expected vendor 6.0.0.4 image "
            f"(got {have[:12]}…). Make sure you used the 6.0.0.4 updater."
        )
    return img


def download(url, dest, expected_sha256=None, progress=None):
    """Download a file (the vendor updater) to dest, optional sha256 check. Returns dest."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "avrfix"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if expected_sha256:
        got = hashlib.sha256(open(dest, "rb").read()).hexdigest()
        if got != expected_sha256:
            raise ShaMismatch(f"downloaded file sha256 {got[:12]}… != expected")
    return dest
