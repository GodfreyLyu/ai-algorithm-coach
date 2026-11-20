"""Verify store separation and complete UI resource identity using synthetic files."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from algorithm_coach.service import Coach
from algorithm_coach.errors import CoachError
from algorithm_coach.web.identity import UI_MANIFEST, inspect_ui, workspace_identity


def write_ui(directory: Path) -> dict:
    """Create a small complete public UI fixture.

    Inputs: A temporary asset directory.
    Outputs: Its valid resource manifest.
    Logic: Hash a synthetic HTML page and script with the runtime canonical format.
    Dependencies: pathlib, JSON, and hashlib. No real records are used.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text('<!-- Synthetic UI. --><script src="/app.js"></script>', encoding="utf-8")
    (directory / "app.js").write_text('/** Synthetic script. */', encoding="utf-8")
    files = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in ("app.js", "index.html")}
    canonical = json.dumps(files, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    record = {"_comment": "Describe synthetic public UI assets.", "format_version": 1, "api_version": "1",
              "build_id": hashlib.sha256(canonical.encode()).hexdigest(), "files": files}
    (directory / UI_MANIFEST).write_text(json.dumps(record), encoding="utf-8")
    return record


class WebIdentityTests(unittest.TestCase):
    """Keep readiness and store identity independent from saved learning state."""

    def test_copied_workspaces_have_distinct_store_ids(self) -> None:
        """Inputs: Two copies of one synthetic workspace. Outputs: different store IDs.

        Logic: Preserve workspace UUID while binding identity to each database path.
        Dependencies: Coach, temporary directories, and workspace_identity.
        """
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            coach = Coach(first / "coach.sqlite3")
            coach.initialize({"timezone": "UTC", "language": "Java"})
            original = coach.get_workspace_identity()
            coach.close()
            shutil.copytree(first, second)
            left, right = workspace_identity(first), workspace_identity(second)
            self.assertEqual(left["workspace_id"], original["workspace_id"])
            self.assertEqual(left["workspace_id"], right["workspace_id"])
            self.assertNotEqual(left["store_id"], right["store_id"])
            self.assertEqual(workspace_identity(first / ".." / "first"), left)

    def test_missing_store_is_not_initialized(self) -> None:
        """Inputs: A missing data directory. Outputs: refusal without new files.

        Logic: A status identity query cannot create another training authority.
        Dependencies: workspace_identity and a temporary directory.
        """
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "missing"
            with self.assertRaises(CoachError):
                workspace_identity(directory)
            self.assertFalse(directory.exists())

    def test_complete_assets_and_tampering_are_distinct(self) -> None:
        """Inputs: Valid assets, then a changed resource. Outputs: readiness then refusal.

        Logic: Verify file content rather than only the HTML entry point's existence.
        Dependencies: write_ui and inspect_ui.
        """
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = write_ui(directory)
            self.assertEqual(inspect_ui(directory), {"ui_ready": True, "ui_build_id": record["build_id"], "reason": None})
            (directory / "app.js").write_text("changed", encoding="utf-8")
            self.assertEqual(inspect_ui(directory)["reason"], "assets_invalid")

    def test_missing_incompatible_and_unsafe_manifests_are_rejected(self) -> None:
        """Inputs: Incomplete or unsafe inventories. Outputs: explicit non-ready results.

        Logic: Refuse missing resources, protocol mismatches, traversal, and links.
        Dependencies: write_ui, JSON, symlinks, and inspect_ui.
        """
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "ui"
            self.assertEqual(inspect_ui(directory)["reason"], "assets_missing")
            record = write_ui(directory)
            record["api_version"] = "other"
            (directory / UI_MANIFEST).write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(inspect_ui(directory)["reason"], "assets_incompatible")
            record = write_ui(directory)
            record["files"]["../outside"] = "0" * 64
            (directory / UI_MANIFEST).write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(inspect_ui(directory)["reason"], "assets_invalid")
            write_ui(directory)
            (directory / "app.js").unlink()
            (directory / "app.js").symlink_to(directory / "index.html")
            self.assertEqual(inspect_ui(directory)["reason"], "assets_invalid")

    def test_unlisted_linked_directory_is_not_a_public_asset(self) -> None:
        """Inputs: A valid UI with an unlisted link to unrelated synthetic files.
        Outputs: Refusal before the linked directory can enter a Web bundle.

        Logic: Check every entry, including directories absent from the manifest.
        Dependencies: Temporary symlinks, write_ui, and inspect_ui.
        """
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "ui"
            write_ui(directory)
            outside = Path(temporary) / "unrelated"
            outside.mkdir()
            (outside / "synthetic-private-note.txt").write_text("Synthetic fixture only.", encoding="utf-8")
            (directory / "unlisted").symlink_to(outside, target_is_directory=True)
            self.assertEqual(inspect_ui(directory)["reason"], "assets_invalid")


if __name__ == "__main__":
    unittest.main()
