"""PyInstaller entry for the windowed app (double-click → GUI)."""
from avrfix import gui

if __name__ == "__main__":
    raise SystemExit(gui.main())
