"""Find runs of little-endian pointers that fall inside a given address range.

Usage: ptr_tables.py image.bin load_addr lo hi width(2|3|4) minrun
Reports runs of consecutive `width`-byte LE values v with lo <= v <= hi.
"""
import sys

def main(path, load, lo, hi, width, minrun):
    d = open(path, 'rb').read()
    load, lo, hi, width, minrun = int(load, 16), int(lo, 16), int(hi, 16), int(width), int(minrun)
    best = []
    for align in range(width):
        i = align; run = 0; start = None
        while i + width <= len(d):
            v = int.from_bytes(d[i:i+width], 'little')
            if lo <= v <= hi:
                if run == 0: start = i
                run += 1
            else:
                if run >= minrun: best.append((start, run))
                run = 0
            i += width
        if run >= minrun: best.append((start, run))
    best.sort()
    print(f'{path.split("/")[-1]}: {len(best)} runs of >= {minrun} {width}-byte LE ptrs in [{lo:#x},{hi:#x}]')
    for s, n in best[:25]:
        vals = [int.from_bytes(d[s+k*width:s+(k+1)*width], 'little') for k in range(min(n, 6))]
        print(f'  file 0x{s:06x} (addr 0x{load+s:06x}) x{n:4d}: ' + ' '.join(f'{v:06x}' for v in vals))

if __name__ == '__main__':
    main(*sys.argv[1:])
