// Decompile the function containing each given address and write C to a file.
// Headless use (see tools/ghidra/decompile.sh):
//   analyzeHeadless <proj_dir> <proj> -process <program> -noanalysis \
//     -scriptPath tools/ghidra -postScript DecompileAt.java <out.c> <hexaddr> [...]
// An address outside any known function is disassembled and a function is created there.
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompileAt extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 2) {
			printerr("usage: DecompileAt.java <out.c> <hexaddr> [...]");
			return;
		}
		DecompInterface di = new DecompInterface();
		di.openProgram(currentProgram);
		try (PrintWriter out = new PrintWriter(new FileWriter(args[0]))) {
			for (int i = 1; i < args.length; i++) {
				Address a = toAddr(Long.parseUnsignedLong(args[i].replaceFirst("^0x", ""), 16));
				Function f = getFunctionContaining(a);
				if (f == null) {
					disassemble(a);
					f = createFunction(a, null);
				}
				if (f == null) {
					out.println("// no function at " + args[i]);
					continue;
				}
				DecompileResults r = di.decompileFunction(f, 180, monitor);
				out.println("// ===== " + args[i] + " in " + f.getName() + " @ " + f.getEntryPoint());
				out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC()
						: "// decompile failed: " + r.getErrorMessage());
			}
		}
		di.dispose();
	}
}
