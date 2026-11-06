@ Cave for the SSDP service-URN arm, linked at 0x601CE800 (Thumb, ARMv5T).
@ The search at 0x60049B32 has just returned in r0. A version colon leaves r0
@ pointing at it; a name with no colon (urn:Belkin:service:basicevent) leaves
@ r0 == 0. The bytes this replaces are `subs r0, r0, r6` / `lsls r7, r0, #16`
@ at 0x60049B36. On the zero return, branch to 0x60049B76, which is `movs r0, #0`
@ and the type switch's epilogue: the reply builder is not called.
.syntax unified
.thumb
.arch armv5t
.type ssdp_st_guard, %function
.global ssdp_st_guard
ssdp_st_guard:
	cmp	r0, #0
	beq	.Lnone
	subs	r0, r0, r6
	lsls	r7, r0, #16
	bx	lr
.Lnone:
	ldr	r3, .Lret
	bx	r3
	.align	2
.Lret:
	.word	0x60049B77
