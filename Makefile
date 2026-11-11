# Denon AVR-4306 firmware RE — extraction / disassembly / verification harness.
#
# The original Denon images are not in this repo. Point SRC at the local folder that
# holds the update tools, then `make images`. Everything lands in build/ (git-ignored).
#
#   make images     extract + de-invert all firmware images into build/images
#   make verify     check build/images against ref/images.sha256
#   make disasm     disassemble MAIN/SUB/DM850 into build/disasm
#   make clean

SRC ?= $(HOME)/denon-avr4306-firmware
UPD ?= $(SRC)/AVR-4306_Upgrade_6_0_0_4.zip
BUILD := build
IMAGES := $(BUILD)/images
DISASM := $(BUILD)/disasm

.PHONY: images verify disasm sim-selftest sim-uarttest sim-writetest sim-toolstest clean
.DEFAULT_GOAL := images

# Unpack the updater zip (and the recovery package if present) into build/, then extract.
$(IMAGES)/manifest.txt:
	@mkdir -p $(BUILD)/pkg $(IMAGES)
	@cd $(BUILD)/pkg && unzip -o -q -j "$(UPD)" '*.exe' || true
	@# FWCV recovery package (InstallShield) if the zip is alongside:
	@if [ -f "$(SRC)/RECOVERY Firmware Network AVR-4306.zip" ]; then \
	   mkdir -p $(BUILD)/rec && cd $(BUILD)/rec && \
	   unzip -o -q "$(SRC)/RECOVERY Firmware Network AVR-4306.zip" && \
	   D=$$(find . -name data1.cab -exec dirname {} \;) && \
	   command -v unshield >/dev/null && unshield -d . x "$$D/data1.cab" >/dev/null 2>&1 || true; \
	 fi
	python3 -I tools/extract.py $(IMAGES) \
	   $(BUILD)/pkg/*.exe \
	   $$(find $(BUILD)/rec -name 'FWCV_*.bin' 2>/dev/null)

images: $(IMAGES)/manifest.txt

# Portable (POSIX sh): compare each extracted image's sha256 against ref/images.sha256.
# Note: make runs recipes with /bin/sh, so no bash process substitution here.
verify: images
	@cd $(IMAGES) && ok=0; bad=0; \
	 for f in *.flash.bin; do \
	   h=$$(shasum -a 256 "$$f" | cut -c1-64); \
	   if grep -q "$$h" $(CURDIR)/ref/images.sha256; then \
	     echo "OK   $$f"; ok=$$((ok+1)); \
	   else echo "FAIL $$f"; bad=$$((bad+1)); fi; \
	 done; \
	 echo "verify: $$ok OK, $$bad FAIL (ref has $$(grep -c . $(CURDIR)/ref/images.sha256))"; \
	 [ $$bad -eq 0 ]

disasm: images
	sh tools/disasm.sh $(IMAGES) $(DISASM)

sim-selftest:
	sh tools/sim.sh selftest

sim-uarttest:
	sh tools/sim.sh uarttest

# MAIN-only writer (tools/loader_client.py write) against sim/fake_unit.py. Needs the two
# built images; add SLOW=1 for the ~17 s full update-mode-entry case.
sim-writetest:
	python3 -I sim/test_main_write.py \
	   $(IMAGES)/MAIN_01.00.flash.bin $(BUILD)/patch/MAIN_dm.flash.bin $(if $(SLOW),--slow,)

# The other tools (status, settings-save/restore, verify, rollback, session log).
sim-toolstest:
	python3 -I sim/test_tools.py \
	   $(IMAGES)/MAIN_01.00.flash.bin $(BUILD)/patch/MAIN_dm.flash.bin

clean:
	rm -rf $(BUILD)
