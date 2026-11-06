@ Dispatch-guard cave for the M-SEARCH path, linked at 0x601CE820 (Thumb, ARMv5T).
@ It replaces the two instructions receiveData (0x601360E0) runs just before it
@ dispatches Disc_Srv_Search_Req at 0x60136178:
@   0x60136174  ldr r0, [sp, #0x274]   (9d 98)   -- the ST string pointer
@   0x60136176  adds r3, r6, #0        (33 1c)   -- Disc_Srv_Search_Req arg
@ r2 holds the ST value length (loaded at 0x60136172 and used by both URN arms as
@ the total length from which the reply "rest" copy is derived). A length over 0x40
@ cannot be a well-formed UPnP ST and would let urn_service_reply / urn_device_reply
@ copy past their 0x64 / 0x5C stack frames, so drop the datagram before the search.
@ This is the second line of defence in front of the per-arm guards (ssdp_guard.S).
.syntax unified
.thumb
.arch armv5t
.global msearch_guard
.type msearch_guard, %function
msearch_guard:
	ldr	r0, [sp, #0x274]	@ displaced: ST string pointer
	adds	r3, r6, #0		@ displaced: Disc_Srv_Search_Req arg
	cmp	r2, #0x40
	bhi	.Ldrop
	bx	lr			@ r2 in range -> 0x60136178, dispatch as normal
.Ldrop:
	ldr	r3, .Lret
	bx	r3			@ -> 0x6013618A, receiveData's drop/return path
	.align	2
.Lret:
	.word	0x6013618B
