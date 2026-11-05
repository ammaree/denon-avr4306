/* Link the MAIN dump hook into the erased tail of MAIN 01.00 (docs/main-dump-patch.md). */
SECTIONS
{
	. = 0xFA9700;
	.hook : { *(.hook) }
	/DISCARD/ : { *(.data) *(.bss) *(.text) }
}
