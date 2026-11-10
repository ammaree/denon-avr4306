// Seed the DM850I ARM image for whole-program analysis: the bCoD entry, the known SSDP/UPnP
// roots, and every ARM function prologue (STMFD sp!,{...,lr}) in the SDRAM code region, so
// analysis discovers the functions (Cursor's import only named the SSDP handful). Thumb
// functions are reached via BLX from the ARM code during analysis.
//   analyzeHeadless build/ghidra denon -process DM850I_x.flash.bin \
//     -scriptPath tools/ghidra -preScript SeedDm850.java
//@category Denon
import java.math.BigInteger;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;

public class SeedDm850 extends GhidraScript {
	private Register tmode;

	private void seed(long va, boolean thumb, String why) {
		try {
		Address a = toAddr(va);
		if (!currentProgram.getMemory().contains(a)) {
			return;
		}
		if (tmode != null) {
			currentProgram.getProgramContext().setValue(tmode, a, a,
					thumb ? BigInteger.ONE : BigInteger.ZERO);
		}
		addEntryPoint(a);
		if (getInstructionAt(a) == null) {
			disassemble(a);
		}
		if (getFunctionAt(a) == null) {
			createFunction(a, null);
		}
		if (why != null) {
			println("seeddm850 " + Long.toHexString(va) + " " + why);
		}
		} catch (Exception e) {
			println("seeddm850 " + Long.toHexString(va) + " skipped: " + e.getMessage());
		}
	}

	@Override
	public void run() throws Exception {
		tmode = currentProgram.getLanguage().getRegister("TMode");
		// Known roots (dm850-map.md / dm850-audit.md).
		seed(0x400E0080L, false, "bCoD entry");
		seed(0x400E00C8L, false, "scatter loader");
		seed(0x601360E0L, true, "UPnPModuleImpl::receiveData (Thumb)");
		seed(0x6004A114L, true, "Disc_Srv_Search_Req (Thumb)");
		seed(0x600A1168L, false, "acceptSocket (ARM)");

		// Scan the big SDRAM code copy for ARM prologues: STMFD sp!,{...,lr}
		// word (4-aligned) with top halfword 0xE92D and the LR bit (0x4000) set.
		long lo = 0x60008000L, hi = 0x601E79D0L;
		int made = 0;
		for (long p = lo; p + 4 <= hi; p += 4) {
			Address a = toAddr(p);
			if (!currentProgram.getMemory().contains(a)) {
				continue;
			}
			long w;
			try {
				w = getInt(a) & 0xFFFFFFFFL;
			} catch (Exception e) {
				continue;
			}
			if ((w & 0xFFFF0000L) != 0xE92D0000L || (w & 0x4000L) == 0) {
				continue;
			}
			if (getFunctionContaining(a) != null) {
				continue;
			}
			if (tmode != null) {
				currentProgram.getProgramContext().setValue(tmode, a, a, BigInteger.ZERO);
			}
			if (getInstructionAt(a) == null) {
				disassemble(a);
			}
			if (getInstructionAt(a) != null && createFunction(a, null) != null) {
				made++;
			}
		}
		println("SeedDm850: " + made + " ARM-prologue functions seeded");
	}
}
