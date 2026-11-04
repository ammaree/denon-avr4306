"""Parse a Denon AVTOOL3 package: print the header records and split payloads.

Header: CRLF-terminated text lines until 'HEADER END'. Lines 3.. are 8-char fixed
width fields. Payloads follow the header back to back in record order; each record's
size is (end - start + 1).
"""
import sys, os, hashlib

def fields(line, w=8):
    return [line[i:i+w].strip() for i in range(0, len(line), w)]

def main(path, outdir=None):
    d = open(path, 'rb').read()
    hend = d.index(b'\r\n', d.index(b'HEADER END')) + 2
    lines = d[:hend].decode('ascii').split('\r\n')
    print(f'{path}: header {hend} bytes, payload {len(d)-hend} bytes')
    recs = []
    for ln in lines:
        if not ln.strip() or ln.startswith('HEADER END'): continue
        if ln.startswith('AVR') or ln.startswith('AVTOOL') or ':' in ln:
            print('  |', ln.rstrip()); continue
        f = fields(ln)
        print('  |', ' '.join(f))
        if f[0] == '0001': continue          # package record
        ident, name, ver, crc, start, end = f[0], f[1], f[2], f[3], int(f[4],16), int(f[5],16)
        recs.append((ident, name, ver, crc, start, end, f[6:]))
    off = hend
    for ident, name, ver, crc, start, end, rest in recs:
        size = end - start + 1
        blob = d[off:off+size]
        h = hashlib.sha256(blob).hexdigest()[:16]
        s32 = sum(blob) & 0xffffffff
        print(f'  {ident} {name:8} v{ver:6} crc={crc} load=0x{start:06x}-0x{end:06x} size=0x{size:x} ({size}) off=0x{off:x} sum32={s32:08x} sha256={h}')
        if outdir:
            os.makedirs(outdir, exist_ok=True)
            open(os.path.join(outdir, f'{name}_{ver}.bin'), 'wb').write(blob)
        off += size
    print(f'  consumed 0x{off:x} of 0x{len(d):x}  remainder={len(d)-off}')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
