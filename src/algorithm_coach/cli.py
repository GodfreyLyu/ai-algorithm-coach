"""Parse local training commands and return structured JSON receipts or errors."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tomllib
from urllib.parse import urlencode

from .errors import CoachError
from .service import Coach


def _reject_constant(value: str) -> None:
    """Reject non-finite JSON constants.

    Inputs: A JSON constant token.
    Outputs: None. Raise a validation error instead.
    Logic: Reject NaN and Infinity before they reach domain rules.
    Dependencies: CoachError.
    """
    raise CoachError("validation_error", f"Invalid JSON number: {value}.")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys before request normalization.

    Inputs: Object fields in their original order.
    Outputs: One dictionary with unique field names.
    Logic: Refuse ambiguous objects instead of silently choosing the last value.
    Dependencies: CoachError.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoachError("validation_error", f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _changes(value: str) -> dict:
    """Read a JSON object passed by a tool or a person.

    Inputs: A JSON string.
    Outputs: A dictionary of explicit field changes.
    Logic: Parse strict JSON and reject values that are not objects.
    Dependencies: json and CoachError.
    """
    try:
        parsed = json.loads(value, parse_constant=_reject_constant, object_pairs_hook=_unique_fields)
    except (ValueError, TypeError) as exc:
        raise CoachError("validation_error", "Changes must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise CoachError("validation_error", "Changes must be a JSON object.")
    return parsed


def _document(path: str, limit: int = 1_048_576) -> dict:
    """Read a local policy or metadata document.

    Inputs: A JSON or TOML file path supplied by the caller.
    Outputs: A parsed object.
    Logic: Bound input size, parse the declared format, and reject invalid roots.
    Dependencies: pathlib, tomllib, the strict JSON reader, and CoachError.
    """
    source = Path(path).expanduser()
    if source.stat().st_size > limit:
        raise CoachError("validation_error", f"Input documents must be at most {limit} bytes.")
    try:
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".toml":
            document = tomllib.loads(text)
            if not isinstance(document, dict):
                raise CoachError("validation_error", "The document must be an object.")
            return document
        if source.suffix.lower() == ".json":
            return _changes(text)
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CoachError("validation_error", "The input document is not valid UTF-8 TOML or JSON.") from exc
    raise CoachError("validation_error", "Use a .toml or .json input document.")


def _policy_commands(commands: argparse._SubParsersAction) -> None:
    """Describe policy discovery, proposal, preview, and activation commands.

    Inputs: The top-level subcommand collection.
    Outputs: None. Add parsers to the collection.
    Logic: Separate proposed content from activation of an exact content hash.
    Dependencies: argparse.
    """
    commands.add_parser("capabilities", help="Read supported policy fields and catalog tags.")
    policy = commands.add_parser("policy", help="Inspect or change versioned training scope.")
    operations = policy.add_subparsers(dest="policy_command", required=True)
    get = operations.add_parser("get")
    get.add_argument("--date")
    operations.add_parser("history")
    propose = operations.add_parser("propose")
    inputs = propose.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--changes")
    inputs.add_argument("--file")
    propose.add_argument("--expected-revision", required=True, type=int)
    propose.add_argument("--submission", required=True)
    preview = operations.add_parser("preview")
    preview.add_argument("--proposal", required=True)
    preview.add_argument("--date")
    activate = operations.add_parser("activate")
    activate.add_argument("--proposal", required=True)
    activate.add_argument("--expected-revision", required=True, type=int)
    activate.add_argument("--accept-hash", required=True)
    activate.add_argument("--submission", required=True)


def _parser() -> argparse.ArgumentParser:
    """Describe the supported local commands.

    Inputs: None.
    Outputs: An argument parser.
    Logic: Define explicit inputs for all core operations.
    Dependencies: argparse and the optional data directory environment value.
    """
    parser = argparse.ArgumentParser(description="Run a local algorithm training loop.")
    parser.add_argument("--data-dir", default=os.environ.get("ALGORITHM_COACH_DATA_DIR"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a private local database.")
    init.add_argument("--timezone", default="UTC")
    init.add_argument("--daily-count", type=int, default=5)
    init.add_argument("--language", default="Java")
    init.add_argument("--profile", default="standard", choices=("standard", "tokyo-interview-v1"))
    for command in ("plan", "show"):
        sub = commands.add_parser(command)
        sub.add_argument("--date")
    session = commands.add_parser("start-session", help="Prepare a training plan and its local feedback page.")
    session.add_argument("--date")
    session.add_argument("--web-python")
    session.add_argument("--web-port", type=int)
    session.add_argument("--web-static-dir", type=Path)
    session.add_argument("--no-web", action="store_true")
    web = commands.add_parser("web", help="Inspect or stop this workspace's managed Web instance.")
    web.add_argument("web_command", choices=("status", "stop"))
    feedback = commands.add_parser("feedback", help="Save progress or a correction.")
    feedback.add_argument("--attempt", required=True)
    feedback.add_argument("--submission", required=True)
    feedback.add_argument("--expected-revision", required=True, type=int)
    feedback.add_argument("--changes", required=True)
    feedback.add_argument("--kind", choices=("progress", "correction"), default="progress")
    feedback.add_argument("--occurred-at")
    history = commands.add_parser("history")
    history_target = history.add_mutually_exclusive_group(required=True)
    history_target.add_argument("--attempt")
    history_target.add_argument("--problem")
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--submission", required=True)
    state = commands.add_parser("state")
    state.add_argument("--summary", action="store_true")
    config = commands.add_parser("config")
    config.add_argument("--changes")
    config.add_argument("--expected-revision", type=int)
    config.add_argument("--preview", action="store_true", help="Validate changes and preview selection without saving.")
    config.add_argument("--date", help="Training date for --preview.")
    practice = commands.add_parser("practice", help="Create an explicit redo or retest.")
    practice.add_argument("--problem", required=True)
    practice.add_argument("--submission", required=True)
    practice.add_argument("--language")
    practice.add_argument("--review")
    practice.add_argument("--date")
    catalog = commands.add_parser("catalog")
    catalog_operations = catalog.add_subparsers(dest="catalog_command")
    catalog_preview = catalog_operations.add_parser("preview", help="Preview metadata without saving it.")
    catalog_preview.add_argument("--file", required=True)
    catalog_import = catalog_operations.add_parser("import", help="Append validated problem metadata.")
    catalog_import.add_argument("--file", required=True)
    catalog_import.add_argument("--submission", required=True)
    catalog_import.add_argument("--expected-hash", help="Require the normalized payload hash from a preview.")
    _policy_commands(commands)
    review = commands.add_parser("review", help="Record code or scoped host-model complexity analysis.")
    review_ops = review.add_subparsers(dest="review_command", required=True)
    review_status = review_ops.add_parser("status")
    review_status.add_argument("--attempt")
    review_status.add_argument("--pending", action="store_true")
    evidence = review_ops.add_parser("evidence")
    evidence.add_argument("--attempt", required=True)
    evidence.add_argument("--expected-revision", type=int, required=True)
    evidence.add_argument("--submission", required=True)
    evidence.add_argument("--file", required=True)
    assessment = review_ops.add_parser("submit")
    assessment.add_argument("--submission", required=True)
    assessment.add_argument("--file", required=True)
    context = commands.add_parser("training-context", help="Save researched framework and selection evidence.")
    context.add_argument("--submission", required=True)
    context.add_argument("--file", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    commands.add_parser("check")
    commands.add_parser("rebuild-state")
    return parser


def _execute_policy(coach: Coach, args: argparse.Namespace) -> dict:
    """Route policy commands through the shared application service.

    Inputs: A Coach instance and parsed policy arguments.
    Outputs: A JSON-compatible policy result or committed receipt.
    Logic: Read input documents for proposals and pass exact activation identities.
    Dependencies: Coach and the JSON or TOML input readers.
    """
    if args.policy_command == "get":
        return coach.get_policy(args.date)
    if args.policy_command == "history":
        return coach.policy_history()
    if args.policy_command == "propose":
        changes = _document(args.file) if args.file else _changes(args.changes)
        return coach.propose_policy(changes, args.expected_revision, args.submission)
    if args.policy_command == "preview":
        return coach.preview_policy(args.proposal, args.date)
    if args.policy_command == "activate":
        return coach.activate_policy(args.proposal, args.expected_revision,
                                     args.accept_hash, args.submission)
    raise CoachError("validation_error", "Unknown policy command.")


def _execute(coach: Coach, args: argparse.Namespace) -> dict:
    """Route one validated command to the core.

    Inputs: A Coach instance and parsed arguments.
    Outputs: A JSON-compatible core result.
    Logic: Call one shared application operation. Do not duplicate rules.
    Dependencies: Coach and the strict JSON input reader.
    """
    if args.command == "init":
        return coach.initialize({"timezone": args.timezone, "daily_count": args.daily_count,
                                 "language": args.language, "training_profile": args.profile})
    if args.command == "plan":
        return coach.ensure_plan(args.date)
    if args.command == "start-session":
        plan = coach.ensure_plan(args.date)
        coach.close()
        if args.no_web:
            web = {"status": "disabled", "action": "none", "reason": "disabled", "url": None}
        else:
            from .web.runtime import ensure_web

            web = ensure_web(Path(args.data_dir).expanduser(), python=args.web_python,
                             static_dir=args.web_static_dir, preferred_port=args.web_port)
        if web.get("status") == "ready":
            query = urlencode({"date": plan["training_date"], "store": web["store_id"]})
            web = {**web, "url": web["url"].rstrip("/") + "/?" + query}
        return {"plan": plan, "web": web}
    if args.command == "web":
        from .web.runtime import stop_web, web_status

        coach.close()
        operation = web_status if args.web_command == "status" else stop_web
        return operation(Path(args.data_dir).expanduser())
    if args.command == "show":
        return coach.get_plan(args.date)
    if args.command == "feedback":
        return coach.submit_feedback(
            attempt_id=args.attempt, submission_id=args.submission,
            expected_revision=args.expected_revision, changes=_changes(args.changes),
            kind=args.kind, occurred_at=args.occurred_at,
        )
    if args.command == "history":
        return coach.history(args.attempt) if args.attempt else coach.history_for_problem(args.problem)
    if args.command == "receipt":
        return coach.receipt(args.submission)
    if args.command == "state":
        state = coach.learning_state()
        if args.summary:
            state.pop("attempts", None)
        return state
    if args.command == "config":
        if args.preview:
            if args.changes is None or args.expected_revision is not None:
                raise CoachError("validation_error", "Use --preview with --changes and without --expected-revision.")
            return coach.preview_config(_changes(args.changes), args.date)
        if args.date is not None:
            raise CoachError("validation_error", "Use --date only with --preview.")
        if args.changes is None:
            if args.expected_revision is not None:
                raise CoachError("validation_error", "Use --changes with --expected-revision.")
            return coach.get_config()
        if args.expected_revision is None:
            raise CoachError("validation_error", "A config update needs --expected-revision.")
        return coach.update_config(_changes(args.changes), args.expected_revision)
    if args.command == "practice":
        return coach.start_practice(
            problem_id=args.problem, submission_id=args.submission, language=args.language,
            review_id=args.review, training_date=args.date,
        )
    if args.command == "catalog":
        if args.catalog_command in ("preview", "import"):
            document = _document(args.file)
            if set(document) != {"problems"} or not isinstance(document["problems"], list):
                raise CoachError("validation_error", "Catalog documents need only a problems array.")
            if args.catalog_command == "preview":
                return coach.preview_catalog(document["problems"])
            return coach.import_catalog(document["problems"], args.submission, expected_hash=args.expected_hash)
        return coach.list_problems()
    if args.command == "capabilities":
        return coach.policy_capabilities()
    if args.command == "policy":
        return _execute_policy(coach, args)
    if args.command == "review":
        if args.review_command == "status":
            result = coach.complexity_status(args.attempt)
            if args.pending:
                result["items"] = [item for item in result["items"] if item["status"] in {"pending", "stale"}]
            return result
        if args.review_command == "evidence":
            return coach.record_solution(args.attempt, args.submission, args.expected_revision, _document(args.file))
        return coach.submit_complexity_review(args.submission, _document(args.file))
    if args.command == "training-context":
        return coach.save_training_context(args.submission, _document(args.file))
    if args.command == "backup":
        return coach.backup(Path(args.output).expanduser())
    if args.command == "check":
        return coach.integrity_check()
    if args.command == "rebuild-state":
        return coach.rebuild_state()
    raise CoachError("validation_error", "Unknown command.")


def main(argv: list[str] | None = None) -> int:
    """Execute a command and print one JSON result.

    Inputs: Optional argument strings. None reads the process arguments.
    Outputs: Exit code 0 on success or 1 on a handled failure.
    Logic: Require a private data path, invoke the core, and close its connection.
    Dependencies: argparse, pathlib, Coach, SQLite, and stdout.
    """
    args = _parser().parse_args(argv)
    coach = None
    try:
        if not args.data_dir:
            raise CoachError("validation_error", "Set --data-dir or ALGORITHM_COACH_DATA_DIR once.")
        data_dir = Path(args.data_dir).expanduser()
        if not data_dir.is_absolute():
            raise CoachError("validation_error", "The data directory must be an absolute path.")
        coach = Coach(data_dir / "coach.sqlite3")
        result = {"ok": True, "data": _execute(coach, args)}
        exit_code = 0
    except CoachError as exc:
        result = {"ok": False, "error": {"code": exc.code, "message": str(exc),
                                          "details": exc.details}}
        exit_code = 1
    except (OSError, sqlite3.Error) as exc:
        result = {"ok": False, "error": {"code": "storage_error", "message": str(exc)}}
        exit_code = 1
    finally:
        if coach is not None:
            coach.close()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return exit_code
