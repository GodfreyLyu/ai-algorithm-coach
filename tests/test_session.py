"""Verify session orchestration, fallbacks, and optional standalone Web packaging."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from algorithm_coach.cli import main
from algorithm_coach.service import Coach
from test_web_identity import write_ui


class SessionTests(unittest.TestCase):
    """Keep session runtime failures separate from durable planning success."""

    def setUp(self) -> None:
        """Inputs: None. Outputs: A fresh initialized synthetic store.

        Logic: Use temporary records outside the checkout for each test.
        Dependencies: Coach and tempfile.
        """
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "private"
        coach = Coach(self.data / "coach.sqlite3")
        coach.initialize({"timezone": "UTC", "language": "Java"})
        coach.close()

    def run_cli(self, arguments: list[str]) -> dict:
        """Inputs: Public CLI arguments. Outputs: A successful structured response.

        Logic: Capture the single JSON result without running a shell.
        Dependencies: main and redirect_stdout.
        """
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--data-dir", str(self.data), *arguments])
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())["data"]

    def test_session_returns_date_bound_link_and_preserves_plan(self) -> None:
        """Inputs: A ready runtime. Outputs: A stable plan and bound feedback URL.

        Logic: Compose the published training date with runtime store identity.
        Dependencies: The session CLI and a mocked process boundary.
        """
        runtime = {"status": "ready", "action": "started", "url": "http://127.0.0.1:8765/", "store_id": "a" * 64}
        with patch("algorithm_coach.web_runtime.ensure_web", return_value=runtime) as ensure:
            first = self.run_cli(["start-session", "--date", "2026-01-01"])
            second = self.run_cli(["start-session", "--date", "2026-01-01"])
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(first["plan"]["id"], second["plan"]["id"])
        self.assertIn("date=2026-01-01&store=" + "a" * 64, first["web"]["url"])
        self.assertEqual(self.run_cli(["show", "--date", "2026-01-01"])["id"], first["plan"]["id"])

    def test_web_failure_keeps_plan_and_core_commands_do_not_start_web(self) -> None:
        """Inputs: Unavailable Web dependencies. Outputs: A usable saved training plan.

        Logic: Keep fallback explicit while ordinary core calls have no runtime effects.
        Dependencies: The CLI and a mocked process boundary.
        """
        with patch("algorithm_coach.web_runtime.ensure_web", return_value={"status": "unavailable", "reason": "dependencies_missing", "url": None}) as ensure:
            self.run_cli(["plan", "--date", "2026-01-01"])
            self.assertFalse(ensure.called)
            session = self.run_cli(["start-session", "--date", "2026-01-01"])
            self.assertEqual(session["web"]["status"], "unavailable")
            self.assertEqual(len(session["plan"]["items"]), 5)
            self.run_cli(["start-session", "--date", "2026-01-02", "--no-web"])
            self.assertEqual(ensure.call_count, 1)

    def test_web_bundle_copies_only_verified_public_assets(self) -> None:
        """Inputs: Verified synthetic UI and a new bundle destination.
        Outputs: A standalone Web bundle with a working dependency-free core.

        Logic: Build outside the checkout, check included files, and run without site packages.
        Dependencies: The bundle builder, write_ui, and subprocess.
        """
        base = Path(self.temporary.name)
        assets = base / "ui"
        write_ui(assets)
        output = base / "bundle"
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / "build_skill.py"),
                                 "--output", str(output), "--with-web", "--web-assets", str(assets)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((output / "assets" / "web" / "coach-ui-manifest.json").is_file())
        self.assertTrue((output / "requirements-web.txt").is_file())
        self.assertFalse((output / "node_modules").exists())
        result = subprocess.run([sys.executable, "-S", str(output / "scripts" / "coach.py"),
                                 "--data-dir", str(self.data), "start-session", "--no-web", "--date", "2026-01-01"],
                                cwd=base, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["web"]["status"], "disabled")
        (assets / "app.js").write_text("modified", encoding="utf-8")
        rejected = base / "rejected"
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / "build_skill.py"),
                                 "--output", str(rejected), "--with-web", "--web-assets", str(assets)],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(rejected.exists())

    def test_web_bundle_rejects_unlisted_directory_links(self) -> None:
        """Inputs: An asset directory linked to unrelated synthetic content.
        Outputs: A rejected bundle and no copied destination.

        Logic: Refuse unlisted directory links before copying any external content.
        Dependencies: The public bundle builder, write_ui, and subprocess.
        """
        base = Path(self.temporary.name)
        assets = base / "linked-ui"
        write_ui(assets)
        outside = base / "unrelated"
        outside.mkdir()
        (outside / "synthetic-private-note.txt").write_text("Synthetic fixture only.", encoding="utf-8")
        (assets / "unlisted").symlink_to(outside, target_is_directory=True)
        destination = base / "rejected-link-bundle"
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / "build_skill.py"),
                                 "--output", str(destination), "--with-web", "--web-assets", str(assets)],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
