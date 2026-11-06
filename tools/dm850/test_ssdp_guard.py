#!/usr/bin/env python3
"""Run the assembled SSDP guard both ways, and check the patched image.

  python3 -I tools/dm850/test_ssdp_guard.py

A zero return from the search (no version colon) must branch to 0x60049B76.
A non-zero return must do the original `subs r0, r0, r6` / `lsls r7, r0, #16`
and return to the link register. This is the gate for the cave itself. A replay
of the whole responder still has to stub Disc_Srv_Search_Req's callees; that is
described in docs/dm850-audit.md and is not this test.
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import apply_ssdp_guard as ap


def load_cave():
    obj = os.path.join(ROOT, 'build', 'patch', 'ssdp_guard.o')
    blob = os.path.join(ROOT, 'build', 'patch', 'ssdp_guard.bin')
    ap.assemble(obj)
    return ap.text_bytes_file(obj, blob)


def u16(code, pc):
    return struct.unpack_from('<H', code, pc)[0]


def run(code, r0, r6):
    """Interpret the cave. Returns (r0, r7, where). where is 'lr' or the bx target."""
    reg = {0: r0, 3: 0, 6: r6, 7: 0}
    pc = 0
    lr = 0x60049B3A
    for _ in range(16):
        if pc == lr or pc >= len(code):
            return reg[0], reg[7], pc
        h = u16(code, pc)
        if h == 0x2800:                      # cmp r0, #0
            flags_z = reg[0] == 0
            pc += 2
        elif (h & 0xFF00) == 0xD000:         # beq
            imm = h & 0xFF
            if imm & 0x80:
                imm -= 0x100
            pc = (pc + 4 + imm * 2) if flags_z else pc + 2
        elif h == 0x1B80:                    # subs r0, r0, r6
            reg[0] = (reg[0] - reg[6]) & 0xFFFFFFFF
            pc += 2
        elif h == 0x0407:                    # lsls r7, r0, #16
            reg[7] = (reg[0] << 16) & 0xFFFFFFFF
            pc += 2
        elif h == 0x4770:                    # bx lr
            pc = lr
        elif (h & 0xF800) == 0x4800:         # ldr r3, [pc, #imm]
            lit = ((pc + 4) & ~3) + (h & 0xFF) * 4
            reg[3] = struct.unpack_from('<I', code, lit)[0]
            pc += 2
        elif h == 0x4718:                    # bx r3
            pc = reg[3]
            return reg[0], reg[7], pc
        elif h == 0x46C0:                    # nop (mov r8, r8), or alignment pad
            pc += 2
        else:
            raise SystemExit(f'unexpected halfword {h:#06x} at cave+{pc:#x}')
    raise SystemExit('cave did not finish')


def main():
    code = load_cave()
    r0, r7, where = run(code, 0, 0x60100000)
    assert where == 0x60049B77, hex(where)
    assert r0 == 0

    r0, r7, where = run(code, 0x200, 0x100)
    assert where == 0x60049B3A, hex(where)
    assert r0 == 0x100, hex(r0)
    assert r7 == 0x100 << 16, hex(r7)

    image = os.path.join(ROOT, 'build', 'patch', 'DM850I_ssdp.flash.bin')
    # Always rebuild so the test reflects the current apply script.
    subprocess.check_call([sys.executable, os.path.join(HERE, 'apply_ssdp_guard.py')])
    data = open(image, 'rb').read()
    co = ap.file_off(ap.CAVE)
    assert data[co:co + len(code)] == code
    vendor = open(ap.IMAGE, 'rb').read()
    for name, site in ap.SITES.items():
        so = ap.file_off(site)
        bl = ap.enc_bl(site, ap.CAVE)
        assert data[so:so + 4] == bl, f'{name}: {data[so:so+4].hex()}'
        # The vendor image still has the original instruction at each site.
        assert vendor[so:so + 4] == ap.SITE_BYTES, name
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import bcod_sum
    probs = bcod_sum.check(data)
    assert not probs, probs
    print(f'guard ok, cave {len(code)} bytes, both sites BL to cave, image CRCs match')


if __name__ == '__main__':
    main()
