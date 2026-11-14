"""Run the same training core from a source checkout or a standalone Skill bundle."""

import json
from pathlib import Path
import sys


def main() -> int:
    """Find the bundled core and start its command line interface.

    Inputs: Command line arguments and optional ALGORITHM_COACH_DATA_DIR.
    Outputs: The core command exit code and JSON output.
    Logic: Prefer bundled code. Use repository source only in a source checkout.
    Dependencies: Python 3.12 or newer and the local algorithm_coach package.
    """
    if sys.version_info < (3, 12):
        print(json.dumps({"ok": False, "error": {"code": "unsupported_python",
                                                "message": "Use Python 3.12 or newer."}}))
        return 1
    entry = Path(__file__).resolve()
    candidates = [entry.parents[1] / "lib"]
    if len(entry.parents) > 3:
        candidates.append(entry.parents[3] / "src")
    for source in candidates:
        if (source / "algorithm_coach" / "__init__.py").is_file():
            sys.path.insert(0, str(source))
            from algorithm_coach.cli import main as core_main

            return core_main()
    print(json.dumps({"ok": False, "error": {"code": "missing_core",
                                            "message": "Use a complete Skill bundle or source checkout."}}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
