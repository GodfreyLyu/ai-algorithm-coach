"""Build a standalone Skill directory from the single maintained core source."""

import argparse
import json
from pathlib import Path
import shutil
import sys


def build(output: Path, with_web: bool = False, web_assets: Path | None = None) -> dict:
    """Copy Skill guidance and runtime into a new output directory.

    Inputs: A new absolute output path and optional prebuilt public Web assets.
    Outputs: A summary with the output path and runtime source.
    Logic: Validate optional UI assets, copy public files, and remove partial output on failure.
    Dependencies: pathlib, shutil, and this source checkout. No build service is used.
    """
    root = Path(__file__).resolve().parents[2]
    assets = Path(web_assets) if web_assets is not None else root / "web" / "dist"
    if with_web:
        sys.path.insert(0, str(root / "src"))
        from algorithm_coach.web.identity import inspect_ui

        readiness = inspect_ui(assets, include_files=True)
        if not readiness["ui_ready"]:
            raise ValueError("Build and verify the Web UI before creating a Web bundle.")
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
        shutil.copy2(root / "THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
        if with_web:
            from algorithm_coach.web.identity import UI_MANIFEST

            target = output / "assets" / "web"
            target.mkdir(parents=True)
            inventory = readiness["ui_files"]
            for name in (*inventory, UI_MANIFEST):
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(assets / name, destination, follow_symlinks=False)
            copied = inspect_ui(target)
            if not copied["ui_ready"] or copied["ui_build_id"] != readiness["ui_build_id"]:
                raise ValueError("The Web resources changed during packaging.")
            shutil.copy2(root / "requirements-web.txt", output / "requirements-web.txt")
    except BaseException:
        shutil.rmtree(output)
        raise
    return {"output": str(output), "runtime": "lib/algorithm_coach", "network_required": False,
            "web_assets": with_web, "web_dependencies_installed": False}


def main() -> int:
    """Read a destination and build a standalone bundle.

    Inputs: The required --output path.
    Outputs: A JSON summary and process exit code.
    Logic: Refuse existing destinations and print a clear error on failure.
    Dependencies: argparse, build, and stdout.
    """
    parser = argparse.ArgumentParser(description="Build a standalone algorithm-coach Skill.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--with-web", action="store_true", help="Include verified prebuilt feedback UI assets.")
    parser.add_argument("--web-assets", type=Path, help="Use another verified UI build directory.")
    args = parser.parse_args()
    try:
        result = {"ok": True, "data": build(args.output, args.with_web, args.web_assets)}
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
