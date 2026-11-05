#!/usr/bin/env python3
"""Cross-reference helper for 32-bit PE tools (the Denon updaters). No external deps;
disassembly uses the system LLVM objdump (/usr/bin/objdump on macOS).

  pe_xref.py imports <exe>                 IAT address -> DLL!name (or ordinal)
  pe_xref.py strings <exe> <regex>         matching strings, their VA and code xrefs
  pe_xref.py callers <exe> <va|import>     direct 'call rel32' sites targeting <va>, or an
                                           import name (e.g. htons) via its jmp thunk
  pe_xref.py dis <exe> <va_start> <va_end> disassembly, import calls and strings annotated

Run with python3 -I. The exe is data: nothing here executes it.
"""
import re, struct, subprocess, sys

# Well-known WS2_32 / WSOCK32 export ordinals (imports by ordinal carry no name).
WS2 = {1: 'accept', 2: 'bind', 3: 'closesocket', 4: 'connect', 5: 'getpeername',
       6: 'getsockname', 7: 'getsockopt', 8: 'htonl', 9: 'htons', 10: 'ioctlsocket',
       11: 'inet_addr', 12: 'inet_ntoa', 13: 'listen', 14: 'ntohl', 15: 'ntohs', 16: 'recv',
       17: 'recvfrom', 18: 'select', 19: 'send', 20: 'sendto', 21: 'setsockopt',
       22: 'shutdown', 23: 'socket', 51: 'gethostbyaddr', 52: 'gethostbyname',
       57: 'gethostname', 111: 'WSAGetLastError', 115: 'WSAStartup', 116: 'WSACleanup'}


class PE:
    def __init__(self, path):
        self.path = path
        d = self.d = open(path, 'rb').read()
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        nsec, optsz = struct.unpack_from('<H', d, pe + 6)[0], struct.unpack_from('<H', d, pe + 20)[0]
        opt = pe + 24
        self.base = struct.unpack_from('<I', d, opt + 28)[0]
        self.dd = [struct.unpack_from('<II', d, opt + 96 + 8 * i) for i in range(16)]
        self.secs = []
        for i in range(nsec):
            nm, vsz, va, rsz, rp = struct.unpack_from('<8sIIII', d, opt + optsz + 40 * i)
            self.secs.append((nm.rstrip(b'\0').decode('latin1'), va, vsz, rp, rsz))

    def r2o(self, rva):
        for _, va, vsz, rp, rs in self.secs:
            if va <= rva < va + max(vsz, rs):
                return rva - va + rp

    def sec(self, name):
        for nm, va, vsz, rp, rs in self.secs:
            if nm == name:
                return self.base + va, self.d[rp:rp + min(vsz, rs) if vsz else rs]

    def cstr(self, o):
        return self.d[o:self.d.index(b'\0', o)].decode('latin1')

    def imports(self):
        out = {}
        o = self.r2o(self.dd[1][0])
        while True:
            oft, _, _, nm, ft = struct.unpack_from('<IIIII', self.d, o)
            if nm == 0:
                break
            dll = self.cstr(self.r2o(nm))
            t, i = self.r2o(oft or ft), 0
            while True:
                e = struct.unpack_from('<I', self.d, t + 4 * i)[0]
                if e == 0:
                    break
                if e & 0x80000000:
                    ordn = e & 0xffff
                    name = WS2.get(ordn, f'#{ordn}') if dll.upper().startswith(('WS2_32', 'WSOCK32')) else f'#{ordn}'
                else:
                    name = self.cstr(self.r2o(e) + 2)
                out[self.base + ft + 4 * i] = f'{dll}!{name}'
                i += 1
            o += 20
        return out

    def thunks(self):
        """Map 'jmp dword ptr [IAT]' thunk addresses to import names."""
        imp, (va, b) = self.imports(), self.text()
        out = {}
        for m in re.finditer(b'\xff\x25', b):
            t = struct.unpack_from('<I', b, m.start() + 2)[0] if m.start() + 6 <= len(b) else 0
            if t in imp:
                out[va + m.start()] = imp[t]
        return out

    def strings(self, minlen=4):
        out = {}
        for name in ('.rdata', '.data'):
            s = self.sec(name)
            if not s:
                continue
            va, b = s
            for m in re.finditer(rb'[\x20-\x7e\t\r\n]{%d,}' % minlen, b):
                out[va + m.start()] = m.group().decode('latin1')
        return out

    def text(self):
        return self.sec('.text')

    def xrefs(self, target):
        va, b = self.text()
        pat = struct.pack('<I', target)
        return [va + m.start() for m in re.finditer(re.escape(pat), b)]

    def callers(self, target):
        va, b = self.text()
        out = []
        for m in re.finditer(b'\xe8', b):
            o = m.start()
            if o + 5 <= len(b) and va + o + 5 + struct.unpack_from('<i', b, o + 1)[0] == target:
                out.append(va + o)
        return out


def dis(pe, a, z):
    imp, strs = {**pe.imports(), **pe.thunks()}, pe.strings()
    out = subprocess.run(['objdump', '-d', '--x86-asm-syntax=intel', f'--start-address={a:#x}',
                          f'--stop-address={z:#x}', pe.path], capture_output=True, text=True).stdout
    for ln in out.splitlines()[6:]:
        note = []
        for h in re.findall(r'0x([0-9a-f]{6,8})', ln):
            v = int(h, 16)
            if v in imp:
                note.append(imp[v])
            elif v in strs:
                note.append(repr(strs[v][:60]))
        print(ln + ('    ; ' + ' | '.join(note) if note else ''))


def main(a):
    pe = PE(a[1])
    if a[0] == 'imports':
        for k, v in sorted(pe.imports().items()):
            print(f'{k:#010x} {v}')
    elif a[0] == 'strings':
        rx = re.compile(a[2])
        for va, s in sorted(pe.strings().items()):
            if rx.search(s):
                xs = pe.xrefs(va)
                print(f'{va:#010x} {s[:70]!r}  xrefs: {" ".join(f"{x:#x}" for x in xs) or "-"}')
    elif a[0] == 'callers':
        if re.fullmatch(r'(0x)?[0-9a-fA-F]+', a[2]):
            targets = [int(a[2], 16)]
        else:
            targets = [va for va, nm in pe.thunks().items() if nm.endswith('!' + a[2])]
        print(' '.join(f'{x:#x}' for t in targets for x in pe.callers(t)))
    elif a[0] == 'dis':
        dis(pe, int(a[2], 16), int(a[3], 16))
    else:
        print(__doc__)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
