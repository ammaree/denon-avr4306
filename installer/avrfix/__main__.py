"""Entry point. `python -m avrfix` runs the guided CLI; `--gui` launches the GUI.
A packaged double-click build launches the GUI (see packaging/)."""
import sys


def main():
    argv = sys.argv[1:]
    if "--gui" in argv:
        from . import gui
        return gui.main()
    from . import cli
    return cli.main([a for a in argv if a != "--cli"])


if __name__ == "__main__":
    sys.exit(main() or 0)
