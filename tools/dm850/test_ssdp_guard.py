#!/usr/bin/env python3
"""Run the per-arm SSDP guard both ways, and check the patched image.

  python3 -I tools/dm850/test_ssdp_guard.py

The arm cave (ssdp_guard.S) is executed by a tiny Thumb interpreter: a zero search
result (no version colon) must branch to 0x60049B76; a non-zero result must do the
original subtract/shift and return through the link register. The patched image is
then rebuilt and checked: every guard site holds a BL to its cave, each cave's bytes
are present, the vendor image is unchanged at every site, and the bCoD CRCs match.
The M-SEARCH dispatch cave (msearch_guard.S) uses an sp-relative load; its two-way
behaviour is exercised in tools/dm850/replay_ssdp.py under Unicorn, not here.
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import apply_ssdp_guard as ap

ARM_GUARD = next(g for g in ap.GUARDS if g['name'] == 'urn')


def load_cave(guard):
    base = os.path.join(ROOT, 'build', 'patch', guard['name'] + '_guard')
    ap.assemble(os.path.join(HERE, guard['src']), base + '.o')
    return ap.text_bytes_file(base + '.o', base + '.bin')


def u16(code, pc):
    return struct.unpack_from('<H', code, pc)[0]


def run(code, r0, r6):
    """Interpret the arm cave. Returns (r0, r7, where); where is the bx target."""
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
    code = load_cave(ARM_GUARD)
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
    vendor = open(ap.IMAGE, 'rb').read()
    sites = 0
    for guard in ap.GUARDS:
        cave = load_cave(guard)
        co = ap.file_off(guard['cave'])
        assert data[co:co + len(cave)] == cave, guard['name']
        for site_name, site in guard['sites'].items():
            so = ap.file_off(site)
            bl = ap.enc_bl(site, guard['cave'])
            assert data[so:so + 4] == bl, f"{guard['name']}/{site_name}: {data[so:so+4].hex()}"
            # The vendor image still has the original instruction at each site.
            assert vendor[so:so + 4] == guard['site_bytes'], f"{guard['name']}/{site_name}"
            sites += 1
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import bcod_sum
    probs = bcod_sum.check(data)
    assert not probs, probs
    print(f'guard ok, {sites} sites BL to {len(ap.GUARDS)} caves, image CRCs match')


if __name__ == '__main__':
    main()
