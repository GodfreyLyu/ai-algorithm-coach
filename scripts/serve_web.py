"""Start the optional local Web adapter from a source checkout."""

from pathlib import Path
import sys


def main() -> int:
    """Load the local HTTP entry point with a useful dependency hint.

    Inputs: Arguments accepted by the optional HTTP adapter.
    Outputs: The server command exit code.
    Logic: Locate repository source and keep optional imports out of the core CLI.
    Dependencies: pathlib and the optional FastAPI Web installation.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        from algorithm_coach.web.http_api import main as run_web
    except ModuleNotFoundError as exc:
        if exc.name not in {"fastapi", "pydantic", "uvicorn"}:
            raise
        print("Install the optional Web dependencies. See docs/web.md.", file=sys.stderr)
        return 1
    return run_web()


if __name__ == "__main__":
    raise SystemExit(main())
