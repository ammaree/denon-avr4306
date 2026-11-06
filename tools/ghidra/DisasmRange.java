// Clear a range, disassemble from start, and print the instruction listing. For M32C
// menu/table code that auto-analysis fragments.
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.flash.bin -noanalysis \
//     -scriptPath tools/ghidra -postScript DisasmRange.java <out.txt> <startHex> <endHex>
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class DisasmRange extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] a = getScriptArgs();
		Address start = toAddr(Long.parseUnsignedLong(a[1].replaceFirst("^0x", ""), 16));
		Address end = toAddr(Long.parseUnsignedLong(a[2].replaceFirst("^0x", ""), 16));
		clearListing(start, end);
		Address p = start;
		try (PrintWriter out = new PrintWriter(new FileWriter(a[0]))) {
			while (p.compareTo(end) < 0) {
				disassemble(p);
				Instruction ins = getInstructionAt(p);
				if (ins == null) {
					out.printf("%s: db %02x%n", p, getByte(p) & 0xff);
					p = p.add(1);
					continue;
				}
				StringBuilder bytes = new StringBuilder();
				for (byte b : ins.getBytes()) {
					bytes.append(String.format("%02x", b & 0xff));
				}
				out.printf("%s: %-16s %s%n", p, bytes, ins.toString());
				p = p.add(ins.getLength());
			}
		}
	}
}
