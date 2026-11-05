;; UART1 echo — validates the scripted-controller bridge through the sim's real
;; UART1 model: status U1C1=0x2ed (bit1 set when a byte is waiting), RX U1RB=0x2ee,
;; TX U1TB=0x2ea. Reads each byte the harness feeds on stdin and echoes it back to
;; stdout, upper-cased if alphabetic, so the round trip is visible and transformed.
	.text
	.global _start
_start:
	ldc	#0x00C000, sp
poll:
	mov.b	0x2ed, r0l		; U1C1 status
	and.b	#0x02, r0l		; RX-full bit
	jeq	poll
	mov.b	0x2ee, r0l		; U1RB -> r0l (consumes one byte)
	cmp.b	#'a', r0l
	jltu	send
	cmp.b	#'z', r0l
	jgtu	send
	sub.b	#0x20, r0l		; lower->upper
send:
	mov.b	r0l, 0x2ea		; U1TB -> stdout
	jmp.b	poll
