#!/usr/bin/env python3
"""Simulator tests for the MAIN DM dump hook (docs/main-dump-patch.md).

Calls 0xF4B1C0 the way 0xF45EEC does (push.l line pointer; jsr; add.l #4,sp) on the
vendor and the patched image, in the GNU M32C simulator, and checks:

  1. pass-through: for every non-DM line, the patched image returns the same r0 and makes
     the same memory writes outside the stack as the vendor image;
  2. DM on UART1 (line 0x4A45): the reply on the sim's UART1 (stdout) is
     "DM" + address + 64 hex digits of the image at that address + CR; r0 = 0x113;
  3. DM on UART0 (line 0x528E): the bytes written to U0TB (0x36A) are the same reply
     (the sim does not model UART0; the stub sets U0C1.TI so the hook does not wait);
  4. malformed / out-of-range DM lines fall through like any unknown command.

  python3 -I sim/test_dm_patch.py build/images/MAIN_01.00.flash.bin build/patch/MAIN_dm.flash.bin
"""
import os, re, subprocess, sys

BIN = os.path.expanduser('~/.local/opt/binutils-m32c-2.43/bin/m32c-elf-')
RUN = os.path.expanduser('~/.local/opt/sim-m32c/bin/m32c-elf-run')
OUT = 'build/sim/dmtest'
STACK_LO, STACK_HI = 0xB000, 0xC000
LINE0, LINE1 = 0x528E, 0x4A45
ANSI = re.compile(rb'\x1b\[[0-9;]*m')
TOKENS = ['PW', 'MV', 'CV', 'MU', 'SI', 'ZM', 'SR', 'SV', 'SD', 'MS', 'PS', 'TF', 'TP',
          'TM', 'Z2', 'Z3', 'Z4', 'VI', 'RB', 'SY', 'SS', 'NS', 'IP', 'TX', 'PD', 'RR',
          'R1', 'R2', 'R3', 'R4', 'LS', 'HD', 'VS', 'XS']


def sh(*a, **k):
    return subprocess.run(a, check=True, capture_output=True, **k)


def image_obj(img, tag):
    s = f'{OUT}/img_{tag}.s'
    open(s, 'w').write(f'\t.section .image,"a",@progbits\n\t.incbin "{os.path.abspath(img)}"\n')
    sh(BIN + 'as', '-m32c', '-o', f'{OUT}/img_{tag}.o', s)
    return f'{OUT}/img_{tag}.o'


def run(imgo, line_addr, text, n):
    body = ''.join(f'\tmov.b #{b}, {line_addr + i:#x}\n' for i, b in enumerate(text))
    asm = f"""	.section .stub,"ax",@progbits
	.global _stub
_stub:
	ldc #0x00C000, sp
	ldc #0x000400, sb
	ldc #0x00C000, fb
	mov.b #0x02, 0x36d
{body}	push.l #{line_addr:#x}
	jsr.a 0xF4B1C0
	add.l #4, sp
	mov.w r0, 0x402
	mov.b #1, 0x400
1:	jmp.b 1b
"""
    open(f'{OUT}/t{n}.s', 'w').write(asm)
    sh(BIN + 'as', '-m32c', '-o', f'{OUT}/t{n}.o', f'{OUT}/t{n}.s')
    sh(BIN + 'ld', '-T', 'sim/image_boot.ld', '--defsym', 'IMAGE_VMA=0xF00000',
       '--defsym', 'START_ADDR=0xF4B1C0', '-o', f'{OUT}/t{n}.elf', imgo, f'{OUT}/t{n}.o')
    sh(BIN + 'objcopy', '-O', 'srec', f'{OUT}/t{n}.elf', f'{OUT}/t{n}.srec')
    p = subprocess.run(['perl', '-e', 'alarm 20; exec @ARGV', RUN, '-t', '-m', 'm32c',
                        f'{OUT}/t{n}.srec'], capture_output=True, stdin=subprocess.DEVNULL)
    out = ANSI.sub(b'', p.stdout + p.stderr)
    r0 = re.search(rb'SimTrace:\s+\S+\s+([0-9a-f]+)', out)
    writes, u0, u1 = [], bytearray(), bytearray()
    for m in re.finditer(rb'MEM\[([0-9a-f]{6})\] <= ([0-9a-f ]+)', out):
        a = int(m.group(1), 16)
        v = m.group(2).split()
        if STACK_LO <= a < STACK_HI or a in (0x400, 0x402) or line_addr <= a < line_addr + 16:
            continue
        if a == 0x36A:
            u0.append(int(v[0], 16))
        writes.append((a, tuple(v)))
    # the sim prints UART1 TX bytes as plain characters outside the trace lines
    for m in re.finditer(rb'MEM\[0002ea\] <= ([0-9a-f]{2})', out):
        u1.append(int(m.group(1), 16))
    return (int(r0.group(1), 16) if r0 else None), writes, bytes(u0), bytes(u1)


def expect_reply(img, addr):
    d = open(img, 'rb').read()
    data = d[addr - 0xF00000:addr - 0xF00000 + 32]
    return b'DM' + f'{addr:06X}'.encode() + data.hex().upper().encode() + b'\r'


def main():
    vend, pat = sys.argv[1:3]
    os.makedirs(OUT, exist_ok=True)
    vo, po = image_obj(vend, 'v'), image_obj(pat, 'p')
    fails, n = 0, 0
    lines = []
    for t in TOKENS:
        lines += [f'{t}?\r', f'{t}ON\r']
    lines += ['MSSTEREO\r', 'SIDVD\r', 'PSTONE CTRL ?\r', 'QQ?\r', '\r',
              'DMFFC00G?\r', 'DM000400?\r', 'DMFFFFF0?\r', 'DMFFC000\r', 'dmffc000?\r',
              'DMFFC000?X', 'XDFFC000?\r']
    for la in (LINE1, LINE0):
        for s in lines:
            n += 1
            a = run(vo, la, s.encode(), n)
            n += 1
            b = run(po, la, s.encode(), n)
            ok = a[0] == b[0] and a[1] == b[1]
            fails += not ok
            print(f'{"ok  " if ok else "FAIL"} pass-through {la:#06x} {s!r:22} r0={a[0]} / {b[0]}'
                  + ('' if ok else f'  writes differ: {len(a[1])} vs {len(b[1])}'))
    for addr in (0xFFC000, 0xF00000, 0xF4B1C0, 0xFFFFE0):
        for la in (LINE1, LINE0):
            n += 1
            r0, w, u0, u1 = run(po, la, f'DM{addr:06X}?\r'.encode(), n)
            got = u1 if la == LINE1 else u0
            exp = expect_reply(pat, addr) if addr < 0xFFC000 else None
            ok = r0 == 0x113 and len(got) == 73 and got.startswith(f'DM{addr:06X}'.encode()) \
                and got.endswith(b'\r') and (exp is None or got == exp)
            fails += not ok
            print(f'{"ok  " if ok else "FAIL"} DM {addr:06X} on {la:#06x}: r0={r0} '
                  f'reply={got[:24]!r}… ({len(got)} B)' + ('' if exp is None else
                                                          f' matches image={got == exp}'))
    print('FAILURES:', fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
