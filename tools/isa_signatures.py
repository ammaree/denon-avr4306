"""Count M16C vs M32C function prologue/epilogue byte signatures in a de-inverted image.

Usage: isa_signatures.py image.bin [code_len_hex]
M16C: ENTER = 7C F2 imm8, EXITD = 7D F2, RTS = F3.
M32C: ENTER = EC imm8,   EXITD = FC,    RTS = DF, NOP = DE.
"""
import sys

PATS = {
    'M16C enter 7C F2': b'\x7c\xf2',
    'M16C exitd 7D F2': b'\x7d\xf2',
    'M16C exitd;enter 7D F2 7C F2': b'\x7d\xf2\x7c\xf2',
    'M16C rts;enter F3 7C F2': b'\xf3\x7c\xf2',
    'M32C exitd;nop;enter FC DE EC': b'\xfc\xde\xec',
    'M32C rts;nop;enter DF DE EC': b'\xdf\xde\xec',
    'M32C exitd;enter FC EC': b'\xfc\xec',
}

def main(path, length=None):
    d = open(path, 'rb').read()
    if length: d = d[:int(length, 16)]
    print(f'{path.split("/")[-1]}: {len(d)} bytes')
    for k, p in PATS.items():
        n = d.count(p)
        print(f'  {k:34} {n:6d}  per 10 KB {n * 10240 / len(d):6.1f}')

if __name__ == '__main__':
    main(*sys.argv[1:])
