"""PyInstaller entry for the console CLI."""
from avrfix import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
