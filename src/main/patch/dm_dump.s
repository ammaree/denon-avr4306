; MAIN 01.00 read-only memory dump hook ("DM" query).  docs/main-dump-patch.md
;
; Patch: the first 4 bytes of 0xF4B1C0 (enter #0xc; pushm r2,a0) become
; jmp.a dm_hook.  0xF4B1C0 is called once per received line, from 0xF45F97 (UART1 /
; rear RS-232, line buffer 0x4A45) and 0xF4603B (UART0 / DM850 link, line 0x528E),
; with the line pointer pushed on the stack (8[fb] after enter); it returns a reply id
; in r0, 0x113 = "no reply".
;
; dm_hook re-executes the displaced prologue, then:
;   line == "DMaaaaaa?\r" (6 upper-case hex digits), aaaaaa in 0xF00000..0xFFFFE0,
;   line buffer 0x528E or 0x4A45:
;       wait until that channel's TX-busy bit (bit 4 of 0x5319 / 0x5279) is clear,
;       send "DMaaaaaa" + 32 bytes as 64 hex digits + CR by polling the UART,
;       return 0x113 through the original epilogue.
;   anything else: jmp.a 0xF4B1C4 with all registers as the original left them.
; It reads flash only and writes only the UART transmit register and its own
; stack frame. Every wait has a bounded loop count.

	.section .hook,"ax",@progbits
	.global dm_hook

U0TB	= 0x36A
U0C1	= 0x36D
U1TB	= 0x2EA
U1C1	= 0x2ED
TXBSY0	= 0x5319		; UART0 TX state, bit 4 = ISR sending
TXBSY1	= 0x5279		; UART1 TX state, bit 4 = ISR sending
LINE0	= 0x528E
LINE1	= 0x4A45

dm_hook:
	.byte	0xEC, 0x0C		; enter #0xc     (displaced from 0xF4B1C0)
	.byte	0x8F, 0x28		; pushm r2,a0    (displaced from 0xF4B1C2)
	pushm	r0,r1,r2,r3,a0,a1	; pass-through restores all of them
	mov.l	8[fb], a0		; line pointer

	mov.w	#0, r3			; r3 = channel: 0 = UART0, 1 = UART1
	cmp.l	#LINE0, a0
	jeq	1f
	mov.w	#1, r3
	cmp.l	#LINE1, a0
	jne	pass
1:	cmp.b	#'D', [a0]
	jne	pass
	cmp.b	#'M', 1[a0]
	jne	pass
	cmp.b	#'?', 8[a0]
	jne	pass
	cmp.b	#0x0D, 9[a0]
	jne	pass

	; parse 6 hex digits at line[2..7] into r2r0
	mov.l	#0, r2r0
	mov.l	a0, a1
	add.l	#2, a1
	mov.w	#6, r1
2:	push.w	r1
	mov.b	[a1], r1l
	sub.b	#'0', r1l
	jltu	bad			; < '0'
	cmp.b	#10, r1l
	jltu	3f			; '0'..'9'
	sub.b	#7, r1l			; 'A' -> 10
	cmp.b	#10, r1l
	jltu	bad
	cmp.b	#16, r1l
	jgeu	bad
3:	shl.l	#4, r2r0
	or.b	r1l, r0l
	pop.w	r1
	add.l	#1, a1
	sub.w	#1, r1
	jne	2b

	cmp.l	#0xF00000, r2r0
	jltu	pass
	cmp.l	#0xFFFFE0, r2r0
	jgtu	pass
	mov.l	r2r0, a1		; a1 = read pointer

	; wait for the interrupt-driven sender on this channel to be idle
	mov.l	#0x40000, a0
4:	cmp.w	#0, r3
	jne	5f
	btst	4, TXBSY0
	jmp.b	6f
5:	btst	4, TXBSY1
6:	jeq	7f			; bit clear: idle
	sub.l	#1, a0
	jne	4b
	jmp.w	done			; still busy: give up, no reply

7:	mov.b	#'D', r1l
	jsr.w	putc
	mov.b	#'M', r1l
	jsr.w	putc
	mov.l	a1, r2r0
	mov.w	r2, r1
	jsr.w	puthex			; address bits 23..16
	mov.b	r0h, r1l
	jsr.w	puthex			; bits 15..8
	mov.b	r0l, r1l
	jsr.w	puthex			; bits 7..0
	mov.w	#32, r2
8:	mov.b	[a1], r1l
	jsr.w	puthex
	add.l	#1, a1
	sub.w	#1, r2
	jne	8b
	mov.b	#0x0D, r1l
	jsr.w	putc

done:	popm	r0,r1,r2,r3,a0,a1
	mov.w	#0x113, r0
	.byte	0x8E, 0x14		; popm r2,a0  (as at 0xF4B2E0)
	.byte	0xFC			; exitd

bad:	pop.w	r1
pass:	popm	r0,r1,r2,r3,a0,a1	; registers exactly as after the displaced prologue
	jmp.a	0xF4B1C4

; puthex: send r1l as two upper-case hex digits. Clobbers r1.
puthex:
	push.w	r1
	shl.b	#-4, r1l
	jsr.w	nib
	pop.w	r1
	and.b	#0x0F, r1l
nib:	and.b	#0x0F, r1l
	add.b	#'0', r1l
	cmp.b	#'9'+1, r1l
	jltu	putc
	add.b	#7, r1l
	; fall through

; putc: wait (bounded) for the channel's transmit buffer to be empty, then send r1l.
; Channel in r3. Clobbers a0.
putc:
	mov.l	#0x4000, a0
1:	cmp.w	#0, r3
	jne	2f
	btst	1, U0C1			; TI
	jmp.b	3f
2:	btst	1, U1C1
3:	jne	4f			; TI set: buffer empty
	sub.l	#1, a0
	jne	1b
4:	cmp.w	#0, r3
	jne	5f
	mov.b	r1l, U0TB
	rts
5:	mov.b	r1l, U1TB
	rts
