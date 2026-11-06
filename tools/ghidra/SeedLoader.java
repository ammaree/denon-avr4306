// Seed the full MAIN image (application + resident blocks 0-2, loaded at 0xF00000) with
// the resident loader's entry points before auto-analysis: the fixed vectors at
// 0xFFFFDC-0xFFFFFF (reset at 0xFFFFFC) and the loader services the application calls
// (loader-interface.md §1.4): 0xFFC09F, 0xFFC0BC, 0xFFC0BE, 0xFFC742, 0xFFD544.
// Headless use (pre-script, analysis on):
//   analyzeHeadless <proj_dir> <proj> -import build/loader/MAIN_full.bin \
//     -loader BinaryLoader -loader-baseAddr 0xF00000 -processor M16C/80:LE:16:default \
//     -scriptPath tools/ghidra -preScript SeedLoader.java
//@category Denon
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class SeedLoader extends GhidraScript {
	private void seed(long target, String why) throws Exception {
		if (target < 0xFFC000L || target > 0xFFFFFFL) {
			return;
		}
		Address a = toAddr(target);
		addEntryPoint(a);
		disassemble(a);
		if (getFunctionAt(a) == null) {
			createFunction(a, null);
		}
		println(String.format("seed %06X %s", target, why));
	}

	@Override
	public void run() throws Exception {
		for (long v = 0xFFFFDCL; v <= 0xFFFFFCL; v += 4) {
			long t = getInt(toAddr(v)) & 0xFFFFFFL;
			seed(t, String.format("fixed vector at %06X", v));
		}
		long[] services = {0xFFC09FL, 0xFFC0BCL, 0xFFC0BEL, 0xFFC742L, 0xFFD544L};
		for (long s : services) {
			seed(s, "loader service called by the application");
		}
	}
}
