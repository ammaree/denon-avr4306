# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — run from the installer/ directory:
#   pyinstaller packaging/avrfix.spec
# Builds a windowed GUI app (double-click) and a console CLI binary. Bundles the byte-diff
# patch (data/) — NO Denon firmware. Pure-stdlib app, so the bundle stays small.
import os

INSTALLER = os.path.abspath(os.getcwd())
DATAS = [(os.path.join("avrfix", "data", "dm850i_ssdp.patch.json"),
          os.path.join("avrfix", "data"))]
HIDDEN = ["avrfix.gui", "avrfix.cli", "avrfix.flasher", "avrfix.acquire", "avrfix.patch"]

gui_a = Analysis([os.path.join("packaging", "entry_gui.py")], pathex=[INSTALLER],
                 datas=DATAS, hiddenimports=HIDDEN, noarchive=False)
gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data)
gui_exe = EXE(gui_pyz, gui_a.scripts, gui_a.binaries, gui_a.datas, [],
              name="AVR-4306-Fix", console=False, disable_windowed_traceback=False,
              icon=None)

cli_a = Analysis([os.path.join("packaging", "entry_cli.py")], pathex=[INSTALLER],
                 datas=DATAS, hiddenimports=HIDDEN, noarchive=False)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data)
cli_exe = EXE(cli_pyz, cli_a.scripts, cli_a.binaries, cli_a.datas, [],
              name="avr-4306-fix-cli", console=True)

# macOS: wrap the windowed app in a .app bundle with the Local Network usage string so the
# OS permission prompt is legible and the app is identified consistently.
app = BUNDLE(gui_exe, name="AVR-4306-Fix.app", icon=None,
             bundle_identifier="org.community.avr4306fix",
             info_plist={
                 "NSLocalNetworkUsageDescription":
                     "This app contacts your Denon AVR-4306 on your local network to apply the "
                     "network-module firmware fix.",
                 "LSMinimumSystemVersion": "11.0",
                 "CFBundleShortVersionString": "1.0.0",
             })
