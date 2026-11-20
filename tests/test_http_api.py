"""Verify the optional local HTTP boundary with synthetic SQLite data."""

from contextlib import ExitStack
from datetime import datetime
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.errors import CoachError
from algorithm_coach.service import Coach

WEB_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "httpx", "uvicorn"))
if WEB_AVAILABLE:
    from fastapi.testclient import TestClient
    from algorithm_coach.http_api import create_app


@unittest.skipUnless(WEB_AVAILABLE, "Install the optional web requirements to run HTTP tests.")
class HttpApiTests(unittest.TestCase):
    """Test local API reads, strict feedback writes, and browser request boundaries."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: initialized temporary core and HTTP client.

        Logic: create only synthetic state and an existing frozen training plan.
        Dependencies: tempfile, Coach, TestClient, and ExitStack.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "private"
        self.coach = Coach(self.directory / "coach.sqlite3")
        self.coach.initialize({"timezone": "Asia/Tokyo"})
        self.plan = self.coach.ensure_plan("2026-01-02")
        self.attempt_id = self.plan["items"][0]["attempt_id"]
        self.stack = ExitStack()
        self.client = self.stack.enter_context(TestClient(create_app(self.directory), base_url="http://127.0.0.1:8765"))
        self.store_id = self.client.get("/v1/context").json()["data"]["store_id"]

    def tearDown(self) -> None:
        """Inputs: the isolated fixture. Outputs: no open clients or state files.

        Logic: close HTTP lifespan and SQLite before deleting temporary data.
        Dependencies: ExitStack, Coach, and TemporaryDirectory.
        """
        self.stack.close()
        self.coach.close()
        self.temp.cleanup()

    def _body(self, submission: str = "http-save", revision: int = 0, changes: dict | None = None, kind: str = "progress") -> dict:
        """Inputs: operation identity, revision, changes, and kind. Outputs: JSON input.

        Logic: provide one deterministic feedback request with an explicit event time.
        Dependencies: no external state.
        """
        return {"submission_id": submission, "expected_revision": revision, "changes": changes if changes is not None else {"result": "A", "elapsed_minutes": 20}, "kind": kind, "occurred_at": "2026-01-02T12:00:00+09:00"}

    def _post(self, body: dict, client: object = None) -> object:
        """Inputs: feedback JSON and optional client. Outputs: an HTTP response.

        Logic: submit through the same-origin browser boundary.
        Dependencies: TestClient and the existing attempt fixture.
        """
        selected = self.client if client is None else client
        return selected.post(f"/v1/attempts/{self.attempt_id}/feedback", json=body, headers=self._headers())

    def _headers(self, origin: str = "http://127.0.0.1:8765") -> dict:
        """Inputs: an explicit local origin. Outputs: browser write headers.

        Logic: Bind each synthetic request to its known SQLite location.
        Dependencies: The context endpoint identity from setUp.
        """
        return {"Origin": origin, "X-Coach-Store-Id": self.store_id}

    def _assets(self) -> Path:
        """Inputs: none. Outputs: complete synthetic UI assets and their manifest.

        Logic: Hash one small file using the public manifest contract.
        Dependencies: pathlib, hashlib, and canonical JSON.
        """
        assets = Path(self.temp.name) / "managed-assets"
        assets.mkdir(exist_ok=True)
        page = assets / "index.html"
        page.write_text("<!-- Synthetic managed UI. --><h1>Feedback UI</h1>", encoding="utf-8")
        files = {"index.html": hashlib.sha256(page.read_bytes()).hexdigest()}
        build_id = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest = {"_comment": "Describe synthetic verified UI files.", "format_version": 1, "api_version": "1", "build_id": build_id, "files": files}
        (assets / "coach-ui-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return assets

    def test_context_uses_configured_date_and_workspace_identity(self) -> None:
        """Inputs: persisted configuration. Outputs: accurate, uncached context.

        Logic: report the configured timezone rather than the browser timezone.
        Dependencies: the context endpoint and the system clock.
        """
        response = self.client.get("/v1/context")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["timezone"], "Asia/Tokyo")
        self.assertEqual(data["training_date"], datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat())
        self.assertEqual(data["language"], "Java")
        self.assertEqual(data["api_version"], "1")
        self.assertTrue(data["workspace_id"])
        self.assertEqual(len(data["store_id"]), 64)
        self.assertEqual(data["store_id"], self.store_id)
        self.assertEqual(data["workspace_id"], self.client.get("/v1/context").json()["data"]["workspace_id"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_reading_a_missing_plan_never_creates_one(self) -> None:
        """Inputs: an absent training date. Outputs: 404 and unchanged stored work.

        Logic: keep browser reads separate from plan publication.
        Dependencies: HTTP GET and Coach plan readers.
        """
        before = self.coach.learning_state()
        response = self.client.get("/v1/plans/2026-01-03")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")
        with self.assertRaises(CoachError):
            self.coach.get_plan("2026-01-03")
        self.assertEqual(self.coach.learning_state(), before)
        saved = self.client.get("/v1/plans/2026-01-02").json()["data"]
        self.assertEqual(saved["id"], self.plan["id"])

    def test_app_creation_and_startup_do_not_initialize_missing_storage(self) -> None:
        """Inputs: a missing state directory. Outputs: startup refusal and no files.

        Logic: require an explicit core initialization before the web app starts.
        Dependencies: create_app, TestClient lifespan, and Coach errors.
        """
        missing = Path(self.temp.name) / "missing"
        app = create_app(missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(CoachError):
            with TestClient(app, base_url="http://127.0.0.1:8765"):
                pass
        self.assertFalse(missing.exists())

    def test_save_retry_and_receipt_return_the_exact_immutable_revision(self) -> None:
        """Inputs: feedback, its retry, and a later correction. Outputs: stable receipts.

        Logic: read the submitted revision instead of substituting the latest feedback.
        Dependencies: HTTP endpoints and the shared SQLite core.
        """
        body = self._body()
        first = self._post(body)
        self.assertEqual(first.status_code, 200)
        initial = first.json()["data"]
        self.assertEqual(initial["receipt"]["status"], "applied")
        self.assertEqual(initial["feedback_revision"]["snapshot"]["result"], "A")
        self.assertEqual(self._post(body).json()["data"], initial)
        changed = self._post(self._body("http-correct", 1, {"result": "C"}, "correction"))
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["data"]["feedback_revision"]["snapshot"]["result"], "C")
        self.assertEqual(self.client.get("/v1/submissions/http-save").json()["data"], initial)
        self.assertEqual(self._post(body).json()["data"], initial)
        history = self.coach.history(self.attempt_id)
        self.assertEqual(len(history["revisions"]), 2)
        self.assertEqual(history["attempt"]["feedback"]["result"], "C")

    def test_partial_feedback_preserves_false_null_and_omitted_fields(self) -> None:
        """Inputs: explicit false, a note, and a null correction. Outputs: distinct values.

        Logic: use exclude_unset without discarding explicit null or false.
        Dependencies: strict request models and core patch semantics.
        """
        self.assertEqual(self._post(self._body(changes={"result": "D", "boundary_tests": False, "blocked_on": "Synthetic note", "elapsed_minutes": 12})).status_code, 200)
        response = self._post(self._body("http-clear", 1, {"boundary_tests": None}, "correction"))
        saved = response.json()["data"]["feedback_revision"]
        self.assertEqual(saved["changes"], {"boundary_tests": None})
        self.assertIsNone(saved["snapshot"]["boundary_tests"])
        self.assertEqual(saved["snapshot"]["blocked_on"], "Synthetic note")
        self.assertEqual(saved["snapshot"]["elapsed_minutes"], 12)
        self.assertIs(self.coach.history(self.attempt_id)["revisions"][0]["snapshot"]["boundary_tests"], False)

    def test_conflicting_or_unknown_targets_return_safe_errors(self) -> None:
        """Inputs: stale and reused operations plus an unknown attempt. Outputs: errors.

        Logic: keep normal domain conflicts distinct from invalid input and missing data.
        Dependencies: core revision and deduplication checks.
        """
        self.assertEqual(self._post(self._body()).status_code, 200)
        self.assertEqual(self._post(self._body("stale", 0, {"result": "B"})).status_code, 409)
        self.assertEqual(self._post(self._body(changes={"result": "B"})).status_code, 409)
        missing = self.client.post("/v1/attempts/not-present/feedback", json=self._body("unknown"), headers=self._headers())
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(len(self.coach.history(self.attempt_id)["revisions"]), 1)

    def test_strict_models_reject_coercion_unknown_fields_and_invalid_numbers(self) -> None:
        """Inputs: malformed field types and unsupported claims. Outputs: atomic 422s.

        Logic: prevent booleans, strings, or verification flags from becoming valid facts.
        Dependencies: Pydantic strict models and core validation.
        """
        invalid_changes = ({"result": "G"}, {"boundary_tests": "false"}, {"proficiency": True}, {"elapsed_minutes": True}, {"elapsed_minutes": "20"}, {"verified": True}, {"defer_until": "tomorrow"})
        for index, changes in enumerate(invalid_changes):
            with self.subTest(changes=changes):
                response = self._post(self._body(f"invalid-{index}", changes=changes))
                self.assertEqual(response.status_code, 422)
                self.assertFalse(response.json()["ok"])
        self.assertEqual(self.coach.history(self.attempt_id)["attempt"]["revision"], 0)
        response = self._post({**self._body("bool-revision"), "expected_revision": True})
        self.assertEqual(response.status_code, 422)

    def test_json_duplicates_and_nonfinite_constants_are_rejected(self) -> None:
        """Inputs: ambiguous or non-standard JSON. Outputs: 422 without saved feedback.

        Logic: reject duplicate keys and NaN before request model construction.
        Dependencies: the bounded middleware JSON parser.
        """
        bodies = ('{"submission_id":"x","submission_id":"y","expected_revision":0,"changes":{"result":"A"}}', '{"submission_id":"x","expected_revision":0,"changes":{"elapsed_minutes":NaN}}')
        for body in bodies:
            response = self.client.post(f"/v1/attempts/{self.attempt_id}/feedback", content=body, headers={"Origin": "http://127.0.0.1:8765", "Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.coach.history(self.attempt_id)["revisions"], [])

    def test_browser_writes_require_same_origin_and_json(self) -> None:
        """Inputs: missing or foreign Origin and a form-like request. Outputs: refusal.

        Logic: reject cross-site browser writes without requiring a login system.
        Dependencies: the local request boundary.
        """
        path = f"/v1/attempts/{self.attempt_id}/feedback"
        self.assertEqual(self.client.post(path, json=self._body()).status_code, 403)
        for origin in ("https://example.com", "null", "http://127.0.0.1:5173"):
            self.assertEqual(self.client.post(path, json=self._body(), headers={"Origin": origin}).status_code, 403)
        self.assertEqual(self.client.post(path, content="result=A", headers={"Origin": "http://127.0.0.1:8765", "Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.coach.history(self.attempt_id)["revisions"], [])

    def test_non_loopback_hosts_are_rejected_before_routing(self) -> None:
        """Inputs: hostile or malformed Host values. Outputs: local-boundary errors.

        Logic: prevent DNS rebinding and permissive host matching.
        Dependencies: the strict loopback authority validator.
        """
        for host in ("example.com", "127.0.0.1.evil.example", "localhost.evil.example", "0.0.0.0:8765", "localhost:65536", "localhost:"):
            with self.subTest(host=host):
                response = self.client.get("/v1/context", headers={"Host": host})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_host")

    def test_development_origin_is_explicit_and_still_local(self) -> None:
        """Inputs: one configured local dev Origin. Outputs: only that Origin allowed.

        Logic: support the Vite proxy without rewriting Origin or enabling wildcard CORS.
        Dependencies: create_app and local Origin validation.
        """
        with TestClient(create_app(self.directory, allowed_origin="http://127.0.0.1:5173"), base_url="http://127.0.0.1:8765") as client:
            response = client.post(f"/v1/attempts/{self.attempt_id}/feedback", json=self._body(), headers=self._headers("http://127.0.0.1:5173"))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("access-control-allow-origin", response.headers)
            self.assertEqual(client.post(f"/v1/attempts/{self.attempt_id}/feedback", json=self._body("wrong-dev"), headers={"Origin": "http://localhost:5173"}).status_code, 403)
        with self.assertRaises(CoachError):
            create_app(self.directory, allowed_origin="http://example.com")

    def test_sqlite_contention_is_retryable_without_acknowledging_a_write(self) -> None:
        """Inputs: an external SQLite writer lock. Outputs: safe 503 then successful retry.

        Logic: acknowledge feedback only after the core transaction commits.
        Dependencies: SQLite writer locks and the same stable submission ID.
        """
        connection = sqlite3.connect(self.directory / "coach.sqlite3", isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            response = self._post(self._body("busy-retry"))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "database_busy")
            self.assertNotIn(str(self.directory), response.text)
        finally:
            connection.rollback()
            connection.close()
        self.assertEqual(self._post(self._body("busy-retry")).status_code, 200)
        self.assertEqual(len(self.coach.history(self.attempt_id)["revisions"]), 1)

    def test_scores_are_core_reads_without_state_changes(self) -> None:
        """Inputs: no evidence and then one reported completion. Outputs: topic scores.

        Logic: reuse scoring semantics while leaving the learning projection unchanged.
        Dependencies: the core scoring method and HTTP read endpoint.
        """
        version = self.coach.learning_state()["state_version"]
        response = self.client.get("/v1/scores")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["metric"], "independent_completion_rate")
        self.assertEqual(response.json()["data"]["basis"], "self_reported")
        self.assertEqual(self.coach.learning_state()["state_version"], version)
        self._post(self._body())
        scored = self.client.get("/v1/scores?language=Java").json()["data"]
        self.assertTrue(any(topic["score"] == 100 for topic in scored["topics"]))
        progress = self.client.get("/v1/progress?language=Java")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["data"]["basis"], "self_reported")
        self.assertEqual(len(progress.json()["data"]["problems"]), 1)

    def test_feedback_requires_one_matching_store_identity(self) -> None:
        """Inputs: missing, foreign, duplicate, and correct store headers.
        Outputs: Atomic identity conflicts followed by one accepted write.

        Logic: Reject an old page before it can save into another SQLite location.
        Dependencies: The same-worker identity precondition and feedback history.
        """
        path = f"/v1/attempts/{self.attempt_id}/feedback"
        invalid = (
            {"Origin": "http://127.0.0.1:8765"},
            {"Origin": "http://127.0.0.1:8765", "X-Coach-Store-Id": "another-store"},
            [("Origin", "http://127.0.0.1:8765"), ("X-Coach-Store-Id", self.store_id), ("X-Coach-Store-Id", self.store_id)],
        )
        for headers in invalid:
            response = self.client.post(path, json=self._body(), headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "workspace_mismatch")
            self.assertNotIn(str(self.directory), response.text)
        self.assertEqual(self.coach.history(self.attempt_id)["revisions"], [])
        self.assertEqual(self._post(self._body()).status_code, 200)

    def test_copied_database_cannot_acknowledge_a_different_store(self) -> None:
        """Inputs: a backup retaining the original workspace and attempt IDs.
        Outputs: A distinct store identity and rejected stale reads and writes.

        Logic: Bind receipt recovery as well as feedback to the actual database location.
        Dependencies: Coach backup, fresh contexts, and optional read preconditions.
        """
        self.assertEqual(self._post(self._body()).status_code, 200)
        copied = Path(self.temp.name) / "copied"
        copied.mkdir()
        self.coach.backup(copied / "coach.sqlite3")
        before = self.coach.learning_state()
        with TestClient(create_app(copied), base_url="http://127.0.0.1:8765") as client:
            source = self.client.get("/v1/context").json()["data"]
            destination = client.get("/v1/context").json()["data"]
            self.assertEqual(source["workspace_id"], destination["workspace_id"])
            self.assertNotEqual(source["store_id"], destination["store_id"])
            paths = ("/v1/context", "/v1/runtime", "/v1/plans/2026-01-02", "/v1/scores", "/v1/progress", "/v1/submissions/http-save")
            for path in paths:
                with self.subTest(path=path):
                    response = client.get(path, headers={"X-Coach-Store-Id": self.store_id})
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()["error"]["code"], "workspace_mismatch")
            response = self._post(self._body("copied-correction", 1, {"result": "B"}, "correction"), client)
            self.assertEqual(response.status_code, 409)
            headers = {"X-Coach-Store-Id": destination["store_id"]}
            self.assertEqual(client.get("/v1/submissions/http-save", headers=headers).status_code, 200)
        clone = Coach(copied / "coach.sqlite3")
        try:
            self.assertEqual(len(clone.history(self.attempt_id)["revisions"]), 1)
        finally:
            clone.close()
        self.assertEqual(self.coach.learning_state(), before)

    def test_runtime_reports_live_identity_and_verified_assets_without_controls(self) -> None:
        """Inputs: managed metadata, complete UI assets, and later corrupted assets.
        Outputs: Fresh safe identity and truthful independent readiness fields.

        Logic: Do not trust supplied workspace fields or expose private control values.
        Dependencies: Runtime endpoint, public workspace identity, and UI manifests.
        """
        assets = self._assets()
        before = self.coach.learning_state()
        supplied = {"instance_id": "synthetic-instance", "workspace_id": "false-workspace", "store_id": "false-store", "control_token": "PRIVATE_SYNTHETIC_TOKEN"}
        with TestClient(create_app(self.directory, assets, runtime_context=supplied), base_url="http://127.0.0.1:8765") as client:
            response = client.get("/v1/runtime")
            data = response.json()["data"]
            self.assertEqual(data["service"], "algorithm-coach-web")
            self.assertEqual(data["runtime_protocol"], 1)
            self.assertEqual(data["store_id"], self.store_id)
            self.assertEqual(data["workspace_id"], self.coach.get_workspace_identity()["workspace_id"])
            self.assertEqual(data["instance_id"], "synthetic-instance")
            self.assertTrue(data["managed"])
            self.assertTrue(data["database_ready"])
            self.assertTrue(data["ui_ready"])
            self.assertTrue(data["ui_build_id"])
            self.assertNotIn("PRIVATE_SYNTHETIC_TOKEN", response.text)
            self.assertNotIn(str(self.directory), response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            (assets / "index.html").write_text("<!-- Synthetic corruption. -->", encoding="utf-8")
            stale = client.get("/v1/runtime").json()["data"]
            self.assertFalse(stale["ui_ready"])
            self.assertTrue(stale["database_ready"])
        unmanaged = self.client.get("/v1/runtime").json()["data"]
        self.assertFalse(unmanaged["managed"])
        self.assertIsNone(unmanaged["instance_id"])
        self.assertFalse(unmanaged["ui_ready"])
        self.assertEqual(self.coach.learning_state(), before)
        with self.assertRaises(CoachError):
            self.coach.get_plan("2026-01-03")

    def test_private_stop_requires_exact_managed_instance_and_control_token(self) -> None:
        """Inputs: browser and private shutdown requests for a synthetic instance.
        Outputs: Rejections without side effects, then one acknowledged callback.

        Logic: Keep stop control outside React and defer it until after the response.
        Dependencies: Strict stop body, constant-time token check, and background tasks.
        """
        stopped = []

        def shutdown() -> None:
            """Inputs: a verified internal stop request. Outputs: one test marker.

            Logic: Observe the callback without stopping the test process.
            Dependencies: The enclosing synthetic marker list.
            """
            stopped.append(True)

        settings = {"runtime_context": {"instance_id": "synthetic-instance"}, "control_token": "PRIVATE_SYNTHETIC_TOKEN", "request_shutdown": shutdown}
        with TestClient(create_app(self.directory, **settings), base_url="http://127.0.0.1:8765") as client:
            path = "/internal/runtime/stop"
            body = {"instance_id": "synthetic-instance"}
            headers = {"Origin": "http://127.0.0.1:8765", "X-Coach-Control-Token": "PRIVATE_SYNTHETIC_TOKEN"}
            self.assertEqual(client.post(path, json=body, headers={"Origin": headers["Origin"]}).status_code, 403)
            self.assertEqual(client.post(path, json=body, headers={**headers, "X-Coach-Control-Token": "wrong"}).status_code, 403)
            self.assertEqual(client.post(path, json={"instance_id": "another-instance"}, headers=headers).status_code, 403)
            self.assertEqual(client.post(path, json={**body, "extra": True}, headers=headers).status_code, 422)
            self.assertEqual(client.post(path, json=body, headers={"X-Coach-Control-Token": headers["X-Coach-Control-Token"]}).status_code, 403)
            self.assertEqual(client.post(path, json=body, headers={**headers, "Origin": "https://example.com"}).status_code, 403)
            self.assertEqual(client.post(path, json=body, headers=[*headers.items(), ("X-Coach-Control-Token", headers["X-Coach-Control-Token"])]).status_code, 403)
            self.assertEqual(stopped, [])
            response = client.post(path, json=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"], {"stopping": True, "instance_id": "synthetic-instance"})
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertNotIn("PRIVATE_SYNTHETIC_TOKEN", response.text)
            self.assertEqual(stopped, [True])
        unmanaged = self.client.post("/internal/runtime/stop", json={"instance_id": "synthetic-instance"}, headers={"Origin": "http://127.0.0.1:8765", "X-Coach-Control-Token": "PRIVATE_SYNTHETIC_TOKEN"})
        self.assertEqual(unmanaged.status_code, 403)

    def test_static_assets_do_not_swallow_unknown_api_or_escape_the_directory(self) -> None:
        """Inputs: built synthetic assets and unknown paths. Outputs: safe static routing.

        Logic: serve index only at the UI route and never expose adjacent files.
        Dependencies: StaticFiles with symlink following disabled.
        """
        assets = Path(self.temp.name) / "assets"
        assets.mkdir()
        (assets / "index.html").write_text("<!-- Synthetic UI fixture. --><h1>Feedback UI</h1>")
        (Path(self.temp.name) / "private-note.txt").write_text("SYNTHETIC_PRIVATE_VALUE")
        with TestClient(create_app(self.directory, assets), base_url="http://127.0.0.1:8765") as client:
            self.assertIn("Feedback UI", client.get("/").text)
            unknown = client.get("/v1/unknown-endpoint")
            self.assertEqual(unknown.status_code, 404)
            self.assertFalse(unknown.json()["ok"])
            escaped = client.get("/%2e%2e/private-note.txt")
            self.assertEqual(escaped.status_code, 404)
            self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", escaped.text)


if __name__ == "__main__":
    unittest.main()
