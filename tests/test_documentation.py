"""Test offline documentation checks and public examples with synthetic data."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_docs import check


class DocumentationTests(unittest.TestCase):
    """Check documentation failures and executable public examples."""

    def test_valid_links_and_literal_examples_pass_without_network(self) -> None:
        """Accept local anchors and ignore literal links in code examples.

        Inputs: Synthetic documents with duplicate headings and an encoded path.
        Outputs: No documentation failures.
        Logic: Resolve local links and skip external URLs and fenced examples.
        Dependencies: check, pathlib, and a temporary directory.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "guide page.md").write_text("# Setup\n# Setup\n# Run `init`\n", encoding="utf-8")
            (root / "README.md").write_text(
                "# Guide\n[local](guide%20page.md#setup-1)\n[self](#guide)\n"
                "[inline heading](guide%20page.md#run-init)\n"
                "[external](https://example.invalid/guide)\n`[literal](missing.md)`\n"
                "````sh\n[example](missing.md)\n```\n````\n"
                "~~~text\n[example](missing.md)\n~~~\n", encoding="utf-8")
            self.assertEqual(check(root), [])

    def test_missing_targets_and_anchors_report_the_source_line(self) -> None:
        """Make broken documentation links fail with useful diagnostics.

        Inputs: A document with a missing file and an unknown local heading.
        Outputs: Two failures with the document path and source line.
        Logic: Check target existence before heading lookup.
        Dependencies: check and synthetic temporary Markdown.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text(
                "# Guide\n[missing](absent.md)\n[anchor](#unknown)\n", encoding="utf-8")
            failures = check(root)
            self.assertEqual(len(failures), 2)
            self.assertIn("README.md:2: missing local link target", failures[0])
            self.assertIn("README.md:3: missing heading anchor", failures[1])

    def test_unclosed_code_fence_fails(self) -> None:
        """Reject a code block closed with a different fence character.

        Inputs: A synthetic Markdown file with mismatched code fences.
        Outputs: A failure pointing to the opening fence.
        Logic: Keep the opening marker active until a matching close appears.
        Dependencies: check and temporary files.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("# Guide\n```sh\n~~~\n", encoding="utf-8")
            self.assertEqual(check(root), ["README.md:2: unclosed code fence"])

    def test_local_links_cannot_escape_the_checkout(self) -> None:
        """Keep documentation portable without inspecting outside files.

        Inputs: A local link to a real file outside the synthetic checkout.
        Outputs: A repository boundary failure.
        Logic: Resolve parent components before accepting a target.
        Dependencies: check and temporary files.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            (root.parent / "outside.md").write_text("# Outside\n", encoding="utf-8")
            (root / "README.md").write_text("[outside](../outside.md)\n", encoding="utf-8")
            self.assertIn("local link must stay inside the repository", check(root)[0])

    def _run_cli(self, data: Path, arguments: list[str]) -> dict:
        """Run a documented command with an isolated data directory.

        Inputs: A temporary data path and command arguments.
        Outputs: The successful CLI data object.
        Logic: Use the public Skill entry point without third-party site packages.
        Dependencies: subprocess, JSON, and the standard-library CLI.
        """
        process = subprocess.run(
            [sys.executable, "-S", str(ROOT / "skills/algorithm-coach/scripts/coach.py"), *arguments],
            cwd=ROOT, env=dict(os.environ, ALGORITHM_COACH_DATA_DIR=str(data)),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result["ok"], result)
        return result["data"]

    def test_readme_quick_start_runs_as_documented(self) -> None:
        """Keep the actual README quick start compatible with the public CLI.

        Inputs: The first shell block under Quick start and a synthetic data path.
        Outputs: An initialized workspace and a five-item Java plan.
        Logic: Parse the documented commands as arguments. Replace only the data path.
        Dependencies: The README, shlex, subprocess, and the CLI. No shell is run.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Quick start\n", 1)[1]
        block = re.search(r"```sh\n(.*?)\n```", section, re.DOTALL)
        self.assertIsNotNone(block)
        with tempfile.TemporaryDirectory() as temp:
            results = []
            for line in block[1].splitlines():
                arguments = shlex.split(line)
                if not arguments:
                    continue
                if arguments[0] == "export":
                    self.assertEqual(arguments[1].split("=", 1)[0], "ALGORITHM_COACH_DATA_DIR")
                    continue
                self.assertEqual(arguments[:2], ["python3.12", "skills/algorithm-coach/scripts/coach.py"])
                results.append(self._run_cli(Path(temp) / "private", arguments[2:]))
            self.assertTrue(results[0]["initialized"])
            self.assertEqual(len(results[1]["items"]), 5)
            self.assertEqual(results[0]["config"]["config"]["language"], "Java")
            self.assertEqual(results[0]["config"]["config"]["timezone"], "UTC")

    def test_public_toml_examples_work_through_the_cli(self) -> None:
        """Verify the checked-in metadata and policy examples remain usable.

        Inputs: Both public TOML examples and a temporary workspace.
        Outputs: A previewed import and an applied easy-array policy.
        Logic: Guard the metadata import, then approve a policy and plan its start date.
        Dependencies: Public example files, the CLI, and synthetic temporary storage.
        """
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "private"
            self._run_cli(data, ["init", "--timezone", "UTC"])
            catalog_preview = self._run_cli(data, [
                "catalog", "preview", "--file", "examples/catalog-extra.toml",
            ])
            self.assertTrue(catalog_preview["import_allowed"])
            imported = self._run_cli(data, [
                "catalog", "import", "--file", "examples/catalog-extra.toml",
                "--submission", "example-catalog-import",
                "--expected-hash", catalog_preview["payload_hash"],
            ])
            self.assertEqual(imported["added_count"], 1)
            self.assertEqual(imported["payload_hash"], catalog_preview["payload_hash"])
            proposal = self._run_cli(data, [
                "policy", "propose", "--file", "examples/easy-arrays-policy.toml",
                "--expected-revision", "0", "--submission", "example-policy-proposal",
            ])
            preview = self._run_cli(data, ["policy", "preview", "--proposal", proposal["proposal_id"]])
            self.assertFalse(preview["stale"])
            self.assertTrue(preview["activation_allowed"])
            self.assertGreater(preview["eligible_count"], 0)
            receipt = self._run_cli(data, [
                "policy", "activate", "--proposal", proposal["proposal_id"],
                "--accept-hash", proposal["content_hash"], "--expected-revision", "0",
                "--submission", "example-policy-activation",
            ])
            self.assertEqual(receipt["status"], "applied")
            plan = self._run_cli(data, ["plan", "--date", proposal["body"]["effective_from"]])
            self.assertGreater(len(plan["items"]), 0)
            self.assertLessEqual(len(plan["items"]), 4)
            self.assertTrue(all(item["problem"]["difficulty"] == "easy" for item in plan["items"]))
            self.assertTrue(all("array" in item["problem"]["tags"] for item in plan["items"]))


if __name__ == "__main__":
    unittest.main()
