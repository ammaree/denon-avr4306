"""Map a PE file: headers, sections, resource tree, overlay. No external deps."""
import struct, sys, math, collections

def entropy(b):
    if not b: return 0.0
    c = collections.Counter(b); n = len(b)
    return -sum(v/n*math.log2(v/n) for v in c.values())

def main(path):
    d = open(path, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    assert d[pe:pe+4] == b'PE\0\0'
    mach, nsec, ts, _, _, optsz, ch = struct.unpack_from('<HHIIIHH', d, pe+4)
    opt = pe + 24
    magic = struct.unpack_from('<H', d, opt)[0]
    import time
    print(f'machine=0x{mach:x} sections={nsec} timestamp={time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))} magic=0x{magic:x}')
    ep = struct.unpack_from('<I', d, opt+16)[0]
    imagebase = struct.unpack_from('<I', d, opt+28)[0]
    ndd = struct.unpack_from('<I', d, opt+92)[0]
    dd = [struct.unpack_from('<II', d, opt+96+8*i) for i in range(ndd)]
    print(f'entry=0x{ep:x} imagebase=0x{imagebase:x}')
    sh = opt + optsz
    secs = []
    end = 0
    for i in range(nsec):
        name, vsz, va, rsz, rptr = struct.unpack_from('<8sIIII', d, sh+40*i)
        name = name.rstrip(b'\0').decode('latin1')
        secs.append((name, va, vsz, rptr, rsz))
        end = max(end, rptr+rsz)
        print(f'  {name:8} va=0x{va:08x} vsz=0x{vsz:08x} raw=0x{rptr:08x} rsz=0x{rsz:08x} H={entropy(d[rptr:rptr+rsz]):.2f}')
    print(f'file=0x{len(d):x} end_of_sections=0x{end:x} overlay=0x{len(d)-end:x}')
    def rva2off(rva):
        for n, va, vsz, rp, rs in secs:
            if va <= rva < va+max(vsz, rs): return rva-va+rp
    # imports
    irva = dd[1][0]
    if irva:
        o = rva2off(irva); dlls = []
        while True:
            oft, _, _, nm, ft = struct.unpack_from('<IIIII', d, o)
            if nm == 0: break
            no = rva2off(nm); dlls.append(d[no:d.index(b'\0', no)].decode())
            o += 20
        print('imports:', ', '.join(dlls))
    # resources
    rrva = dd[2][0]
    if rrva:
        base = rva2off(rrva)
        def name_of(e):
            if e & 0x80000000:
                o = base + (e & 0x7fffffff); n = struct.unpack_from('<H', d, o)[0]
                return d[o+2:o+2+2*n].decode('utf-16le')
            return e
        def walk(off, depth, path):
            _, _, _, _, nn, ni = struct.unpack_from('<IIHHHH', d, off)
            for i in range(nn+ni):
                nm, tgt = struct.unpack_from('<II', d, off+16+8*i)
                p = path + [name_of(nm)]
                if tgt & 0x80000000:
                    walk(base + (tgt & 0x7fffffff), depth+1, p)
                else:
                    drva, dsz = struct.unpack_from('<II', d, base+tgt)
                    fo = rva2off(drva)
                    blob = d[fo:fo+dsz]
                    print(f'  res {"/".join(map(str,p)):40} off=0x{fo:08x} size={dsz:9d} H={entropy(blob):.2f} head={blob[:16].hex()}')
        print('resources:')
        walk(base, 0, [])

if __name__ == '__main__':
    main(sys.argv[1])
