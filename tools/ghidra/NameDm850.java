// Name DM850 functions from the diagnostic strings they reference, then apply
// the names recovered by hand from those same references (docs/dm850-map.md,
// docs/dm850-audit.md). Run after LoadDm850. The string pass only fires for a
// C string containing "::": the function is the PUSH-with-LR before a Thumb
// literal load of that string. The fixed table is applied last.
//@category Denon
import java.math.BigInteger;
import java.util.HashMap;
import java.util.Map;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

public class NameDm850 extends GhidraScript {
	private ghidra.program.model.mem.Memory mem;
	private static final long SDRAM = 0x60008000L;
	private static final long SDRAM_LEN = 0x1DF9D0L;

	private static final long[][] FIXED = {
		{0x60012104L, 1}, {0x600123A4L, 1}, {0x60011798L, 1}, {0x60012244L, 1},
		{0x600122C0L, 1}, {0x60011C90L, 0}, {0x60011284L, 1},
		{0x60049650L, 1}, {0x6004A788L, 1}, {0x60049A80L, 1}, {0x6004A114L, 1},
		{0x600496B4L, 1}, {0x60067050L, 1}, {0x6006FCFCL, 1},
		{0x6006F938L, 1}, {0x6006FA98L, 1}, {0x60070A5CL, 1}, {0x60070974L, 1},
		{0x60070BBCL, 1}, {0x60124BA4L, 1}, {0x601360E0L, 1}, {0x60063BA4L, 1},
		{0x6010CF24L, 1}, {0x6004DA20L, 0}, {0x60104B9CL, 1},
		{0x600459FCL, 1}, {0x600459F4L, 1}, {0x600D43F4L, 1},
	};
	private static final String[] FIXED_NAME = {
		"strchr", "strstr", "memcmp", "strlen", "strncmp", "memcpy", "sprintf",
		"upnp_disc_thread_create", "upnp_disc_thread", "disc_srv_type_switch",
		"disc_srv_search_req", "disc_srv_schedule", "req_prs_translate_req",
		"udp_rec_check_msearch_req", "upnp_tcp_thread_create", "upnp_tcp_thread",
		"urn_service_reply", "urn_device_reply", "service_name_lookup",
		"pk_alloc", "UPnPModuleImpl_receiveData", "set_dim_psdim", "tcp_out",
		"denon_link_send", "ssdp_rec_udp", "swap_spaces_thread_create",
		"swap_spaces_thread", "dhcp_client_log",
	};

	private Register tmode;

	private void nameAt(long va, String name, boolean thumb) throws Exception {
		Address a = toAddr(va);
		if (getInstructionAt(a) == null) {
			if (tmode != null) {
				currentProgram.getProgramContext().setValue(tmode, a, a,
						thumb ? BigInteger.ONE : BigInteger.ZERO);
			}
			disassemble(a);
		}
		Function f = getFunctionAt(a);
		if (f == null) {
			f = createFunction(a, name);
		}
		if (f != null && f.getEntryPoint().equals(a)) {
			f.setName(name, SourceType.USER_DEFINED);
		}
	}

	private int readU16(long va) throws Exception {
		byte[] b = new byte[2];
		mem.getBytes(toAddr(va), b);
		return (b[0] & 0xFF) | ((b[1] & 0xFF) << 8);
	}

	private long readU32(long va) throws Exception {
		return getInt(toAddr(va)) & 0xFFFFFFFFL;
	}

	private long pushBefore(long va) throws Exception {
		for (long p = va; p > va - 0x400 && p >= SDRAM; p -= 2) {
			int h = readU16(p);
			if ((h & 0xFF00) == 0xB500 && (h & 0x0100) != 0) {
				return p;
			}
		}
		return 0;
	}

	private static String methodName(String s) {
		int col = s.indexOf("::");
		if (col < 1) {
			return null;
		}
		String cls = s.substring(0, col).replaceAll("[^A-Za-z0-9_]", "");
		String rest = s.substring(col + 2);
		int end = 0;
		while (end < rest.length()) {
			char c = rest.charAt(end);
			if (!(Character.isLetterOrDigit(c) || c == '_')) {
				break;
			}
			end++;
		}
		if (cls.isEmpty() || end == 0) {
			return null;
		}
		return cls + "_" + rest.substring(0, end);
	}

	@Override
	public void run() throws Exception {
		mem = currentProgram.getMemory();
		tmode = currentProgram.getLanguage().getRegister("TMode");
		MemoryBlock body = mem.getBlock(toAddr(SDRAM));
		if (body == null) {
			printerr("NameDm850: SDRAM block missing; run LoadDm850 first");
			return;
		}
		byte[] raw = new byte[(int) SDRAM_LEN];
		mem.getBytes(toAddr(SDRAM), raw);

		Map<Long, String> want = new HashMap<Long, String>();
		int i = 0;
		while (i < raw.length) {
			if (raw[i] < 32) {
				i++;
				continue;
			}
			int e = i;
			while (e < raw.length && raw[e] != 0 && e - i < 120) {
				e++;
			}
			if (e < raw.length && raw[e] == 0 && e - i >= 8) {
				boolean printable = true;
				for (int k = i; k < e; k++) {
					int c = raw[k] & 0xFF;
					if (c < 32 || c > 126) {
						printable = false;
						break;
					}
				}
				if (printable) {
					String s = new String(raw, i, e - i, "ISO-8859-1");
					String mn = methodName(s);
					if (mn != null) {
						want.put(SDRAM + i, mn);
					}
				}
			}
			i = (e < raw.length && raw[e] == 0) ? e + 1 : e;
		}

		int named = 0;
		for (long va = SDRAM; va + 2 < SDRAM + SDRAM_LEN; va += 2) {
			int h = (raw[(int) (va - SDRAM)] & 0xFF)
					| ((raw[(int) (va - SDRAM) + 1] & 0xFF) << 8);
			if (h < 0x4800 || h > 0x4FFF) {
				continue;
			}
			long lit = (va + 4) & ~3L;
			lit += (h & 0xFF) * 4L;
			if (lit < SDRAM || lit + 4 > SDRAM + SDRAM_LEN) {
				continue;
			}
			long ptr = readU32(lit);
			String mn = want.get(ptr);
			if (mn == null) {
				continue;
			}
			long fn = pushBefore(va);
			if (fn == 0 || getFunctionAt(toAddr(fn)) != null) {
				continue;
			}
			try {
				nameAt(fn, mn, true);
				named++;
			} catch (Exception ex) {
				println("skip " + Long.toHexString(fn) + " " + ex.getMessage());
			}
		}
		println("NameDm850: " + named + " functions from :: strings");

		for (int n = 0; n < FIXED.length; n++) {
			try {
				nameAt(FIXED[n][0], FIXED_NAME[n], FIXED[n][1] == 1);
			} catch (Exception ex) {
				println("fixed " + FIXED_NAME[n] + " " + ex.getMessage());
			}
		}
		println("NameDm850: fixed names applied");
	}
}
