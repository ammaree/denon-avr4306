#!/usr/bin/env python3
"""Extract all firmware images from the Denon AVR-4306 update tools.

Pipeline, for each Windows tool .exe given:
  1. walk the PE resource tree, pull every BINARY resource that begins with "AVR4306"
     (the updaters) — or read the tool's standalone .bin (FWCV recovery);
  2. parse the AVTOOL3 container header and split the component payloads;
  3. the 6.0.0.x updaters store payloads bit-inverted (XOR 0xFF), the FWCV package
     stores them plain — detect by testing the header 32-bit sum against both;
  4. write each component as <target>_<ver>.flash.bin (true flash contents, de-inverted)
     into the output dir, and append its sha256 to the manifest.

Nothing here is Denon code; it only unpacks the vendor container. Run with -I.
Images are NOT committed to the repo (see .gitignore).

Usage:
  extract.py <out_dir> <updater.exe | recovery.bin> [more ...]
"""
import os, sys, struct, hashlib


def pe_binary_resources(d):
    """Yield (name, bytes) for every RT 'BINARY' (named type) resource in a PE."""
    for name, fo, size in pe_binary_resource_spans(d):
        yield name, d[fo:fo + size]


def pe_binary_resource_spans(d):
    """Yield (name, file_offset, size) for every RT 'BINARY' (named type) resource."""
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    nsec, optsz = struct.unpack_from('<H', d, pe + 6)[0], struct.unpack_from('<H', d, pe + 20)[0]
    opt = pe + 24
    ndd = struct.unpack_from('<I', d, opt + 92)[0]
    rrva, _ = struct.unpack_from('<II', d, opt + 96 + 8 * 2)
    secs = []
    for i in range(nsec):
        nm, vsz, va, rsz, rp = struct.unpack_from('<8sIIII', d, opt + optsz + 40 * i)
        secs.append((va, vsz, rp, rsz))
    def r2o(rva):
        for va, vsz, rp, rs in secs:
            if va <= rva < va + max(vsz, rs):
                return rva - va + rp
    if not rrva:
        return
    base = r2o(rrva)
    def rsrc_name(e):
        if e & 0x80000000:
            o = base + (e & 0x7fffffff)
            n = struct.unpack_from('<H', d, o)[0]
            return d[o + 2:o + 2 + 2 * n].decode('utf-16le')
        return e
    def walk(off, path):
        _, _, _, _, nn, ni = struct.unpack_from('<IIHHHH', d, off)
        for i in range(nn + ni):
            nm, tgt = struct.unpack_from('<II', d, off + 16 + 8 * i)
            p = path + [rsrc_name(nm)]
            if tgt & 0x80000000:
                yield from walk(base + (tgt & 0x7fffffff), p)
            else:
                drva, dsz = struct.unpack_from('<II', d, base + tgt)
                yield p, r2o(drva), dsz
    for path, fo, dsz in walk(base, []):
        if path and path[0] == 'BINARY':
            yield '/'.join(str(x) for x in path), fo, dsz


def split_avtool3(blob):
    """Return list of (ident, name, ver, crc_hex, start, end, payload)."""
    hend = blob.index(b'\r\n', blob.index(b'HEADER END')) + 2
    lines = blob[:hend].decode('ascii').split('\r\n')
    recs = []
    off = hend
    for ln in lines:
        if not ln.strip() or ln.startswith(('AVR', 'AVTOOL', 'HEADER')) or ':' in ln:
            continue
        f = [ln[i:i + 8].strip() for i in range(0, len(ln), 8)]
        if f[0] in ('0001',):
            continue
        ident, name, ver, crc = f[0], f[1], f[2], f[3]
        start, end = int(f[4], 16), int(f[5], 16)
        size = end - start + 1
        recs.append((ident, name, ver, crc, start, end, blob[off:off + size]))
        off += size
    return recs


def main(out, srcs):
    os.makedirs(out, exist_ok=True)
    man = []
    for src in srcs:
        d = open(src, 'rb').read()
        base = os.path.basename(src)
        blobs = []
        if d[:2] == b'MZ':
            blobs = [b for _, b in pe_binary_resources(d) if b[:7] == b'AVR4306']
            if not blobs:
                print(f'{base}: no AVR4306 BINARY resources'); continue
        elif d[:7] == b'AVR4306':
            blobs = [d]
        else:
            print(f'{base}: not a PE or AVTOOL3 file'); continue
        for bi, blob in enumerate(blobs):
            recs = split_avtool3(blob)
            # Inversion is a property of the container generation, not the image:
            # 6.0.0.x updaters store every payload XOR 0xFF, the FWCV package stores
            # plain. Decide once from the images whose header field is a plain byte sum
            # (MAIN/SUB/DM850 use byte-sum; DSP uses a different checksum we don't model).
            inverted = None
            for ident, name, ver, crc, start, end, payload in recs:
                want = int(crc, 16)
                if (sum(payload) & 0xffffffff) == want:
                    inverted = False; break
                if (sum(b ^ 0xff for b in payload) & 0xffffffff) == want:
                    inverted = True; break
            if inverted is None:
                print(f'{base} r{bi}: cannot determine inversion; skipping'); continue
            for ident, name, ver, crc, start, end, payload in recs:
                want = int(crc, 16)
                flash = bytes(b ^ 0xff for b in payload) if inverted else payload
                bytesum = sum(flash) & 0xffffffff
                mode = ('inverted' if inverted else 'plain') + ('' if bytesum == want else ' (crc:other)')
                fn = f'{name}_{ver or "x"}.flash.bin'.replace('/', '_')
                open(os.path.join(out, fn), 'wb').write(flash)
                h = hashlib.sha256(flash).hexdigest()
                man.append((h, fn, base, ident, mode, f'0x{start:06x}-0x{end:06x}'))
                print(f'{base} r{bi}: {name:9} v{ver:6} {mode:16} load={start:#08x}-{end:#08x} -> {fn}')
    with open(os.path.join(out, 'manifest.txt'), 'w') as f:
        for row in man:
            f.write('  '.join(row) + '\n')
    print(f'\n{len(man)} images, manifest in {out}/manifest.txt')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
