"""Identify local Web stores and verify packaged UI assets without Web dependencies."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from .service import Coach

API_VERSION = "1"
RUNTIME_PROTOCOL = 1
SERVICE_NAME = "algorithm-coach-web"
UI_MANIFEST = "coach-ui-manifest.json"


def store_id(database: Path, workspace_id: str) -> str:
    """Bind a workspace identity to its canonical local database location.

    Inputs: An existing database path and its saved workspace ID.
    Outputs: A deterministic SHA-256 identifier without a readable private path.
    Logic: Hash an unambiguous canonical pair; copied stores have different IDs.
    Dependencies: pathlib, hashlib, and JSON. This identifier is not a credential.
    """
    body = json.dumps([str(Path(database).resolve()), workspace_id], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def workspace_identity(data_dir: Path) -> dict:
    """Read store identity through the public core without initialization.

    Inputs: An absolute private data directory.
    Outputs: workspace_id and its location-bound store_id.
    Logic: Open and close one Coach and derive the local store identifier.
    Dependencies: Coach and store_id. Missing or old stores remain unchanged.
    """
    database = Path(data_dir) / "coach.sqlite3"
    coach = Coach(database)
    try:
        identity = coach.get_workspace_identity()
        return {**identity, "store_id": store_id(database, identity["workspace_id"])}
    finally:
        coach.close()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous resource manifests.

    Inputs: JSON object pairs from a resource manifest.
    Outputs: A dictionary with unique keys.
    Logic: Refuse duplicate keys instead of silently replacing a file hash.
    Dependencies: The standard JSON parser.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest field")
        result[key] = value
    return result


def inspect_ui(static_dir: Path | None, *, include_files: bool = False) -> dict:
    """Check the complete UI inventory before reporting feedback readiness.

    Inputs: A static directory and an optional validated-inventory request.
    Outputs: Readiness, build identity, failure reason, and optional safe file hashes.
    Logic: Validate the manifest, safe regular files, inventory, and content hashes.
    Dependencies: pathlib, hashlib, and JSON. Never builds or installs anything.
    """
    failed = {"ui_ready": False, "ui_build_id": None, "reason": "assets_missing"}
    if static_dir is None:
        return failed
    directory = Path(static_dir)
    manifest = directory / UI_MANIFEST
    try:
        if not directory.is_dir() or directory.is_symlink() or not manifest.is_file() or manifest.is_symlink():
            return failed
        if manifest.stat().st_size > 1_048_576:
            raise ValueError("Manifest too large")
        record = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
        files = record["files"]
        if record.get("format_version") != 1 or record.get("api_version") != API_VERSION:
            return {**failed, "reason": "assets_incompatible"}
        if not isinstance(files, dict) or not files or "index.html" not in files or len(files) > 10_000:
            raise ValueError("Invalid inventory")
        for name, digest in files.items():
            relative = PurePosixPath(name)
            if not isinstance(name, str) or not name or "\\" in name or relative.is_absolute() or ".." in relative.parts or str(relative) != name or name == UI_MANIFEST:
                raise ValueError("Unsafe resource path")
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("Invalid resource hash")
            resource = directory / name
            if any((directory / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)):
                raise ValueError("Linked resource")
            if not resource.is_file() or hashlib.sha256(resource.read_bytes()).hexdigest() != digest:
                raise ValueError("Resource hash mismatch")
        entries = list(directory.rglob("*"))
        if any(item.is_symlink() for item in entries):
            raise ValueError("Linked resource directory")
        inventory = {item.relative_to(directory).as_posix() for item in entries if item.is_file() and item != manifest}
        if inventory != set(files):
            raise ValueError("Resource inventory mismatch")
        canonical = json.dumps(files, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if record.get("build_id") != expected:
            raise ValueError("Build identity mismatch")
        ready = {"ui_ready": True, "ui_build_id": expected, "reason": None}
        if include_files:
            ready["ui_files"] = files
        return ready
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {**failed, "reason": "assets_invalid"}
