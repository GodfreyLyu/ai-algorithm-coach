"""Run the local command line interface when Python loads this package."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
