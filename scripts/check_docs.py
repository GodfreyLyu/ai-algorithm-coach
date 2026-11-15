"""Check local Markdown links, heading anchors, and fenced code blocks offline."""

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
INLINE_CODE = re.compile(r"(`+).*?\1")
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)')


def _prose(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """Read Markdown outside fenced code examples.

    Inputs: A UTF-8 Markdown file.
    Outputs: Numbered prose lines and code fence failures.
    Logic: Match closing fence characters and lengths. Retain heading text.
    Dependencies: pathlib and the Markdown patterns in this module.
    """
    lines = []
    opened = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fence = FENCE.match(line)
        if fence:
            marker, suffix = fence.groups()
            if opened is None:
                opened = (marker, number)
            elif marker[0] == opened[0][0] and len(marker) >= len(opened[0]) and not suffix.strip():
                opened = None
        elif opened is None:
            lines.append((number, line))
    failures = [f"{opened[1]}: unclosed code fence"] if opened else []
    return lines, failures


def _anchors(path: Path) -> set[str]:
    """Collect GitHub-style anchors for ATX headings in a local document.

    Inputs: A Markdown path.
    Outputs: Heading anchors, including suffixes for duplicate headings.
    Logic: Remove punctuation, lowercase text, and number repeated slugs.
    Dependencies: re and _prose. Headings use the project's ATX style.
    """
    anchors = set()
    for _, line in _prose(path)[0]:
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            slug = re.sub(r"[^\w\- ]", "", heading[1].lower()).replace(" ", "-")
            anchor = slug
            suffix = 0
            while anchor in anchors:
                suffix += 1
                anchor = f"{slug}-{suffix}"
            anchors.add(anchor)
    return anchors


def check(root: Path) -> list[str]:
    """Find broken links and unclosed code fences in maintained Markdown.

    Inputs: A repository root or a synthetic fixture directory.
    Outputs: Human-readable file and line failures.
    Logic: Scan root documents, docs, skills, and .github. Resolve local links only.
    Dependencies: pathlib, urllib.parse, _prose, and _anchors. No network is used.
    """
    root = root.resolve()
    paths = sorted(root.glob("*.md"))
    for directory in ("docs", "skills", ".github"):
        paths.extend(sorted((root / directory).rglob("*.md")))
    failures = []
    for path in paths:
        relative = path.relative_to(root)
        lines, fence_errors = _prose(path)
        failures.extend(f"{relative}:{error}" for error in fence_errors)
        for number, line in lines:
            for link in LINK.finditer(INLINE_CODE.sub("", line)):
                destination = link[1] or link[2]
                parsed = urlsplit(destination)
                if parsed.scheme in {"https", "http", "mailto"}:
                    continue
                target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
                message = None
                if parsed.scheme or parsed.netloc or not target.is_relative_to(root):
                    message = "local link must stay inside the repository"
                elif not target.exists():
                    message = "missing local link target"
                elif parsed.fragment and target.suffix == ".md" and unquote(parsed.fragment) not in _anchors(target):
                    message = "missing heading anchor"
                if message:
                    failures.append(f"{relative}:{number}: {message}: {destination}")
    return failures


def main() -> int:
    """Report offline documentation failures for this checkout.

    Inputs: None. Use the root that contains this script.
    Outputs: Exit code 0 when documentation links and fences pass.
    Logic: Print failures or one success message.
    Dependencies: check, pathlib, and stdout.
    """
    failures = check(Path(__file__).resolve().parents[1])
    for failure in failures:
        print(failure)
    if not failures:
        print("Markdown links, heading anchors, and code fences passed.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
