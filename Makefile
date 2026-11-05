# Denon AVR-4306 firmware RE — extraction / disassembly / verification harness.
#
# The original Denon images are not in this repo. Point SRC at the local folder that
# holds the update tools, then `make images`. Everything lands in build/ (git-ignored).
#
#   make images     extract + de-invert all firmware images into build/images
#   make verify     check build/images against ref/images.sha256
#   make disasm     disassemble MAIN/SUB/DM850 into build/disasm
#   make clean

SRC ?= $(HOME)/Library/CloudStorage/ProtonDrive-andrem@kss.co.za-folder/FamilyShare/Vendors/Hifi/Denon
UPD ?= $(SRC)/AVR-4306_Upgrade_6_0_0_4.zip
BUILD := build
IMAGES := $(BUILD)/images
DISASM := $(BUILD)/disasm

.PHONY: images verify disasm sim-selftest sim-uarttest clean
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

verify: images
	@cd $(IMAGES) && shasum -a 256 -c <(sed 's#.*/##' $(CURDIR)/ref/images.sha256) 2>/dev/null \
	   || (echo "verify: regenerating comparison"; \
	       cd $(IMAGES) && for f in *.flash.bin; do \
	         h=$$(shasum -a 256 "$$f" | cut -c1-64); \
	         grep -q "$$h" $(CURDIR)/ref/images.sha256 && echo "OK   $$f" || echo "FAIL $$f"; \
	       done)

disasm: images
	sh tools/disasm.sh $(IMAGES) $(DISASM)

sim-selftest:
	sh tools/sim.sh selftest

sim-uarttest:
	sh tools/sim.sh uarttest

clean:
	rm -rf $(BUILD)
