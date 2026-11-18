"""Verify local code evidence writes and read-only review status with synthetic data."""

from contextlib import ExitStack
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algorithm_coach.service import Coach

WEB_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "httpx", "uvicorn"))
if WEB_AVAILABLE:
    from fastapi.testclient import TestClient
    from algorithm_coach.http_api import create_app


@unittest.skipUnless(WEB_AVAILABLE, "Install the optional web requirements to run HTTP tests.")
class HttpReviewTests(unittest.TestCase):
    """Keep browser evidence separate from host-authored complexity assessments."""

    def setUp(self) -> None:
        """Inputs: none. Outputs: an isolated practice and local HTTP client.

        Logic: initialize synthetic data without reading any private workspace.
        Dependencies: tempfile, Coach, TestClient, and ExitStack.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "private"
        self.coach = Coach(self.directory / "coach.sqlite3")
        self.coach.initialize({"timezone": "Asia/Tokyo"})
        self.attempt = self.coach.ensure_plan("2026-01-02")["items"][0]["attempt_id"]
        self.stack = ExitStack()
        self.client = self.stack.enter_context(TestClient(create_app(self.directory), base_url="http://127.0.0.1:8765"))
        self.store = self.client.get("/v1/context").json()["data"]["store_id"]
        self.headers = {"Origin": "http://127.0.0.1:8765", "X-Coach-Store-Id": self.store}

    def tearDown(self) -> None:
        """Inputs: the isolated fixture. Outputs: no open clients or private files.

        Logic: close HTTP and SQLite before removing the temporary directory.
        Dependencies: ExitStack, Coach, and TemporaryDirectory.
        """
        self.stack.close()
        self.coach.close()
        self.temp.cleanup()

    def _body(self, submission: str = "synthetic-code", revision: int = 0) -> dict:
        """Inputs: an operation identity and feedback version. Outputs: code JSON.

        Logic: use small synthetic Java code and an explicit input-size definition.
        Dependencies: no private data or model service.
        """
        return {"submission_id": submission, "expected_revision": revision,
                "document": {"code": "int identity(int n) { return n; }", "language": "Java", "input_definition": "n is one integer"}}

    def _post(self, body: dict) -> object:
        """Inputs: one evidence request. Outputs: its local HTTP response.

        Logic: bind the operation to the known store and same local origin.
        Dependencies: TestClient and the existing practice attempt.
        """
        return self.client.post(f"/v1/attempts/{self.attempt}/solution", json=body, headers=self.headers)

    def _status(self) -> dict:
        """Inputs: none. Outputs: the saved status for this synthetic attempt.

        Logic: inspect the authority without submitting code or invoking a model.
        Dependencies: the store-bound read endpoint.
        """
        response = self.client.get(f"/v1/attempts/{self.attempt}/complexity", headers={"X-Coach-Store-Id": self.store})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertFalse(response.json()["data"]["model_api"])
        return response.json()["data"]["items"][0]

    def test_code_save_is_retryable_without_changing_feedback(self) -> None:
        """Inputs: one code submission sent twice. Outputs: one evidence receipt.

        Logic: preserve exact code identity and keep practice feedback unchanged.
        Dependencies: solution endpoint, immutable receipts, and status reads.
        """
        self.assertEqual(self._status()["status"], "awaiting_code")
        before = self.coach.history(self.attempt)
        saved = self._post(self._body())
        self.assertEqual(saved.status_code, 200)
        receipt = saved.json()["data"]["receipt"]
        self.assertEqual(receipt["operation"], "record_solution")
        self.assertEqual(receipt["feedback_revision"], 0)
        self.assertEqual(self._post(self._body()).json(), saved.json())
        lookup = self.client.get("/v1/submissions/synthetic-code", headers={"X-Coach-Store-Id": self.store})
        self.assertEqual(lookup.json(), saved.json())
        after = self.coach.history(self.attempt)
        self.assertEqual(after["revisions"], before["revisions"])
        self.assertEqual(after["attempt"]["feedback"], before["attempt"]["feedback"])
        self.assertEqual(after["attempt"]["revision"], before["attempt"]["revision"])
        self.assertNotEqual(after["attempt"]["assessment_version"], before["attempt"]["assessment_version"])
        status = self._status()
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["evidence"]["id"], receipt["evidence_id"])
        self.assertEqual(status["evidence"]["body"], self._body()["document"])
        changed = self._body()
        changed["document"]["code"] = "int identity(int n) { return 0; }"
        self.assertEqual(self._post(changed).status_code, 409)

    def test_code_requires_store_origin_revision_and_strict_document(self) -> None:
        """Inputs: missing guards, stale feedback, and an injected assessment.
        Outputs: rejected writes without any evidence saved.

        Logic: enforce the same browser boundary and concurrency as feedback writes.
        Dependencies: local middleware, Pydantic, and Coach revision checks.
        """
        path = f"/v1/attempts/{self.attempt}/solution"
        absent_store = self.client.post(path, json=self._body(), headers={"Origin": self.headers["Origin"]})
        self.assertEqual(absent_store.status_code, 409)
        absent_origin = self.client.post(path, json=self._body(), headers={"X-Coach-Store-Id": self.store})
        self.assertEqual(absent_origin.status_code, 403)
        self.assertEqual(self._post(self._body(revision=1)).status_code, 409)
        injected = self._body()
        injected["document"]["status"] = "supported"
        self.assertEqual(self._post(injected).status_code, 422)
        self.assertEqual(self._status()["status"], "awaiting_code")
        unknown = self.client.get(f"/v1/attempts/{self.attempt}/complexity", headers={"X-Coach-Store-Id": "other-store"})
        self.assertEqual(unknown.status_code, 409)

    def test_host_review_is_visible_and_feedback_changes_make_it_stale(self) -> None:
        """Inputs: a host review followed by a new feedback revision.
        Outputs: a scoped conclusion and then an explicit stale state.

        Logic: never silently attach old analysis to another feedback version.
        Dependencies: host-only core review writes and browser status reads.
        """
        receipt = self._post(self._body()).json()["data"]["receipt"]
        self.coach.submit_complexity_review("synthetic-review", {
            "evidence_id": receipt["evidence_id"], "status": "supported", "input_definition": "n is one integer",
            "time_complexity": "O(1)", "space_complexity": "O(1)",
            "reasoning": "The function returns one scalar without a loop or allocation.",
            "sources": ["Synthetic submitted code"], "reviewer": "synthetic-host",
        })
        status = self._status()
        self.assertEqual(status["status"], "supported")
        self.assertEqual(status["review"]["body"]["time_complexity"], "O(1)")
        self.coach.submit_feedback(self.attempt, "synthetic-progress", 0, {"result": "D"})
        stale = self._status()
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["evidence"]["id"], receipt["evidence_id"])
        self.assertEqual(self._post(self._body("old-revision")).status_code, 409)

    def test_browser_has_no_assessment_write_endpoint(self) -> None:
        """Inputs: a browser attempt to post a review verdict. Outputs: a 404.

        Logic: accept user evidence while reserving analytical verdicts for the host.
        Dependencies: explicit API routing and the unknown-endpoint boundary.
        """
        response = self.client.post(f"/v1/attempts/{self.attempt}/complexity", json={"status": "supported"}, headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._status()["status"], "awaiting_code")


if __name__ == "__main__":
    unittest.main()
