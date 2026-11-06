// Apply the annotation map docs/main-names.tsv to the analyzed MAIN program: for each row
// `hexaddr <tab> name <tab> purpose`, rename the function at (or containing) the address and
// set a plate comment with the purpose. Makes the reverse-engineered names reproducible and
// keeps the Ghidra project in sync with the repo docs. Rows beginning with # are comments.
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin \
//     -scriptPath tools/ghidra -postScript ApplyNames.java docs/main-names.tsv
//@category Denon
import java.io.BufferedReader;
import java.io.FileReader;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class ApplyNames extends GhidraScript {
	@Override
	public void run() throws Exception {
		String path = getScriptArgs().length > 0 ? getScriptArgs()[0] : "docs/main-names.tsv";
		int named = 0, commented = 0, made = 0, miss = 0;
		try (BufferedReader br = new BufferedReader(new FileReader(path))) {
			String line;
			while ((line = br.readLine()) != null) {
				line = line.strip();
				if (line.isEmpty() || line.startsWith("#")) {
					continue;
				}
				String[] c = line.split("\t", 3);
				if (c.length < 2) {
					continue;
				}
				long va = Long.parseUnsignedLong(c[0].strip().replaceFirst("^0x", ""), 16);
				String name = c[1].strip();
				String purpose = c.length > 2 ? c[2].strip() : null;
				Address a = toAddr(va);
				if (!currentProgram.getMemory().contains(a)) {
					continue;   // RAM variable (not in the flash image); documented in the code-flow doc
				}
				Function f = getFunctionAt(a);
				if (f == null) {
					f = getFunctionContaining(a);
				}
				if (f == null) {
					if (getInstructionAt(a) == null) {
						disassemble(a);
					}
					f = createFunction(a, name);
					if (f != null) {
						made++;
					}
				}
				if (f == null) {
					// data label (tables, buffers, strings)
					createLabel(a, name, true, SourceType.USER_DEFINED);
					if (purpose != null) {
						setPlateComment(a, purpose);
					}
					miss++;
					continue;
				}
				f.setName(name, SourceType.USER_DEFINED);
				named++;
				if (purpose != null) {
					f.setComment(purpose);
					setPlateComment(f.getEntryPoint(), purpose);
					commented++;
				}
			}
		}
		println(String.format("ApplyNames: %d named, %d commented, %d created, %d data-labels",
				named, commented, made, miss));
	}
}
