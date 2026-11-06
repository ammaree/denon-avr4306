// Load DM850I_x at the addresses the image's own scatter loader uses.
//
// Import the file with BinaryLoader at base 0x400DFFF4, processor ARM:LE:32:v5t,
// and run this as a pre-script (before analysis). File offset 0x8C is then the
// ARM entry at 0x400E0080, and file offset 0x1A0 is the scatter header at
// 0x400E0194. The header is four words, each an offset from 0x400E0194:
// copy-region start, copy-region end, ZI start, ZI end. Copy records are 12
// bytes (src, dst, len); ZI records are 8 bytes (addr, len). A zero length, or
// src == dst, is an empty marker. This image's live records have the low flag
// bits clear, so the addresses are absolute; a record with a flag bit set is
// reported and skipped (the loader at 0x400E00C8 would add a base the script
// does not have).
//
//   analyzeHeadless build/ghidra denon -import build/images/DM850I_x.flash.bin \
//     -loader BinaryLoader -loader-baseAddr 0x400DFFF4 -processor ARM:LE:32:v5t \
//     -scriptPath tools/ghidra -preScript LoadDm850.java -postScript NameDm850.java
//@category Denon
import java.math.BigInteger;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.mem.MemoryBlock;

public class LoadDm850 extends GhidraScript {
	private ghidra.program.model.mem.Memory mem;
	private static final long IMAGE_BASE = 0x400DFFF4L;
	private static final long ENTRY = 0x400E0080L;
	private static final long SCATTER = 0x400E00C8L;
	private static final long REGION_TABLE = 0x400E0194L;

	private long u32(long va) throws Exception {
		return getInt(toAddr(va)) & 0xFFFFFFFFL;
	}

	private void armAt(long va, String name) throws Exception {
		Address a = toAddr(va);
		Register tmode = currentProgram.getLanguage().getRegister("TMode");
		if (tmode != null && getInstructionAt(a) == null) {
			currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.ZERO);
		}
		addEntryPoint(a);
		if (getInstructionAt(a) == null) {
			disassemble(a);
		}
		if (getFunctionAt(a) == null) {
			createFunction(a, name);
		} else {
			getFunctionAt(a).setName(name, ghidra.program.model.symbol.SourceType.USER_DEFINED);
		}
	}

	private void copyBlock(String name, long src, long dst, long len) throws Exception {
		Address start = toAddr(dst);
		MemoryBlock block = mem.createInitializedBlock(name, start, len, (byte) 0, monitor, false);
		block.setPermissions(true, true, true);
		final int CHUNK = 0x10000;
		byte[] buf = new byte[CHUNK];
		long done = 0;
		while (done < len) {
			int n = (int) Math.min(CHUNK, len - done);
			if (n != buf.length) {
				buf = new byte[n];
			}
			mem.getBytes(toAddr(src + done), buf);
			mem.setBytes(toAddr(dst + done), buf);
			done += n;
		}
		println(String.format("copy %s %08X <- %08X len %X", name, dst, src, len));
	}

	@Override
	public void run() throws Exception {
		mem = currentProgram.getMemory();
		Address base = toAddr(IMAGE_BASE);
		byte[] magic = new byte[4];
		mem.getBytes(base, magic);
		if (magic[0] != 'b' || magic[1] != 'C' || magic[2] != 'o' || magic[3] != 'D') {
			printerr("LoadDm850: file is not a bCoD image at 0x400DFFF4");
			return;
		}
		long headerLen = u32(IMAGE_BASE + 0x30);
		long load = u32(IMAGE_BASE + 0x34);
		long bodyLen = u32(IMAGE_BASE + 0x38);
		println(String.format("bCoD headerLen %X load %08X body %X", headerLen, load, bodyLen));
		if (load != ENTRY) {
			printerr(String.format("load address %08X, expected %08X", load, ENTRY));
			return;
		}

		long r8 = REGION_TABLE;
		long copyLo = (u32(r8) + r8) & 0xFFFFFFFFL;
		long copyHi = (u32(r8 + 4) + r8) & 0xFFFFFFFFL;
		long ziLo = (u32(r8 + 8) + r8) & 0xFFFFFFFFL;
		long ziHi = (u32(r8 + 12) + r8) & 0xFFFFFFFFL;
		println(String.format("scatter copy %08X-%08X zi %08X-%08X", copyLo, copyHi, ziLo, ziHi));

		int n = 0;
		for (long p = copyLo; p + 12 <= copyHi; p += 12) {
			long src = u32(p);
			long dst = u32(p + 4);
			long len = u32(p + 8);
			if (len == 0 || src == dst) {
				continue;
			}
			if ((src & 3) != 0 || (dst & 3) != 0) {
				println(String.format("skip relative record at %08X src %08X dst %08X", p, src, dst));
				continue;
			}
			copyBlock(String.format("region_%d_%08x", n, dst), src, dst, len);
			n++;
		}

		int z = 0;
		for (long p = ziLo; p + 8 <= ziHi; p += 8) {
			long addr = u32(p);
			long len = u32(p + 4);
			if (len == 0) {
				continue;
			}
			if ((addr & 3) != 0) {
				println(String.format("skip relative ZI at %08X addr %08X", p, addr));
				continue;
			}
			String name = String.format("zi_%d_%08x", z, addr);
			mem.createUninitializedBlock(name, toAddr(addr), len, false);
			println(String.format("zi   %s %08X len %X", name, addr, len));
			z++;
		}

		armAt(ENTRY, "dm850_reset");
		armAt(SCATTER, "__scatterload");
		println(String.format("LoadDm850: %d copies, %d ZI regions", n, z));
	}
}
