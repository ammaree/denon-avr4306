@ Cave for the SSDP URN arms, linked at 0x601CE800 (Thumb, ARMv5T). Used by both
@ the service arm (site 0x60049B36) and the device arm (site 0x60049AD0); the
@ replaced bytes `subs r0, r0, r6` / `lsls r7, r0, #16` are identical at both.
@ The preceding strstr has just returned in r0: a version colon leaves r0 pointing
@ at it; a name with no colon (urn:Belkin:service:basicevent, or a device URN with
@ no :N) leaves r0 == 0. On the non-zero path, do the original subtract/shift and
@ bx lr back to whichever site called (0x60049B3A or 0x60049AD4). On the zero
@ return, branch to 0x60049B76 (movs r0, #0 and the type-switch epilogue), so
@ neither reply builder is called.
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
