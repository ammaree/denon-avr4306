// Codebase-wide risk scan: iterate every instruction and flag the firmware bug-class
// patterns, so an audit covers all subsystems without hand-reading every function.
//   - DIV/DIVU with a register divisor  -> div-by-zero candidate (needs a zero guard)
//   - ENTER #imm with imm >= 0x40       -> large stack frame (buffer-overflow surface)
// Writes a report. Read-only.
//   analyzeHeadless build/ghidra denon -process MAIN_01.00.full.bin -noanalysis -readOnly \
//     -scriptPath tools/ghidra -postScript AuditScan.java <out.txt>
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

public class AuditScan extends GhidraScript {
	@Override
	public void run() throws Exception {
		List<String> divs = new ArrayList<>();
		List<String> frames = new ArrayList<>();
		List<String> moves = new ArrayList<>();
		long insns = 0;
		InstructionIterator it = currentProgram.getListing().getInstructions(true);
		while (it.hasNext() && !monitor.isCancelled()) {
			Instruction ins = it.next();
			insns++;
			String m = ins.getMnemonicString();
			Function f = getFunctionContaining(ins.getAddress());
			String fn = f == null ? "?" : f.getName();
			if (m.startsWith("DIV")) {
				// classify divisor: immediate operand present -> constant (safe unless 0)
				String ops = ins.toString();
				boolean imm = ops.contains("#");
				divs.add(String.format("%s  %-22s %s  [%s]", ins.getAddress(), m,
						imm ? "imm-divisor" : "REG-DIVISOR", fn));
			} else if (m.startsWith("SMOV") || m.startsWith("SSTR") || m.equals("SIN")
					|| m.startsWith("RMPA")) {
				// M32C string/block move or multiply-accumulate: R3 = count. Unbounded-copy class.
				moves.add(String.format("%s  %-10s %s  [%s]", ins.getAddress(), m, ins.toString(), fn));
			} else if (m.equals("ENTER")) {
				Object[] o = ins.getOpObjects(0);
				long imm = -1;
				if (o.length > 0 && o[0] instanceof ghidra.program.model.scalar.Scalar) {
					imm = ((ghidra.program.model.scalar.Scalar) o[0]).getUnsignedValue();
				}
				if (imm >= 0x40) {
					frames.add(String.format("%s  ENTER #%#x  [%s]", ins.getAddress(), imm, fn));
				}
			}
		}
		try (PrintWriter out = new PrintWriter(new FileWriter(getScriptArgs()[0]))) {
			out.println("instructions_scanned=" + insns);
			out.println("== DIV/DIVU sites (" + divs.size() + ") ==");
			for (String s : divs) {
				out.println("  " + s);
			}
			out.println("== large stack frames ENTER >= 0x40 (" + frames.size() + ") ==");
			for (String s : frames) {
				out.println("  " + s);
			}
			out.println("== string/block moves SMOV*/SSTR/RMPA (" + moves.size() + ") ==");
			for (String s : moves) {
				out.println("  " + s);
			}
		}
		println("AuditScan: " + insns + " insns, " + divs.size() + " DIV, "
				+ frames.size() + " large frames, " + moves.size() + " block-moves");
	}
}
