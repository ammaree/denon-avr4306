#!/usr/bin/env python3
"""Rebuild Denon AVTOOL3 containers — the inverse of extract.py.

Header layout (ASCII; each line space-padded to 16*k-2 bytes, then CRLF):
  'AVR4306', 'AVTOOL3 B007'
  package record, 8-char fields:
    0001 AMP 0011 <model> 00.01 <pkgsum> <count> 00000007 00000004 00000003
  image records, 8-char fields at cols 0..95:
    id name ver sum start end end flash 00000004 t m 00000000
    route at col 96, DM850 build stamp at col 112, line length always 158
  'MW:ON', 'BP:OFF', 'PV:OFF', two blank lines, 'HEADER END'
  payloads back to back in record order, size end-start+1, no trailer.

sum    = 32-bit byte sum of the true flash bytes (before inversion).
pkgsum = 32-bit sum of the image sum fields; count = number of image records.
Storage: the 6.0.0.x updaters store payloads XOR 0xFF, the FWCV .bin stores them plain.
DSP's sum field uses another, unknown checksum: it is always kept verbatim.

Safety (docs/safety-plan.md, hard rule 1): only MAIN and DM850I/W/D payloads can be
replaced, at the same size, and the address range of an image never changes — so a MAIN
image can never reach the resident blocks 0-2 (0xFFC000-0xFFFFFF). A replacement DM850
payload must pass the bCoD header check (bcod_sum.py) or it is refused.

Usage (run with python3 -I):
  avtool3_pack.py verify <updater.exe | avtool3.bin> ...
      rebuild every container and the exe from parsed fields; must be byte-identical
  avtool3_pack.py build <template> <out.bin> [--only NAME ...] [--replace NAME=flash.bin]
                        [--ver NAME=xx.xx] [--stamp NAME=X...] [--plain | --inverted]
      template = avtool3.bin or updater.exe#<resource> (320, 321, 351)
  avtool3_pack.py patch-exe <updater.exe> <out.exe> --replace NAME=flash.bin
                            [--ver NAME=xx.xx] [--stamp NAME=X...]
      replace payloads inside the updater's resources in place (sizes must not change)
"""
import argparse, hashlib, os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import pe_binary_resource_spans
import bcod_sum

M = 0xFFFFFFFF
INV = bytes(range(255, -1, -1))         # XOR 0xFF as a translate table
REPLACEABLE = {'MAIN', 'DM850I', 'DM850W', 'DM850D', 'DM850'}   # DM850 = FWCV's app image
MAIN_TOP = 0xFFBFFF                     # last byte below the resident blocks 0-2
REC_LEN = 158


def pad(s):
    return s + ' ' * (-(len(s) + 2) % 16)


def parse(blob):
    hend = blob.index(b'\r\n', blob.index(b'HEADER END')) + 2
    lines = blob[:hend].decode('ascii').split('\r\n')[:-1]
    c = dict(head=[], pkg=None, recs=[], tail=[])
    off = hend
    for ln in lines:
        if ln.startswith('0001'):
            c['pkg'] = [ln[i:i + 8].strip() for i in range(0, 80, 8)]
        elif len(ln) == REC_LEN:
            f = [ln[i:i + 8].strip() for i in range(0, 96, 8)]
            size = int(f[5], 16) - int(f[4], 16) + 1
            c['recs'].append(dict(f=f, route=ln[96:112].strip(), stamp=ln[112:].strip(),
                                  data=blob[off:off + size]))
            off += size
        else:
            (c['head'] if c['pkg'] is None else c['tail']).append(ln.rstrip())
    if off != len(blob):
        raise ValueError(f'payloads end at {off:#x}, container is {len(blob):#x}')
    # Generation: plain if a byte-summed image matches its field as stored, else inverted.
    for r in c['recs']:
        if r['f'][1] == 'DSP':
            continue
        want = int(r['f'][3], 16)
        if sum(r['data']) & M == want:
            c['inverted'] = False; break
        if sum(r['data'].translate(INV)) & M == want:
            c['inverted'] = True; break
    else:
        raise ValueError('cannot determine payload inversion')
    return c


def flash(c, r):
    return r['data'].translate(INV) if c['inverted'] else r['data']


def serialize(c):
    for r in c['recs']:
        if r['f'][1] != 'DSP':
            r['f'][3] = '%08X' % (sum(flash(c, r)) & M)
    c['pkg'][5] = '%08X' % (sum(int(r['f'][3], 16) for r in c['recs']) & M)
    c['pkg'][6] = '%08X' % len(c['recs'])
    out = [pad(s) for s in c['head']]
    out.append(pad(''.join(x.ljust(8) for x in c['pkg'])))
    for r in c['recs']:
        ln = ''.join(x.ljust(8) for x in r['f']) + r['route'].ljust(16) + r['stamp']
        out.append(ln.ljust(REC_LEN))
    out += [pad(s) for s in c['tail']]
    hdr = ''.join(s + '\r\n' for s in out).encode('ascii')
    return hdr + b''.join(r['data'] for r in c['recs'])


def set_inversion(c, inverted):
    if c['inverted'] != inverted:
        for r in c['recs']:
            r['data'] = r['data'].translate(INV)
        c['inverted'] = inverted


def apply(c, replace, ver, stamp):
    names = {r['f'][1] for r in c['recs']}
    for nm in list(replace) + list(ver) + list(stamp):
        if nm not in REPLACEABLE:
            sys.exit(f'refused: {nm} may not be modified (safety-plan.md hard rule 1)')
    for r in c['recs']:
        nm = r['f'][1]
        start, end = int(r['f'][4], 16), int(r['f'][5], 16)
        if nm == 'MAIN' and end > MAIN_TOP:
            sys.exit(f'refused: MAIN range ends at {end:#x}, above {MAIN_TOP:#x}')
        if nm in replace:
            new = open(replace[nm], 'rb').read()
            if len(new) != end - start + 1:
                sys.exit(f'refused: {nm} replacement is {len(new)} bytes, '
                         f'range {start:#x}-{end:#x} needs {end - start + 1}')
            if nm.startswith('DM850') and bcod_sum.check(new):
                sys.exit(f'refused: {nm} bCoD header: {"; ".join(bcod_sum.check(new))}')
            r['data'] = new.translate(INV) if c['inverted'] else new
            print(f'  {nm}: payload replaced, flash sha256 {hashlib.sha256(new).hexdigest()[:16]}')
        if nm in ver:
            if not re.fullmatch(r'\d\d\.\d\d', ver[nm]):
                sys.exit(f'refused: version {ver[nm]!r} is not NN.NN')
            r['f'][2] = ver[nm]
        if nm in stamp:
            if not re.fullmatch(r'[A-Z]\d{12}', stamp[nm]):
                sys.exit(f'refused: stamp {stamp[nm]!r} is not like I200805270745')
            r['stamp'] = stamp[nm]
    for nm in set(replace) | set(ver) | set(stamp):
        if nm not in names:
            sys.exit(f'refused: {nm} is not in this container')


def containers(path):
    """Yield (label, file_offset, blob) for each AVTOOL3 container in an exe or .bin."""
    d = open(path, 'rb').read()
    if d[:2] == b'MZ':
        for name, fo, size in pe_binary_resource_spans(d):
            if d[fo:fo + 7] == b'AVR4306':
                yield name.split('/')[1], fo, d[fo:fo + size]
    elif d[:7] == b'AVR4306':
        yield 'file', 0, d
    else:
        sys.exit(f'{path}: not a PE or AVTOOL3 file')


def cmd_verify(paths):
    bad = 0
    for p in paths:
        d = open(p, 'rb').read()
        rebuilt = bytearray(d)
        for label, fo, blob in containers(p):
            c = parse(blob)
            out = serialize(c)
            ok = out == blob
            bad += not ok
            rebuilt[fo:fo + len(out)] = out
            imgs = ' '.join(f"{r['f'][1]}/{r['f'][2] or '-'}" for r in c['recs'])
            print(f"{'OK  ' if ok else 'FAIL'} {os.path.basename(p)}#{label} "
                  f"{'inverted' if c['inverted'] else 'plain'} {imgs}")
        if bytes(rebuilt) != d:
            bad += 1; print(f'FAIL {os.path.basename(p)}: whole-file rebuild differs')
    print(f'verify: {bad} failure(s)')
    return bad == 0


def kv(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition('=')
        out[k] = v
    return out


def cmd_build(a):
    path, _, res = a.template.partition('#')
    sel = [b for label, _, b in containers(path) if not res or label == res]
    if len(sel) != 1:
        sys.exit('template must name exactly one container (use updater.exe#320 etc.)')
    c = parse(sel[0])
    if a.only:
        c['recs'] = [r for r in c['recs'] if r['f'][1] in a.only]
        if {r['f'][1] for r in c['recs']} != set(a.only):
            sys.exit('refused: --only names an image not in the template')
    apply(c, kv(a.replace), kv(a.ver), kv(a.stamp))
    if a.plain or a.inverted:
        set_inversion(c, bool(a.inverted))
    out = serialize(c)
    open(a.out, 'wb').write(out)
    print(f'{a.out}: {len(out)} bytes, sha256 {hashlib.sha256(out).hexdigest()}')
    for r in c['recs']:
        print(f"  {r['f'][0]} {r['f'][1]:8} v{r['f'][2] or '-':6} sum {r['f'][3]} "
              f"{r['f'][4]}-{r['f'][5]} route {r['route']} {r['stamp']}")


def cmd_patch_exe(a):
    d = bytearray(open(a.exe, 'rb').read())
    rep, ver, stamp = kv(a.replace), kv(a.ver), kv(a.stamp)
    touched = set()
    for label, fo, blob in containers(a.exe):
        c = parse(blob)
        here = {r['f'][1] for r in c['recs']}
        mine = lambda m: {k: v for k, v in m.items() if k in here}
        if not (mine(rep) or mine(ver) or mine(stamp)):
            continue
        print(f'resource {label}:')
        apply(c, mine(rep), mine(ver), mine(stamp))
        out = serialize(c)
        if len(out) != len(blob):
            sys.exit(f'refused: resource {label} would change size')
        d[fo:fo + len(out)] = out
        touched |= here
    missing = (set(rep) | set(ver) | set(stamp)) - touched
    if missing:
        sys.exit(f'refused: not found in any resource: {sorted(missing)}')
    open(a.out, 'wb').write(d)
    print(f'{a.out}: sha256 {hashlib.sha256(d).hexdigest()}')


def main():
    ap = argparse.ArgumentParser(description='rebuild Denon AVTOOL3 containers')
    sub = ap.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify'); v.add_argument('paths', nargs='+')
    b = sub.add_parser('build'); b.add_argument('template'); b.add_argument('out')
    b.add_argument('--only', nargs='+')
    g = b.add_mutually_exclusive_group()
    g.add_argument('--plain', action='store_true'); g.add_argument('--inverted', action='store_true')
    p = sub.add_parser('patch-exe'); p.add_argument('exe'); p.add_argument('out')
    for x in (b, p):
        x.add_argument('--replace', action='append', metavar='NAME=flash.bin')
        x.add_argument('--ver', action='append', metavar='NAME=NN.NN')
        x.add_argument('--stamp', action='append', metavar='NAME=I200805270745')
    a = ap.parse_args()
    if a.cmd == 'verify':
        sys.exit(0 if cmd_verify(a.paths) else 1)
    cmd_build(a) if a.cmd == 'build' else cmd_patch_exe(a)


if __name__ == '__main__':
    main()
