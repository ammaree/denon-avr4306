// List references to each given address, with the function containing each reference.
// Headless use (see tools/ghidra/decompile.sh):
//   analyzeHeadless <proj_dir> <proj> -process <program> -noanalysis -readOnly \
//     -scriptPath tools/ghidra -postScript XrefsTo.java <out.txt> <hexaddr> [...]
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class XrefsTo extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 2) {
			printerr("usage: XrefsTo.java <out.txt> <hexaddr> [...]");
			return;
		}
		try (PrintWriter out = new PrintWriter(new FileWriter(args[0]))) {
			for (int i = 1; i < args.length; i++) {
				Address a = toAddr(Long.parseUnsignedLong(args[i].replaceFirst("^0x", ""), 16));
				out.println("== " + args[i]);
				for (Reference r : getReferencesTo(a)) {
					Address from = r.getFromAddress();
					Function f = getFunctionContaining(from);
					out.println("  " + from + " " + r.getReferenceType()
							+ (f == null ? "" : " in " + f.getName() + " @ " + f.getEntryPoint()));
				}
			}
		}
	}
}
