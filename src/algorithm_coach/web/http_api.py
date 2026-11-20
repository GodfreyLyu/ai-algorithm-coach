"""Serve the local feedback UI through a small, loopback-only HTTP adapter."""

import argparse
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Annotated, Callable, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..errors import CoachError
from ..service import Coach
from .identity import API_VERSION, RUNTIME_PROTOCOL, SERVICE_NAME, inspect_ui, store_id


MAX_REQUEST_BYTES = 1_048_576


class FeedbackChanges(BaseModel):
    """Describe strict optional fields while preserving omitted and null values."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    result: Literal["A", "B", "C", "D", "E", "F"] | None = None
    elapsed_minutes: Annotated[int | float, Field(ge=0)] | None = None
    blocked_on: Annotated[str, Field(max_length=4000)] | None = None
    explanation: Literal["not_tried", "partial", "clear", "uncertain"] | None = None
    boundary_tests: bool | None = None
    proficiency: Annotated[int, Field(ge=1, le=5)] | None = None
    time_complexity: Annotated[str, Field(max_length=4000)] | None = None
    space_complexity: Annotated[str, Field(max_length=4000)] | None = None
    defer_until: str | None = None
    skip_until: str | None = None
    assistance: Literal["none", "hint", "solution"] | None = None


class FeedbackRequest(BaseModel):
    """Bind feedback changes to a stable operation and expected practice revision."""

    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    submission_id: Annotated[str, Field(min_length=1, max_length=200)]
    expected_revision: Annotated[int, Field(ge=0)]
    kind: Literal["progress", "correction"] = "progress"
    changes: FeedbackChanges
    occurred_at: str | None = None


class StopRequest(BaseModel):
    """Bind a private shutdown request to one managed instance."""

    model_config = ConfigDict(strict=True, extra="forbid")
    instance_id: Annotated[str, Field(min_length=1, max_length=200)]


class SolutionDocument(BaseModel):
    """Describe user-supplied code without accepting a browser-written verdict."""

    model_config = ConfigDict(strict=True, extra="forbid")
    code: Annotated[str, Field(min_length=1, max_length=200000)]
    language: Annotated[str, Field(min_length=1, max_length=40)]
    input_definition: Annotated[str, Field(max_length=4000)] | None = None


class SolutionRequest(BaseModel):
    """Bind code evidence to one saved feedback revision and retry identity."""

    model_config = ConfigDict(strict=True, extra="forbid")
    submission_id: Annotated[str, Field(min_length=1, max_length=200)]
    expected_revision: Annotated[int, Field(ge=0)]
    document: SolutionDocument


def _error(code: str, message: str, status: int, details: object = None) -> JSONResponse:
    """Inputs: safe error fields and an HTTP status. Outputs: a JSON error.

    Logic: use one envelope without request bodies, SQL, or private file paths.
    Dependencies: JSONResponse.
    """
    return JSONResponse({"ok": False, "error": {"code": code, "message": message, "details": details}}, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _store_arguments(request: Request, arguments: dict | None = None, required: bool = False) -> dict:
    """Inputs: request headers, operation fields, and a required identity flag.
    Outputs: Arguments carrying an optional expected database identity.

    Logic: Reject duplicate identities and preserve absence only for safe reads.
    Dependencies: Request headers and the common core error contract.
    """
    values = request.headers.getlist("x-coach-store-id")
    if len(values) > 1:
        raise CoachError("workspace_mismatch", "Reload the feedback link for this workspace.")
    result = dict(arguments or {})
    if values or required:
        result["_expected_store_id"] = values[0] if values else None
    return result


def _authority(value: str) -> str:
    """Inputs: a Host authority. Outputs: a canonical loopback authority.

    Logic: allow only explicit loopback names and valid ports; reject rebinding hosts.
    Dependencies: urllib.parse and CoachError.
    """
    try:
        parsed = urlsplit("//" + value)
        hostname = parsed.hostname
        port = parsed.port
        if any(character.isspace() for character in value) or parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Invalid authority")
        if hostname not in {"127.0.0.1", "localhost", "::1"} or (port is not None and not 1 <= port <= 65535):
            raise ValueError("Non-loopback authority")
        if value.endswith(":"):
            raise ValueError("Empty port")
    except (ValueError, TypeError) as exc:
        raise CoachError("invalid_host", "Use a loopback Host with a valid port.") from exc
    host = "[::1]" if hostname == "::1" else hostname
    return host + (f":{port}" if port is not None else "")


def _origin(value: str) -> str:
    """Inputs: an Origin value. Outputs: its canonical loopback origin.

    Logic: reject credentials, paths, unknown schemes, and non-local origins.
    Dependencies: urlsplit and the strict authority validator.
    """
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Invalid origin")
        authority = _authority(parsed.netloc)
    except (ValueError, CoachError) as exc:
        raise CoachError("invalid_origin", "Use the local UI's exact origin.") from exc
    return parsed.scheme + "://" + authority


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    """Inputs: parsed JSON object fields. Outputs: one unambiguous object.

    Logic: reject duplicate keys instead of silently choosing a value.
    Dependencies: CoachError.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoachError("validation_error", "Duplicate JSON fields are not allowed.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Inputs: a JSON constant. Outputs: no value; raise a validation error.

    Logic: reject NaN and Infinity before domain validation.
    Dependencies: CoachError.
    """
    raise CoachError("validation_error", "JSON numbers must be finite.")


class LocalRequestBoundary:
    """Check loopback hosts and explicit JSON origins before any business operation."""

    def __init__(self, app: object, allowed_origin: str | None = None) -> None:
        """Inputs: an ASGI app and an optional local development origin.
        Outputs: a request boundary middleware instance.

        Logic: store a prevalidated origin without changing application state.
        Dependencies: ASGI and the loopback origin validator.
        """
        self.app = app
        self.allowed_origin = _origin(allowed_origin) if allowed_origin is not None else None

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        """Inputs: ASGI scope and channels. Outputs: one guarded HTTP response.

        Logic: reject unsafe browser writes and bound strict JSON before routing.
        Dependencies: JSON parsing, safe error envelopes, and the wrapped ASGI app.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = scope.get("headers", [])
        hosts = [value.decode("latin-1") for name, value in raw_headers if name.lower() == b"host"]
        try:
            if len(hosts) != 1:
                raise CoachError("invalid_host", "Send exactly one local Host header.")
            authority = _authority(hosts[0])
        except CoachError as exc:
            await _error(exc.code, exc.message, 400)(scope, receive, send)
            return
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origins = [value.decode("latin-1") for name, value in raw_headers if name.lower() == b"origin"]
            try:
                if len(origins) != 1:
                    raise CoachError("invalid_origin", "Writes require the local UI Origin header.")
                actual_origin = _origin(origins[0])
                expected_origin = scope.get("scheme", "http") + "://" + authority
                if actual_origin not in {expected_origin, self.allowed_origin}:
                    raise CoachError("invalid_origin", "Cross-origin writes are not allowed.")
            except CoachError as exc:
                await _error(exc.code, exc.message, 403)(scope, receive, send)
                return
            types = [value.decode("latin-1").split(";", 1)[0].strip().lower() for name, value in raw_headers if name.lower() == b"content-type"]
            if types != ["application/json"]:
                await _error("unsupported_media_type", "Writes require application/json.", 415)(scope, receive, send)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_REQUEST_BYTES:
                    await _error("request_too_large", "The JSON request exceeds one MiB.", 413)(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            try:
                parsed = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
            except (ValueError, UnicodeError, CoachError, RecursionError):
                await _error("validation_error", "Send valid JSON with unique fields and finite numbers.", 422)(scope, receive, send)
                return
            scope.setdefault("state", {})["feedback_json"] = parsed

        async def safe_send(message: dict) -> None:
            """Inputs: an ASGI response message. Outputs: the forwarded message.

            Logic: mark API responses private and non-cacheable.
            Dependencies: the original send channel and request path.
            """
            if message["type"] == "http.response.start" and scope["path"].startswith(("/v1/", "/internal/")):
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"]
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, safe_send)


def _submission_data(coach: Coach, receipt: dict) -> dict:
    """Inputs: one service and a committed receipt. Outputs: an exact revision payload.

    Logic: resolve the immutable submitted revision, even after later corrections.
    Dependencies: Coach history; no new connection or transaction is created here.
    """
    revision = None
    if receipt["operation"] == "submit_feedback":
        for record in coach.history(receipt["attempt_id"])["revisions"]:
            if record["revision"] == receipt["revision"] and record["submission_id"] == receipt["submission_id"]:
                revision = record
                break
        if revision is None:
            raise CoachError("integrity_error", "The committed feedback revision is unavailable.")
    return {"receipt": receipt, "feedback_revision": revision}


def _execute(data_dir: Path, operation: str, arguments: dict) -> dict:
    """Inputs: server data directory, operation, and arguments. Outputs: core data.

    Logic: create, use, and close one Coach in the same synchronous worker.
    Dependencies: the shared core and its existing initialized SQLite database.
    """
    coach = Coach(data_dir / "coach.sqlite3")
    try:
        arguments = dict(arguments)
        if "_expected_store_id" in arguments:
            expected = arguments.pop("_expected_store_id")
            identity = coach.get_workspace_identity()
            actual = store_id(data_dir / "coach.sqlite3", identity["workspace_id"])
            if expected != actual:
                raise CoachError("workspace_mismatch", "Reload the feedback link for this workspace.")
        if operation == "context":
            config = coach.get_config()["config"]
            identity = coach.get_workspace_identity()
            return {"workspace_id": identity["workspace_id"], "store_id": store_id(data_dir / "coach.sqlite3", identity["workspace_id"]), "training_date": datetime.now(ZoneInfo(config["timezone"])).date().isoformat(), "timezone": config["timezone"], "language": config["language"], "api_version": API_VERSION, "app_version": __version__}
        if operation == "plan":
            return coach.get_plan(arguments["date"])
        if operation == "scores":
            return coach.get_topic_scores(arguments.get("language"))
        if operation == "progress":
            return coach.get_practice_progress(arguments.get("language"))
        if operation == "feedback":
            return _submission_data(coach, coach.submit_feedback(**arguments))
        if operation == "solution":
            return _submission_data(coach, coach.record_solution(**arguments))
        if operation == "complexity":
            return coach.complexity_status(arguments["attempt_id"])
        if operation == "receipt":
            return _submission_data(coach, coach.receipt(arguments["submission_id"]))
        raise CoachError("not_found", "The local operation does not exist.")
    except CoachError:
        raise
    except sqlite3.Error as exc:
        raise CoachError("storage_error", "The local database operation failed.") from exc
    except OSError:
        raise CoachError("storage_error", "The local database is unavailable.") from None
    except Exception:
        raise CoachError("internal_error", "The local service could not complete this request.") from None
    finally:
        coach.close()


def _busy(error: BaseException) -> bool:
    """Inputs: an exception chain. Outputs: whether SQLite reported contention.

    Logic: classify only SQLite busy or locked codes as retryable availability errors.
    Dependencies: sqlite3 error codes and exception causes.
    """
    current = error
    for _ in range(10):
        if isinstance(current, sqlite3.Error):
            code = getattr(current, "sqlite_errorcode", None)
            if code is not None and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                return True
        cause = current.__cause__
        if cause is None:
            break
        current = cause
    return False


def create_app(data_dir: Path, static_dir: Path | None = None, allowed_origin: str | None = None, *, runtime_context: dict | None = None, control_token: str | None = None, request_shutdown: Callable[[], None] | None = None) -> FastAPI:
    """Inputs: local data, assets, dev origin, and optional managed process controls.
    Outputs: a FastAPI app without starting a server or creating data.

    Logic: expose read-only plans and scores plus one shared-core feedback endpoint.
    Dependencies: optional web libraries and an initialized core database at startup.
    """
    directory = Path(data_dir).expanduser()
    if not directory.is_absolute():
        raise CoachError("validation_error", "The data directory must be an absolute path.")
    if allowed_origin is not None:
        _origin(allowed_origin)
    managed_instance = runtime_context.get("instance_id") if runtime_context is not None else None
    if runtime_context is not None and (not isinstance(managed_instance, str) or not managed_instance or len(managed_instance) > 200):
        raise CoachError("validation_error", "Set a valid managed instance identity.")
    startup_identity = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Inputs: the app. Outputs: its startup and shutdown context.

        Logic: validate the selected current store in one worker.
        Dependencies: _execute and Starlette's thread pool.
        """
        nonlocal startup_identity
        current = await run_in_threadpool(_execute, directory, "context", {})
        if runtime_context is not None:
            startup_identity = {"workspace_id": current["workspace_id"], "store_id": current["store_id"]}
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalRequestBoundary, allowed_origin=allowed_origin)

    @app.exception_handler(CoachError)
    async def core_error(request: Request, exc: CoachError) -> JSONResponse:
        """Inputs: request and safe core error. Outputs: a stable JSON failure.

        Logic: map missing data, conflicts, invalid inputs, and contention to HTTP.
        Dependencies: the core's stable error codes and SQLite cause inspection.
        """
        if _busy(exc):
            return _error("database_busy", "The local database is busy; retry this submission ID.", 503)
        if exc.code == "not_found":
            status = 404
        elif exc.code in {"revision_conflict", "idempotency_conflict", "config_conflict", "review_conflict", "schema_mismatch", "workspace_mismatch"}:
            status = 409
        elif exc.code in {"validation_error", "policy_violation", "daily_capacity_exceeded"}:
            status = 422
        else:
            return _error(exc.code, "The local data service is unavailable.", 500)
        return _error(exc.code, exc.message, status, exc.details)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request: Request, exc: Exception) -> JSONResponse:
        """Inputs: request and validation error. Outputs: a sanitized 422 response.

        Logic: do not echo submitted notes, invalid values, or exception internals.
        Dependencies: the common error envelope.
        """
        return _error("validation_error", "The request does not match the feedback contract.", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        """Inputs: request and routing error. Outputs: a consistent safe envelope.

        Logic: keep unknown API and asset routes from returning a UI fallback.
        Dependencies: HTTPException and the common error envelope.
        """
        return _error("not_found" if exc.status_code == 404 else "http_error", "The requested local resource is unavailable.", exc.status_code)

    @app.get("/v1/context")
    def context(request: Request) -> dict:
        """Inputs: none. Outputs: workspace identity and the configured training date.

        Logic: read existing configuration and metadata without creating a plan.
        Dependencies: _execute and the shared core.
        """
        return {"ok": True, "data": _execute(directory, "context", _store_arguments(request))}

    @app.get("/v1/runtime")
    def runtime(request: Request) -> dict:
        """Inputs: an optional expected store header. Outputs: safe live readiness.

        Logic: Prefer fresh identity; retain startup ownership only for failed managed reads.
        Dependencies: The shared context reader, UI manifest checker, and runtime metadata.
        """
        arguments = _store_arguments(request)
        database_ready = True
        try:
            current = _execute(directory, "context", arguments)
        except CoachError as error:
            if startup_identity is None or error.code == "workspace_mismatch":
                raise
            expected = arguments.get("_expected_store_id")
            if expected is not None and expected != startup_identity["store_id"]:
                raise CoachError("workspace_mismatch", "Reload the feedback link for this workspace.") from error
            current = startup_identity
            database_ready = False
        ui = inspect_ui(static_dir)
        return {"ok": True, "data": {
            "service": SERVICE_NAME, "runtime_protocol": RUNTIME_PROTOCOL,
            "workspace_id": current["workspace_id"], "store_id": current["store_id"],
            "api_version": API_VERSION, "app_version": __version__,
            "ui_build_id": ui["ui_build_id"], "ui_ready": ui["ui_ready"],
            "database_ready": database_ready, "managed": runtime_context is not None,
            "instance_id": managed_instance,
        }}

    @app.get("/v1/plans/{training_date}")
    def plan(training_date: str, request: Request) -> dict:
        """Inputs: a training date. Outputs: its existing frozen plan.

        Logic: return not found when no plan exists; never call ensure_plan.
        Dependencies: Coach.get_plan through _execute.
        """
        return {"ok": True, "data": _execute(directory, "plan", _store_arguments(request, {"date": training_date}))}

    @app.get("/v1/scores")
    def scores(request: Request, language: str | None = None) -> dict:
        """Inputs: an optional language. Outputs: recorded topic performance scores.

        Logic: use the core's read-only scoring contract.
        Dependencies: Coach.get_topic_scores through _execute.
        """
        return {"ok": True, "data": _execute(directory, "scores", _store_arguments(request, {"language": language}))}

    @app.get("/v1/progress")
    def progress(request: Request, language: str | None = None) -> dict:
        """Inputs: an optional language. Outputs: daily activity and problem results.

        Logic: use the core's read-only progress contract without writing.
        Dependencies: Coach.get_practice_progress through _execute.
        """
        return {"ok": True, "data": _execute(directory, "progress", _store_arguments(request, {"language": language}))}

    @app.post("/v1/attempts/{attempt_id}/feedback")
    def feedback(attempt_id: str, request: Request) -> dict:
        """Inputs: attempt ID and strict JSON. Outputs: receipt and exact saved revision.

        Logic: preserve omitted fields, explicit null, false, and stable retry IDs.
        Dependencies: Pydantic validation and one shared-core worker operation.
        """
        body = FeedbackRequest.model_validate(request.state.feedback_json)
        arguments = {"attempt_id": attempt_id, "submission_id": body.submission_id, "expected_revision": body.expected_revision, "changes": body.changes.model_dump(exclude_unset=True), "kind": body.kind, "occurred_at": body.occurred_at}
        return {"ok": True, "data": _execute(directory, "feedback", _store_arguments(request, arguments, required=True))}

    @app.get("/v1/attempts/{attempt_id}/complexity")
    def complexity(attempt_id: str, request: Request) -> dict:
        """Inputs: an attempt and optional store guard. Outputs: saved review status.

        Logic: Read existing evidence without running a model or generating work.
        Dependencies: Coach.complexity_status through the shared worker operation.
        """
        return {"ok": True, "data": _execute(directory, "complexity", _store_arguments(request, {"attempt_id": attempt_id}))}

    @app.post("/v1/attempts/{attempt_id}/solution")
    def solution(attempt_id: str, request: Request) -> dict:
        """Inputs: strict code evidence and revision. Outputs: a committed receipt.

        Logic: Save evidence only; the browser cannot write a model assessment.
        Dependencies: SolutionRequest, store identity, and Coach.record_solution.
        """
        body = SolutionRequest.model_validate(request.state.feedback_json)
        arguments = {"attempt_id": attempt_id, "submission_id": body.submission_id,
                     "expected_revision": body.expected_revision,
                     "document": body.document.model_dump(exclude_unset=True)}
        return {"ok": True, "data": _execute(directory, "solution", _store_arguments(request, arguments, required=True))}

    @app.get("/v1/submissions/{submission_id}")
    def submission(submission_id: str, request: Request) -> dict:
        """Inputs: a stable submission ID. Outputs: receipt and its immutable revision.

        Logic: allow a lost response to be checked without submitting again.
        Dependencies: Coach receipt and history readers through _execute.
        """
        return {"ok": True, "data": _execute(directory, "receipt", _store_arguments(request, {"submission_id": submission_id}))}

    @app.post("/internal/runtime/stop")
    def stop(request: Request) -> JSONResponse:
        """Inputs: a private token and exact instance ID. Outputs: a shutdown acknowledgment.

        Logic: Authorize managed control before scheduling shutdown after the response.
        Dependencies: Constant-time token checks, StopRequest, and BackgroundTask.
        """
        tokens = request.headers.getlist("x-coach-control-token")
        if runtime_context is None or not control_token or request_shutdown is None or len(tokens) != 1:
            return _error("control_denied", "This managed control request was rejected.", 403)
        if not secrets.compare_digest(tokens[0].encode("utf-8"), control_token.encode("utf-8")):
            return _error("control_denied", "This managed control request was rejected.", 403)
        body = StopRequest.model_validate(request.state.feedback_json)
        if body.instance_id != managed_instance:
            return _error("control_denied", "This managed control request was rejected.", 403)
        return JSONResponse({"ok": True, "data": {"stopping": True, "instance_id": managed_instance}}, background=BackgroundTask(request_shutdown))

    @app.api_route("/internal/{unknown:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.api_route("/v1/{unknown:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def unknown_api(unknown: str) -> JSONResponse:
        """Inputs: an unknown API path. Outputs: a JSON 404 response.

        Logic: reserve the API namespace before optional static-file routing.
        Dependencies: the common error envelope.
        """
        return _error("not_found", "The API endpoint does not exist.", 404)

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=Path(static_dir), html=True, follow_symlink=False), name="ui")
    return app


def main(argv: list[str] | None = None) -> int:
    """Inputs: optional command arguments. Outputs: a process exit code.

    Logic: validate local paths and start one loopback server without proxy trust.
    Dependencies: argparse, optional Uvicorn, and an initialized local database.
    """
    parser = argparse.ArgumentParser(description="Serve the local algorithm feedback UI.")
    parser.add_argument("--data-dir", default=os.environ.get("ALGORITHM_COACH_DATA_DIR"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--static-dir")
    parser.add_argument("--allowed-origin", help="Allow one explicit loopback development origin.")
    args = parser.parse_args(argv)
    try:
        if not args.data_dir or not 1 <= args.port <= 65535:
            raise CoachError("validation_error", "Set an absolute data directory and a port from 1 to 65535.")
        directory = Path(args.data_dir).expanduser()
        if not directory.is_absolute():
            raise CoachError("validation_error", "The data directory must be an absolute path.")
        assets = Path(args.static_dir).expanduser() if args.static_dir else None
        if assets is None:
            candidate = Path(__file__).resolve().parents[3] / "web" / "dist"
            assets = candidate if candidate.is_dir() else None
        _execute(directory, "context", {})
        app = create_app(directory, assets, args.allowed_origin)
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
        return 0
    except (CoachError, OSError, RuntimeError):
        print(json.dumps({"ok": False, "error": {"code": "startup_error", "message": "Check the local data directory, schema, assets, port, and origin configuration.", "details": None}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
