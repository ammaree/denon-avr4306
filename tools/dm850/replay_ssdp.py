#!/usr/bin/env python3
"""Replay an SSDP service/device search through the real DM850I responder under
Unicorn, on the vendor image and on the patched image. Offline; no unit contact.

This is the gate docs/dm850-audit.md §4 asks for. It enters the reconstructed
type-switch function (0x60049A80, see docs/dm850-map.md) with r0 = URN type and
r1 = the URN text after "urn:", exactly as Disc_Srv_Search_Req calls it, and runs
the real service arm and urn_service_reply up to the copy. strstr and memcpy are
stubbed in Python so no subtree outside the arm is executed and no oversized write
actually runs; the length the responder would pass to memcpy is what is measured.

  build/venv/bin/python tools/dm850/replay_ssdp.py

Conclusions, printed and asserted:
- vendor + urn:Belkin:service:basicevent  -> reply reached, copy length >> frame
- vendor + urn:...:service:dial:1          -> reply reached, length 4
- vendor + urn:...:service:ContentDirectory:1 -> length 16
- patched + Belkin                         -> reply NOT reached, type switch returns 0
- patched + dial / ContentDirectory        -> length 4 / 16 (still answered)
"""
import os
import sys

try:
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UcError, UC_HOOK_CODE,
                         UC_PROT_ALL)
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC, UC_ARM_REG_CPSR)
except ImportError:
    sys.exit("unicorn not found. Run from the project venv:\n"
             "  python3 -m venv build/venv && build/venv/bin/pip install unicorn==2.1.4 capstone==5.0.7\n"
             "  build/venv/bin/python tools/dm850/replay_ssdp.py")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dm850_mem as M

# Addresses from the disassembly (docs/dm850-map.md, docs/dm850-audit.md).
TYPE_SWITCH = 0x60049A80
STRSTR = 0x600123A4
MEMCPY = 0x60011C90
SVC_REPLY = 0x60070A5C
DEV_REPLY = 0x60070974
TYPE_SERVICE = 7
TYPE_DEVICE = 5
FRAME_SVC = 0x64            # sub sp,#0x64 in urn_service_reply
FRAME_DEV = 0x5C            # sub sp,#0x5C in urn_device_reply

STACK_BASE = 0x6F000000
STACK_SIZE = 0x00100000
SP_INIT = STACK_BASE + 0x80000
URN_ADDR = STACK_BASE + 0x90000     # where the URN text is placed
SENTINEL = 0x2000                   # return lands here (unmapped) -> clean exit
PAGE = 0x1000


def _align_down(x):
    return x & ~(PAGE - 1)


def _cstr(uc, addr, limit=256):
    out = bytearray()
    while len(out) < limit:
        c = uc.mem_read(addr + len(out), 1)[0]
        if c == 0:
            break
        out.append(c)
    return bytes(out)


class Replay:
    def __init__(self, image_path):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self._map_image(image_path)
        self.uc.mem_map(STACK_BASE, STACK_SIZE, UC_PROT_ALL)
        self.memcpy_calls = []
        self._stopped = None            # 'strstr' or 'memcpy' when a stub halts the run
        uc = self.uc
        uc.hook_add(UC_HOOK_CODE, self._on_code)

    def _map_image(self, image_path):
        copies, zi = M.build(image_path)
        spans = [(dst, len(b)) for dst, b in copies] + list(zi)
        # Map page-aligned, merging nothing fancy; each span gets its own pages.
        for addr, length in spans:
            lo = _align_down(addr)
            hi = ((addr + length + PAGE - 1) // PAGE) * PAGE
            # map only pages not already mapped
            p = lo
            while p < hi:
                try:
                    self.uc.mem_map(p, PAGE, UC_PROT_ALL)
                except UcError:
                    pass
                p += PAGE
        for dst, blob in copies:
            self.uc.mem_write(dst, blob)

    def _on_code(self, uc, address, size, user):
        # Stub strstr and memcpy: set the return value, then stop so run() can
        # restart from LR. Restarting (not rewriting PC in-hook) is the only way
        # Unicorn re-reads the Thumb state for the continuation.
        if address == STRSTR:
            hay = uc.reg_read(UC_ARM_REG_R0)
            ndl = uc.reg_read(UC_ARM_REG_R1)
            idx = _cstr(uc, hay).find(_cstr(uc, ndl))
            uc.reg_write(UC_ARM_REG_R0, (hay + idx) if idx >= 0 else 0)
            self._stopped = 'strstr'
            uc.emu_stop()
        elif address == MEMCPY:
            dst = uc.reg_read(UC_ARM_REG_R0)
            src = uc.reg_read(UC_ARM_REG_R1)
            ln = uc.reg_read(UC_ARM_REG_R2)
            self.memcpy_calls.append((dst, src, ln))
            uc.reg_write(UC_ARM_REG_R0, dst)
            self._stopped = 'memcpy'
            uc.emu_stop()

    def run(self, urn_text, urn_type):
        uc = self.uc
        self.memcpy_calls = []
        blob = urn_text.encode() + b'\x00'
        uc.mem_write(URN_ADDR, blob)
        uc.reg_write(UC_ARM_REG_SP, SP_INIT)
        uc.reg_write(UC_ARM_REG_R0, urn_type)
        uc.reg_write(UC_ARM_REG_R1, URN_ADDR)
        uc.reg_write(UC_ARM_REG_R2, len(urn_text))   # incoming r2 = URN text length
        uc.reg_write(UC_ARM_REG_R3, 0)
        uc.reg_write(UC_ARM_REG_LR, SENTINEL | 1)
        pc = TYPE_SWITCH
        for _ in range(64):             # at most a few stub hops on this path
            self._stopped = None
            cpsr = uc.reg_read(UC_ARM_REG_CPSR) | (1 << 5)   # Thumb state
            uc.reg_write(UC_ARM_REG_CPSR, cpsr)
            try:
                uc.emu_start(pc | 1, SENTINEL, count=200000)
            except UcError:
                p = uc.reg_read(UC_ARM_REG_PC)
                if (p & ~1) == SENTINEL:
                    return {'reply': False, 'ret': uc.reg_read(UC_ARM_REG_R0),
                            'clean': True}
                raise
            if self._stopped == 'memcpy':
                dst, src, ln = self.memcpy_calls[0]
                return {'reply': True, 'len': ln, 'src': src, 'dst': dst}
            if self._stopped == 'strstr':
                pc = uc.reg_read(UC_ARM_REG_LR) & ~1
                continue
            # emu_start hit the SENTINEL 'until' exactly (even landing)
            return {'reply': False, 'ret': uc.reg_read(UC_ARM_REG_R0), 'clean': True}
        raise SystemExit('replay did not converge (too many stub hops)')


STS = {
    'Belkin': 'Belkin:service:basicevent',
    'dial': 'dial-multiscreen-org:service:dial:1',
    'ContentDirectory': 'schemas-upnp-org:service:ContentDirectory:1',
}
DEV_ST = 'schemas-upnp-org:device:MediaServer'   # device arm, no trailing colon


def describe(r):
    if r['reply']:
        return f"reply reached, memcpy length {r['len']} (0x{r['len']:x})"
    return f"no reply; type switch returned {r['ret']} (clean={r['clean']})"


def main():
    results = {}
    for tag, path in (('vendor', M.VENDOR), ('patched', M.PATCHED)):
        if not os.path.exists(path):
            raise SystemExit(f'{tag} image missing: {path}')
        print(f"== {tag} ==")
        rep = Replay(path)
        results[tag] = {}
        for name, tail in STS.items():
            r = rep.run(tail, TYPE_SERVICE)
            results[tag][name] = r
            print(f"  service urn:{tail}")
            print(f"    -> {describe(r)}")
        rd = rep.run(DEV_ST, TYPE_DEVICE)
        results[tag]['device'] = rd
        print(f"  device  urn:{DEV_ST}")
        print(f"    -> {describe(rd)}")
        print()

    v, p = results['vendor'], results['patched']
    # Vendor: Belkin overruns the 0x64 frame; dial and CD are bounded.
    assert v['Belkin']['reply'] and v['Belkin']['len'] > FRAME_SVC, v['Belkin']
    assert v['dial']['reply'] and v['dial']['len'] == 4, v['dial']
    assert v['ContentDirectory']['reply'] and v['ContentDirectory']['len'] == 16, v['ContentDirectory']
    # Patched: Belkin never reaches the reply builder; the type switch returns 0.
    assert (not p['Belkin']['reply']) and p['Belkin']['ret'] == 0 and p['Belkin']['clean'], p['Belkin']
    # Patched: the two real searches still get a reply, same lengths as vendor.
    assert p['dial']['reply'] and p['dial']['len'] == 4, p['dial']
    assert p['ContentDirectory']['reply'] and p['ContentDirectory']['len'] == 16, p['ContentDirectory']
    # Device arm (docs/dm850-audit.md §2) is NOT patched here: it still overruns
    # on both images. Recorded so the gate states what the service patch leaves.
    assert v['device']['reply'] and v['device']['len'] > FRAME_DEV, v['device']
    assert p['device']['reply'] and p['device']['len'] > FRAME_DEV, p['device']

    print("GATE PASS")
    print(f"  vendor  Belkin copy length {v['Belkin']['len']} > frame {FRAME_SVC}: would smash the stack")
    print(f"  patched Belkin: service URN with no version colon is ignored, type switch returns 0")
    print(f"  patched dial/ContentDirectory still answered (lengths 4 / 16)")
    print(f"  device arm still overruns on both images (length {p['device']['len']}): §2 patch not applied")


if __name__ == '__main__':
    main()
