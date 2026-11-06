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
- vendor + urn:Belkin:service:basicevent      -> reply reached, copy length >> frame
- vendor + urn:...:service:dial:1              -> reply reached, length 4
- vendor + urn:...:service:ContentDirectory:1  -> length 16
- vendor + urn:...:device:MediaServer (no :N)  -> reply reached, copy length >> frame
- vendor + urn:...:device:MediaServer:1        -> length 11
- patched + Belkin / device-no-colon          -> reply NOT reached, type switch returns 0
- patched + dial / ContentDirectory / device:1 -> still answered (4 / 16 / 11)
"""
import os
import struct
import sys

try:
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UcError, UC_HOOK_CODE,
                         UC_PROT_ALL)
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_R6, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
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
# The M-SEARCH dispatch pre-check (msearch_guard.S) and its two exits in receiveData.
DISPATCH_CAVE = 0x601CE820
DISPATCH_CONT = 0x60136178  # bl Disc_Srv_Search_Req (r2 in range: dispatch)
DISPATCH_DROP = 0x6013618A  # receiveData drop/return (r2 over bound)
ST_BOUND = 0x40             # the bound msearch_guard.S enforces

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
        self._dispatch = None           # 'dispatch' or 'drop' from run_dispatch
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
        elif address == DISPATCH_CONT:
            self._dispatch = 'dispatch'
            uc.emu_stop()
        elif address == DISPATCH_DROP:
            self._dispatch = 'drop'
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

    def run_dispatch(self, st_len):
        """Execute the dispatch pre-check cave with r2 = st_len. Returns 'dispatch'
        (r2 in range -> would call Disc_Srv_Search_Req) or 'drop' (r2 over bound ->
        receiveData's return path). Only valid on the patched image."""
        uc = self.uc
        self._dispatch = None
        uc.reg_write(UC_ARM_REG_SP, SP_INIT)
        uc.mem_write(SP_INIT + 0x274, struct.pack('<I', URN_ADDR))   # ST pointer slot
        uc.reg_write(UC_ARM_REG_R6, 0xD0D0D0D0)                      # a marker arg
        uc.reg_write(UC_ARM_REG_R2, st_len)
        uc.reg_write(UC_ARM_REG_LR, DISPATCH_CONT | 1)
        cpsr = uc.reg_read(UC_ARM_REG_CPSR) | (1 << 5)
        uc.reg_write(UC_ARM_REG_CPSR, cpsr)
        try:
            uc.emu_start(DISPATCH_CAVE | 1, 0, count=1000)
        except UcError:
            pass
        return self._dispatch


STS = {
    'Belkin': 'Belkin:service:basicevent',
    'dial': 'dial-multiscreen-org:service:dial:1',
    'ContentDirectory': 'schemas-upnp-org:service:ContentDirectory:1',
}
DEV_STS = {
    'device_bad': 'schemas-upnp-org:device:MediaServer',      # no version colon
    'device_ok': 'schemas-upnp-org:device:MediaServer:1',     # valid device URN
}


def describe(r):
    if r['reply']:
        return f"reply reached, memcpy length {r['len']} (0x{r['len']:x})"
    return f"no reply; type switch returned {r['ret']} (clean={r['clean']})"


# A long but well-formed service name: the name has a version colon, so the per-arm
# guard passes it, yet its length overruns the reply frame. Only the dispatch
# pre-check stops it (its total length is over the bound).
LONG_TAIL = 'x:service:' + 'A' * 200 + ':1'


def main():
    results = {}
    reps = {}
    for tag, path in (('vendor', M.VENDOR), ('patched', M.PATCHED)):
        if not os.path.exists(path):
            raise SystemExit(f'{tag} image missing: {path}')
        print(f"== {tag} ==")
        rep = Replay(path)
        reps[tag] = rep
        results[tag] = {}
        for name, tail in STS.items():
            r = rep.run(tail, TYPE_SERVICE)
            results[tag][name] = r
            print(f"  service urn:{tail}")
            print(f"    -> {describe(r)}")
        for name, tail in DEV_STS.items():
            r = rep.run(tail, TYPE_DEVICE)
            results[tag][name] = r
            print(f"  device  urn:{tail}")
            print(f"    -> {describe(r)}")
        r = rep.run(LONG_TAIL, TYPE_SERVICE)
        results[tag]['long_name'] = r
        print(f"  service long name ({len(LONG_TAIL)} chars, well-formed)")
        print(f"    -> {describe(r)}")
        print()

    # Dispatch pre-check on the patched image: a normal-length ST dispatches; an ST
    # over the bound is dropped before Disc_Srv_Search_Req.
    d_small = reps['patched'].run_dispatch(0x30)
    d_long = reps['patched'].run_dispatch(len(LONG_TAIL))
    print(f"== dispatch pre-check (patched) ==")
    print(f"  r2=0x30 -> {d_small};  r2={len(LONG_TAIL)} (0x{len(LONG_TAIL):x}) -> {d_long}")
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
    # Device arm (docs/dm850-audit.md §2), now guarded by the same cave:
    # vendor overruns on a device URN with no version colon; patched drops it and
    # returns 0, while a valid device URN (…:1) still gets a reply on both images.
    assert v['device_bad']['reply'] and v['device_bad']['len'] > FRAME_DEV, v['device_bad']
    assert (not p['device_bad']['reply']) and p['device_bad']['ret'] == 0 and p['device_bad']['clean'], p['device_bad']
    assert v['device_ok']['reply'] and v['device_ok']['len'] == 11, v['device_ok']
    assert p['device_ok']['reply'] and p['device_ok']['len'] == 11, p['device_ok']
    # A long well-formed service name overruns on BOTH images via the arm (the name
    # has a colon, so the per-arm guard passes it). This is the residual the dispatch
    # pre-check exists for; its total length is over the bound.
    assert v['long_name']['reply'] and v['long_name']['len'] == 200, v['long_name']
    assert p['long_name']['reply'] and p['long_name']['len'] == 200, p['long_name']
    assert len(LONG_TAIL) > ST_BOUND
    # The dispatch pre-check: a normal ST dispatches; the long one is dropped.
    assert d_small == 'dispatch', d_small
    assert d_long == 'drop', d_long

    print("GATE PASS")
    print(f"  vendor  Belkin copy length {v['Belkin']['len']} > frame {FRAME_SVC}: would smash the stack")
    print(f"  patched Belkin: service URN with no version colon is ignored, type switch returns 0")
    print(f"  patched dial/ContentDirectory still answered (lengths 4 / 16)")
    print(f"  vendor  device URN with no colon overruns (length {v['device_bad']['len']} > frame {FRAME_DEV})")
    print(f"  patched device URN with no colon ignored; valid device URN still answered (length 11)")
    print(f"  long well-formed name overruns via the arm on both images (length 200 > frame {FRAME_SVC})")
    print(f"  dispatch pre-check drops an ST over 0x{ST_BOUND:x} before the search; normal ST dispatches")


if __name__ == '__main__':
    main()
