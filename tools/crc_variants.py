"""Try common checksum variants against the header field."""
import sys, zlib, struct

def crc_generic(data, poly, init, refin, refout, xorout, width=32):
    mask = (1 << width) - 1
    crc = init
    if refin:
        rpoly = int(f'{poly:0{width}b}'[::-1], 2)
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ (rpoly if crc & 1 else 0)
    else:
        top = 1 << (width - 1)
        for b in data:
            crc ^= b << (width - 8)
            for _ in range(8):
                crc = ((crc << 1) ^ poly) if crc & top else (crc << 1)
                crc &= mask
    return (crc ^ xorout) & mask

def main(path, field):
    d = open(path, 'rb').read()
    inv = bytes(b ^ 0xff for b in d)
    field = field.upper()
    cands = {}
    for nm, buf in (('raw', d), ('inv', inv)):
        cands[f'crc32/{nm}'] = zlib.crc32(buf) & 0xffffffff
        cands[f'adler32/{nm}'] = zlib.adler32(buf) & 0xffffffff
        cands[f'sum8/{nm}'] = sum(buf) & 0xffffffff
        cands[f'sum16le/{nm}'] = sum(struct.unpack(f'<{len(buf)//2}H', buf[:len(buf)//2*2])) & 0xffffffff
        cands[f'sum16be/{nm}'] = sum(struct.unpack(f'>{len(buf)//2}H', buf[:len(buf)//2*2])) & 0xffffffff
        cands[f'sum32le/{nm}'] = sum(struct.unpack(f'<{len(buf)//4}I', buf[:len(buf)//4*4])) & 0xffffffff
        cands[f'sum32be/{nm}'] = sum(struct.unpack(f'>{len(buf)//4}I', buf[:len(buf)//4*4])) & 0xffffffff
    # only run slow bit-wise CRCs on a sample if large; here full but only a few variants
    if len(d) <= 0x400000:
        cands['crc32-bzip2/raw'] = crc_generic(d, 0x04C11DB7, 0xffffffff, False, False, 0xffffffff)
        cands['crc32-mpeg2/raw'] = crc_generic(d, 0x04C11DB7, 0xffffffff, False, False, 0)
        cands['crc32-posix/raw'] = crc_generic(d, 0x04C11DB7, 0, False, False, 0xffffffff)
        cands['crc32-jamcrc/raw'] = zlib.crc32(d) ^ 0xffffffff
        cands['crc32-init0/raw'] = crc_generic(d, 0x04C11DB7, 0, True, True, 0)
        cands['crc32c/raw'] = crc_generic(d, 0x1EDC6F41, 0xffffffff, True, True, 0xffffffff)
    hit = [k for k, v in cands.items() if f'{v:08X}' == field]
    print(f'{path.split("/")[-1]:22} field={field} hit={hit or "none"}  ' + ' '.join(f'{k}={v:08X}' for k, v in cands.items() if k.startswith(('crc32/', 'sum8/', 'sum32le/'))))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
