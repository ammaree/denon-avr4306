// Report coverage of the analyzed MAIN image: function count, whether key addresses are
// functions, and callers of given addresses (to see if control flow now reaches code that
// value-scan could not). Read-only.
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin -noanalysis -readOnly \
//     -scriptPath tools/ghidra -postScript VerifyFull.java <out.txt> <hexaddr>...
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class VerifyFull extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] a = getScriptArgs();
		try (PrintWriter out = new PrintWriter(new FileWriter(a[0]))) {
			int n = currentProgram.getFunctionManager().getFunctionCount();
			out.println("function_count=" + n);
			Address min = currentProgram.getMinAddress(), max = currentProgram.getMaxAddress();
			out.println("range=" + min + ".." + max);
			for (int i = 1; i < a.length; i++) {
				Address addr = toAddr(Long.parseUnsignedLong(a[i].replaceFirst("^0x", ""), 16));
				Function f = getFunctionContaining(addr);
				StringBuilder sb = new StringBuilder();
				sb.append(a[i]).append(": ");
				if (f == null) {
					sb.append("NOT in any function");
				} else {
					sb.append("in ").append(f.getName()).append(" @ ").append(f.getEntryPoint());
				}
				// callers / references to this exact address
				int refs = 0, calls = 0;
				for (Reference r : getReferencesTo(addr)) {
					refs++;
					if (r.getReferenceType().isCall()) {
						calls++;
					}
				}
				sb.append("  refsTo=").append(refs).append(" calls=").append(calls);
				out.println(sb.toString());
			}
		}
	}
}
