# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — run from the installer/ directory:
#   pyinstaller packaging/avrfix.spec
# Builds a windowed GUI app (double-click) and a console CLI binary. Bundles the byte-diff
# patch (data/) — NO Denon firmware. Pure-stdlib app, so the bundle stays small.
#
# Paths are absolute, derived from SPECPATH (the spec's own directory), so the build does not
# depend on the current working directory.
import os
import sys

SPEC_DIR = os.path.abspath(SPECPATH)            # installer/packaging
INSTALLER = os.path.dirname(SPEC_DIR)           # installer
DATA_SRC = os.path.join(INSTALLER, "avrfix", "data", "dm850i_ssdp.patch.json")
DATAS = [(DATA_SRC, os.path.join("avrfix", "data"))]
HIDDEN = ["avrfix.gui", "avrfix.cli", "avrfix.flasher", "avrfix.acquire", "avrfix.patch"]

gui_a = Analysis([os.path.join(SPEC_DIR, "entry_gui.py")], pathex=[INSTALLER],
                 datas=DATAS, hiddenimports=HIDDEN, noarchive=False)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(gui_pyz, gui_a.scripts, gui_a.binaries, gui_a.datas, [],
              name="AVR-4306-Fix", console=False)

cli_a = Analysis([os.path.join(SPEC_DIR, "entry_cli.py")], pathex=[INSTALLER],
                 datas=DATAS, hiddenimports=HIDDEN, noarchive=False)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(cli_pyz, cli_a.scripts, cli_a.binaries, cli_a.datas, [],
              name="avr-4306-fix-cli", console=True)

# macOS only: wrap the windowed app in a .app bundle with the Local Network usage string.
if sys.platform == "darwin":
    app = BUNDLE(gui_exe, name="AVR-4306-Fix.app",
                 bundle_identifier="org.community.avr4306fix",
                 info_plist={
                     "NSLocalNetworkUsageDescription":
                         "This app contacts your Denon AVR-4306 on your local network to apply "
                         "the network-module firmware fix.",
                     "LSMinimumSystemVersion": "11.0",
                     "CFBundleShortVersionString": "1.0.1",
                 })
