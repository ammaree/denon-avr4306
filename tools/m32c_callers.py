#!/usr/bin/env python3
"""Find call/jump sites to given addresses in a raw M32C image (byte-pattern scan).

Patterns (M32C/80 encodings, confirmed against the sim/Ghidra on MAIN 01.00):
  jsr.a abs24   CD xx xx xx      target = LE24
  jmp.a abs24   CC xx xx xx      target = LE24
  jsr.w rel16   CF xx xx         target = site + 1 + s16
  jmp.w rel16   CE xx xx         target = site + 1 + s16
A byte scan cannot tell code from data, so hits inside tables are possible; check each
hit by disassembling around it.

  python3 -I tools/m32c_callers.py build/images/MAIN_01.00.flash.bin 0xF4B1C0 [...]
"""
import sys

BASE = 0xF00000
OPS = {0xCD: 'jsr.a', 0xCC: 'jmp.a', 0xCF: 'jsr.w', 0xCE: 'jmp.w'}


def sites(d, target):
    out = []
    for i in range(len(d) - 3):
        op = d[i]
        if op in (0xCD, 0xCC):
            if int.from_bytes(d[i + 1:i + 4], 'little') == target:
                out.append((BASE + i, OPS[op]))
        elif op in (0xCF, 0xCE):
            disp = int.from_bytes(d[i + 1:i + 3], 'little', signed=True)
            if BASE + i + 1 + disp == target:
                out.append((BASE + i, OPS[op]))
    return out


def main():
    d = open(sys.argv[1], 'rb').read()
    for t in sys.argv[2:]:
        t = int(t, 0)
        hits = sites(d, t)
        print(f'{t:06X}: ' + (' '.join(f'{a:06X}({k})' for a, k in hits) or '-'))


if __name__ == '__main__':
    main()
