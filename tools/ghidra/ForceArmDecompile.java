// Force ARM (TMode=0) decoding at each given address, (re)create the function, and
// decompile it to a file. For the DM850I image, whose BridgeCo C++ library is ARM
// while the Denon app layer is Thumb, so auto-analysis guesses the mode wrong.
//   analyzeHeadless build/ghidra denon -process DM850I_x.flash.bin -noanalysis \
//     -scriptPath tools/ghidra -postScript ForceArmDecompile.java <out.c> <hexaddr>...
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;
import java.math.BigInteger;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;

public class ForceArmDecompile extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		DecompInterface di = new DecompInterface();
		di.openProgram(currentProgram);
		Register tmode = currentProgram.getLanguage().getRegister("TMode");
		try (PrintWriter out = new PrintWriter(new FileWriter(args[0]))) {
			for (int i = 1; i < args.length; i++) {
				Address a = toAddr(Long.parseUnsignedLong(args[i].replaceFirst("^0x", ""), 16));
				Address end = a.add(0x400);
				clearListing(a, end);
				if (tmode != null) {
					currentProgram.getProgramContext().setValue(tmode, a, end, BigInteger.ZERO);
				}
				disassemble(a);
				Function f = getFunctionContaining(a);
				if (f == null) {
					f = createFunction(a, null);
				}
				if (f == null) {
					out.println("// no function at " + args[i]);
					continue;
				}
				DecompileResults r = di.decompileFunction(f, 200, monitor);
				out.println("// ===== " + args[i] + " in " + f.getName() + " @ " + f.getEntryPoint());
				out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC()
						: "// decompile failed: " + r.getErrorMessage());
			}
		}
		di.dispose();
	}
}
