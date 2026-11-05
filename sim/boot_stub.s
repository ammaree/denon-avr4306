;; Bootstrap stub — stands in for the MAIN M32C boot block (the top 16 KB,
;; 0xFFC000-0xFFFFFF, that no firmware package contains).
;;
;; The real reset path (stack/frame/static-base setup, RAM clear, vector table)
;; lives in that missing block. Without it the sim starts a chosen routine with
;; all registers = 0, so the first [fb]/[sb]-relative access computes an address
;; near 0 and the sim halts ("NULL pointer dereference at pc=...").
;;
;; This stub initialises the pointers to valid internal-RAM addresses, then jumps
;; to the chosen entry (START_ADDR, supplied at link time). The values are valid,
;; not authentic: enough to keep memory accesses inside the 48 KB RAM window
;; (0x000400-0x00C3FF) so a routine runs far enough to observe its peripheral I/O.
;; A routine entered at its own prologue (enter/pushm) overwrites fb itself.
	.section .stub,"ax",@progbits
	.global _stub
_stub:
	ldc	#0x00C000, sp		; ISP: top of RAM, stack grows down
	ldc	#0x00BF00, fb		; frame base mid-RAM (neg offsets stay in RAM)
	ldc	#0x000400, sb		; static base at RAM bottom
	jmp.a	START_ADDR		; link-time entry (reloc filled by ld)
