;; M32C toolchain + simulator self-test.
;; Proves the assemble -> link -> simulate loop the firmware rebuild is validated against.
;; Uses the GNU m32c sim's semihosting: a 16-bit write to 0x402 prints "SimTrace: <pc> <v>",
;; a byte write of 1 to 0x400 is SYS_exit.
	.text
	.global _start
_start:
	mov.w	#0x1234, r0
	add.w	#0x1111, r0		; r0 = 0x2345
	mov.w	r0, 0x402		; expect SimTrace ... 2345
	mov.w	#0x0007, r1
	mulu.w	#0x0003, r1		; r1 = 0x15
	mov.w	r1, 0x402		; expect SimTrace ... 0015
	mov.b	#1, 0x400		; SYS_exit
1:	jmp.b	1b
