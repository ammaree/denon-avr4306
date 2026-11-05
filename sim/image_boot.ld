/* Boot-capable layout: firmware image at its true address, plus the bootstrap
 * stub placed in the empty boot-block region (0xFFC000-0xFFFFFF, absent from the
 * package). The reset vector at 0xFFFFFC points at the stub; the stub sets the
 * pointers and jumps to START_ADDR. The sim boots an SREC from the reset vector. */
ENTRY(_stub)

MEMORY {
  ram  (rwx) : ORIGIN = 0x000400, LENGTH = 0x00C000   /* M32C/87 internal RAM, 48 KB */
  rom  (rx)  : ORIGIN = 0xF00000, LENGTH = 0x0FC000    /* flash in the package, 1008 KB */
  boot (rx)  : ORIGIN = 0xFFC000, LENGTH = 0x004000    /* boot-block gap, 16 KB (synth) */
}

SECTIONS {
  .image IMAGE_VMA : { KEEP(*(.image)) } > rom
  .stub  0xFFC000  : { KEEP(*(.stub)) }  > boot
  .resetvec 0xFFFFFC : { LONG(0xFFC000) }   /* reset -> stub */
  .bss   (NOLOAD) : { *(.bss) *(COMMON) } > ram
  /DISCARD/ : { *(.comment) *(.note*) }
}
