;; RX-ISR demonstration seed — stands in for the boot block's startup just enough
;; to exercise the UART1 receive ISR at 0xF01704. Startup (absent, in the boot
;; block) would initialise the RX ring-buffer control block in RAM; here we seed
;; the write pointer (0x31A0) to a scratch buffer at 0x3200 and the index (0x3196)
;; to 0, then enter the ISR. Fed a byte on UART1 RX, the ISR reads U1RB (0x2ee),
;; stores the byte at 0x3200, and advances the pointer to 0x3201 -- the enqueue
;; the parser's dequeue side (0xF01242) later consumes.
	.section .stub,"ax",@progbits
	.global _stub
_stub:
	ldc	#0x00C000, sp
	mov.w	#0x3200, 0x31a0		; RX write pointer -> scratch buffer
	mov.b	#0x00, 0x31a2		; pointer high byte
	mov.w	#0x0000, 0x3196		; index/count = 0
	jmp.a	0xF01704		; enter UART1 receive ISR
