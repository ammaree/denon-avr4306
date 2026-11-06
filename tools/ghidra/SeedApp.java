// Seed the application's own entry (0xF00000, where the boot-block startup jumps on a cold
// boot) plus known application code anchors, so re-analysis follows control flow into the
// app body. Run with analysis ON, after the initial import/analysis:
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin \
//     -scriptPath tools/ghidra -preScript SeedApp.java
//@category Denon
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class SeedApp extends GhidraScript {
	private void seed(long t, String why) throws Exception {
		Address a = toAddr(t);
		addEntryPoint(a);
		disassemble(a);
		if (getFunctionAt(a) == null) {
			createFunction(a, null);
		}
		println(String.format("seedapp %06X %s", t, why));
	}

	@Override
	public void run() throws Exception {
		seed(0xF00000L, "application cold-boot entry");
		// Known application code anchors (docs/control-protocol.md, docs/main-audit.md).
		long[] anchors = {
			0xF45EECL,  // per-line command step
			0xF4B1C0L,  // command processor (DM-dump hook site)
			0xF4B42EL,  // token dispatcher
			0xF46172L,  // command path
			0xF45F48L, 0xF461A2L,  // group sub-processors
			0xF02332L,  // PW handler
			0xF4BA26L, 0xF4BBF2L,  // UART1/UART0 RX assemblers
			0xF17F30L, 0xF17F4EL,  // setup-menu display builders (dimmer at 0xF17F4E)
		};
		for (long t : anchors) {
			seed(t, "known app anchor");
		}
	}
}
