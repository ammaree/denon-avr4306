"""Wrap a raw code blob in a minimal ELF32 so llvm-objdump can disassemble it.

Usage: elfwrap.py in.bin out.elf machine(arm|mips|sh) endian(le|be) base_addr_hex [skip_hex] [len_hex]
"""
import sys, struct

EM = {'arm': 40, 'mips': 8, 'sh': 42, 'm32r': 88, 'arc': 93, 'xtensa': 94, 'nios2': 113, 'm32c': 120}

def main(src, dst, mach, endian, base, skip='0', length=None):
    d = open(src, 'rb').read()
    skip = int(skip, 16); d = d[skip:]
    if length: d = d[:int(length, 16)]
    base = int(base, 16) + skip
    e = '<' if endian == 'le' else '>'
    ei_data = 1 if endian == 'le' else 2
    shstr = b'\0.text\0.shstrtab\0'
    ehsize, shentsize = 52, 40
    off_text = ehsize
    off_shstr = off_text + len(d)
    off_sh = (off_shstr + len(shstr) + 3) & ~3
    eh = b'\x7fELF' + bytes([1, ei_data, 1, 0]) + b'\0' * 8
    eh += struct.pack(e + 'HHIIIIIHHHHHH', 1, EM[mach], 1, 0, 0, off_sh, 0x05000000 if mach == 'arm' else 0,
                      ehsize, 0, 0, shentsize, 3, 2)
    sh0 = b'\0' * 40
    sh_text = struct.pack(e + 'IIIIIIIIII', 1, 1, 6, base, off_text, len(d), 0, 0, 4, 0)
    sh_str = struct.pack(e + 'IIIIIIIIII', 7, 3, 0, 0, off_shstr, len(shstr), 0, 0, 1, 0)
    out = eh + d + shstr
    out += b'\0' * (off_sh - len(out))
    out += sh0 + sh_text + sh_str
    open(dst, 'wb').write(out)

if __name__ == '__main__':
    main(*sys.argv[1:])
