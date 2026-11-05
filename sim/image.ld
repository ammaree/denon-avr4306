/* Place a raw firmware image at its true load address so the m32c simulator can run it.
 * The image blob is turned into object .image by objcopy -I binary; this script pins it
 * at IMAGE_VMA (passed with --defsym). A reset/entry stub, if linked in, goes in .stub. */
ENTRY(_start)

MEMORY {
  ram  (rwx) : ORIGIN = 0x000400, LENGTH = 0x00C000   /* M32C/87 internal RAM, 48 KB */
  rom  (rx)  : ORIGIN = 0xF00000, LENGTH = 0x100000    /* internal flash, 1 MB         */
}

SECTIONS {
  .image IMAGE_VMA : { KEEP(*(.image)) } > rom
  /* Synthesize the M32C reset vector (missing from the package, lives in the boot block)
   * so the simulator, which boots an SREC from 0xFFFFFC, starts at the chosen address. */
  .resetvec 0xFFFFFC : { LONG(START_ADDR) }
  .bss   (NOLOAD) : { *(.bss) *(COMMON) } > ram
  /DISCARD/ : { *(.comment) *(.note*) }
}
