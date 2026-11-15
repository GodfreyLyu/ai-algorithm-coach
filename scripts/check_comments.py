"""Check file descriptions and Python function contracts required by this project."""

import ast
from pathlib import Path


def check(root: Path) -> list[str]:
    """Find source files with missing descriptions or function contracts.

    Inputs: The project root.
    Outputs: A list of human-readable failures.
    Logic: Skip generated paths, inspect Python ASTs, and inspect text headers.
    Dependencies: ast, pathlib, and UTF-8 source files.
    """
    failures = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in {".git", ".venv", "__pycache__", "dist", "build"}
                                     or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".yml", ".yaml"} and path.name not in {
            ".gitignore", "LICENSE", "CODEOWNERS"
        }:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            tree = ast.parse(text, filename=str(relative))
            if not ast.get_docstring(tree):
                failures.append(f"{relative}: missing file description")
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node) or ""
                    if not all(label in doc for label in ("Inputs:", "Outputs:", "Logic:", "Dependencies:")):
                        failures.append(f"{relative}:{node.lineno}: incomplete contract for {node.name}")
        elif path.name == "SKILL.md":
            if not text.startswith("---\n# "):
                failures.append(f"{relative}: missing YAML file description")
        elif path.suffix == ".md":
            if not text.startswith("<!-- "):
                failures.append(f"{relative}: missing file description")
        elif not text.startswith("# "):
            failures.append(f"{relative}: missing file description")
    return failures


def main() -> int:
    """Report documentation contract failures.

    Inputs: None. Use the source checkout that contains this script.
    Outputs: Exit code 0 when all maintained files comply.
    Logic: Print each failure or a single success message.
    Dependencies: check, pathlib, and stdout.
    """
    failures = check(Path(__file__).resolve().parents[1])
    for failure in failures:
        print(failure)
    if not failures:
        print("File descriptions and function contracts passed.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
