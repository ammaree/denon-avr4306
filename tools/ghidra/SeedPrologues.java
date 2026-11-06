// Aggressive function discovery for the M32C image: Ghidra's auto-analysis under-discovers
// functions (weak flow-following across indexed/indirect calls), so scan the code range for
// the common prologue `ENTER #imm8 ; PUSHM ...` (bytes EC imm 8F) and create a function at
// each, where one does not already exist. Run with analysis ON so the decompiler expands
// from the new functions:
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin \
//     -scriptPath tools/ghidra -preScript SeedPrologues.java
//@category Denon
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class SeedPrologues extends GhidraScript {
	@Override
	public void run() throws Exception {
		long lo = 0xF00000L, hi = 0xFFBFFFL;   // application code (boot block seeded separately)
		int made = 0, scanned = 0;
		for (long p = lo; p <= hi - 2; p++) {
			if ((getByte(toAddr(p)) & 0xff) != 0xEC) {
				continue;
			}
			if ((getByte(toAddr(p + 2)) & 0xff) != 0x8F) {
				continue;   // require ENTER #imm ; PUSHM  (low false-positive prologue)
			}
			scanned++;
			Address a = toAddr(p);
			if (getFunctionContaining(a) != null) {
				continue;
			}
			if (getInstructionAt(a) == null) {
				disassemble(a);
			}
			if (getInstructionAt(a) == null) {
				continue;   // did not decode as an instruction here
			}
			if (createFunction(a, null) != null) {
				made++;
			}
		}
		println(String.format("SeedPrologues: %d EC..8F sites, %d new functions", scanned, made));
	}
}
