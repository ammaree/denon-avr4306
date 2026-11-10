// DM850 / ARM copy audit: for every call to a copy routine, classify the length (R2) as a
// constant or a variable, and the destination (R0) as stack-relative or not. The SSDP crash
// (dm850-audit.md) was a variable-length copy into a stack buffer; this flags every other
// site of that shape so the audit covers all of them, not just SSDP.
//   analyzeHeadless build/ghidra denon -process DM850I_x.flash.bin -noanalysis -readOnly \
//     -scriptPath tools/ghidra -postScript AuditCopyArm.java <out.txt> <copyFuncHex>...
//@category Denon
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

public class AuditCopyArm extends GhidraScript {
	// walk back up to N instructions to find who last wrote a register
	private Instruction lastWriter(Instruction call, Register reg, int n) {
		Instruction ins = call.getPrevious();
		for (int i = 0; i < n && ins != null; i++, ins = ins.getPrevious()) {
			for (Object o : ins.getResultObjects()) {
				if (o instanceof Register && ((Register) o).equals(reg)) {
					return ins;
				}
			}
		}
		return null;
	}

	private boolean isConstSet(Instruction ins) {
		if (ins == null) {
			return false;
		}
		String m = ins.getMnemonicString().toLowerCase();
		// mov/movs/movw rX,#imm  with an immediate (scalar) source and no memory/other reg
		if (m.startsWith("mov") || m.equals("ldr") && ins.toString().contains("[pc")) {
			return ins.toString().matches(".*#0x[0-9a-f]+.*") && !ins.toString().contains("[");
		}
		return false;
	}

	private boolean isStackDst(Instruction ins) {
		if (ins == null) {
			return false;
		}
		String s = ins.toString().toLowerCase();
		return s.contains(",sp") || s.contains(", sp") || s.contains("sp,");
	}

	@Override
	public void run() throws Exception {
		String[] a = getScriptArgs();
		Register r0 = currentProgram.getRegister("r0");
		Register r2 = currentProgram.getRegister("r2");
		int total = 0, varStack = 0, varOther = 0, constLen = 0;
		try (PrintWriter out = new PrintWriter(new FileWriter(a[0]))) {
			for (int i = 1; i < a.length; i++) {
				Address t = toAddr(Long.parseUnsignedLong(a[i].replaceFirst("^0x", ""), 16));
				for (Reference r : getReferencesTo(t)) {
					if (!r.getReferenceType().isCall()) {
						continue;
					}
					Instruction call = getInstructionAt(r.getFromAddress());
					if (call == null) {
						continue;
					}
					total++;
					boolean constR2 = isConstSet(lastWriter(call, r2, 8));
					boolean stackR0 = isStackDst(lastWriter(call, r0, 8));
					Function f = getFunctionContaining(call.getAddress());
					String fn = f == null ? "?" : f.getName();
					if (!constR2 && stackR0) {
						varStack++;
						out.println("VAR-LEN+STACK  " + call.getAddress() + "  [" + fn + "]  "
								+ "copy@" + a[i]);
					} else if (!constR2) {
						varOther++;
					} else {
						constLen++;
					}
				}
			}
			out.println("");
			out.println("total=" + total + " const-len=" + constLen + " var-len-other="
					+ varOther + " VAR-LEN+STACK=" + varStack);
		}
		println("AuditCopyArm: total=" + total + " VAR-LEN+STACK=" + varStack
				+ " var-other=" + varOther + " const=" + constLen);
	}
}
