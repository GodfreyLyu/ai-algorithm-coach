"""Build a standalone Skill directory from the single maintained core source."""

import argparse
import json
from pathlib import Path
import shutil


def build(output: Path) -> dict:
    """Copy Skill guidance and runtime into a new output directory.

    Inputs: An absolute path that does not yet exist.
    Outputs: A summary with the output path and runtime source.
    Logic: Copy only public Skill files and core source. Remove partial output on failure.
    Dependencies: pathlib, shutil, and this source checkout. No build service is used.
    """
    root = Path(__file__).resolve().parents[1]
    if not output.is_absolute():
        raise ValueError("The output path must be absolute.")
    output = output.resolve()
    for protected in (root / "src", root / "skills", root / "scripts"):
        if output == protected or protected in output.parents:
            raise ValueError("Do not build into a source directory.")
    output.mkdir(parents=True, exist_ok=False)
    try:
        source = root / "skills" / "algorithm-coach"
        shutil.copytree(source, output, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(root / "src" / "algorithm_coach", output / "lib" / "algorithm_coach",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(root / "LICENSE", output / "LICENSE")
    except BaseException:
        shutil.rmtree(output)
        raise
    return {"output": str(output), "runtime": "lib/algorithm_coach", "network_required": False}


def main() -> int:
    """Read a destination and build a standalone bundle.

    Inputs: The required --output path.
    Outputs: A JSON summary and process exit code.
    Logic: Refuse existing destinations and print a clear error on failure.
    Dependencies: argparse, build, and stdout.
    """
    parser = argparse.ArgumentParser(description="Build a standalone algorithm-coach Skill.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = {"ok": True, "data": build(args.output)}
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
