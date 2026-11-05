// Seed a raw MAIN image (loaded at 0xF00000) with entry points before auto-analysis:
// the agent entry pointer at 0xFFBE7C, the application vector table at 0xFFBF00 and the
// agent INTB table at 0xFFBD7C (64 x 4-byte LE pointers each; unused = 0xFFC0BC / -1).
// Headless use (pre-script, analysis on):
//   analyzeHeadless <proj_dir> <proj> -process MAIN_01.00.bin \
//     -scriptPath tools/ghidra -preScript SeedMain.java
//@category Denon
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class SeedMain extends GhidraScript {
	private int seeded = 0;

	private void seed(long target, String why) throws Exception {
		if (target < 0xF00000L || target >= 0xFFBD7CL) {
			return;
		}
		Address a = toAddr(target);
		addEntryPoint(a);
		disassemble(a);
		if (getFunctionAt(a) == null) {
			createFunction(a, null);
		}
		seeded++;
		println(String.format("seed %06X %s", target, why));
	}

	private long u32(long addr) throws Exception {
		return getInt(toAddr(addr)) & 0xFFFFFFFFL;
	}

	@Override
	public void run() throws Exception {
		seed(u32(0xFFBE7CL), "entry pointer 0xFFBE7C");
		for (int i = 0; i < 64; i++) {
			seed(u32(0xFFBF00L + 4 * i), "app vector " + i);
			seed(u32(0xFFBD7CL + 4 * i), "agent vector " + i);
		}
		println("seeded " + seeded);
	}
}
