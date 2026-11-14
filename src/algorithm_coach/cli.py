"""Parse local training commands and return structured JSON receipts or errors."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

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


def _changes(value: str) -> dict:
    """Read a JSON object passed by a tool or a person.

    Inputs: A JSON string.
    Outputs: A dictionary of explicit field changes.
    Logic: Parse strict JSON and reject values that are not objects.
    Dependencies: json and CoachError.
    """
    try:
        parsed = json.loads(value, parse_constant=_reject_constant)
    except (ValueError, TypeError) as exc:
        raise CoachError("validation_error", "Changes must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise CoachError("validation_error", "Changes must be a JSON object.")
    return parsed


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
    for command in ("plan", "show"):
        sub = commands.add_parser(command)
        sub.add_argument("--date")
    feedback = commands.add_parser("feedback", help="Save progress or a correction.")
    feedback.add_argument("--attempt", required=True)
    feedback.add_argument("--submission", required=True)
    feedback.add_argument("--expected-revision", required=True, type=int)
    feedback.add_argument("--changes", required=True)
    feedback.add_argument("--kind", choices=("progress", "correction"), default="progress")
    feedback.add_argument("--occurred-at")
    history = commands.add_parser("history")
    history.add_argument("--attempt", required=True)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--submission", required=True)
    commands.add_parser("state")
    config = commands.add_parser("config")
    config.add_argument("--changes")
    config.add_argument("--expected-revision", type=int)
    practice = commands.add_parser("practice", help="Create an explicit redo or retest.")
    practice.add_argument("--problem", required=True)
    practice.add_argument("--submission", required=True)
    practice.add_argument("--language")
    practice.add_argument("--review")
    practice.add_argument("--date")
    commands.add_parser("catalog")
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    commands.add_parser("check")
    commands.add_parser("rebuild-state")
    return parser


def _execute(coach: Coach, args: argparse.Namespace) -> dict:
    """Route one validated command to the core.

    Inputs: A Coach instance and parsed arguments.
    Outputs: A JSON-compatible core result.
    Logic: Call one shared application operation. Do not duplicate rules.
    Dependencies: Coach and the strict JSON input reader.
    """
    if args.command == "init":
        return coach.initialize({"timezone": args.timezone, "daily_count": args.daily_count,
                                 "language": args.language})
    if args.command == "plan":
        return coach.ensure_plan(args.date)
    if args.command == "show":
        return coach.get_plan(args.date)
    if args.command == "feedback":
        return coach.submit_feedback(
            attempt_id=args.attempt, submission_id=args.submission,
            expected_revision=args.expected_revision, changes=_changes(args.changes),
            kind=args.kind, occurred_at=args.occurred_at,
        )
    if args.command == "history":
        return coach.history(args.attempt)
    if args.command == "receipt":
        return coach.receipt(args.submission)
    if args.command == "state":
        return coach.learning_state()
    if args.command == "config":
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
        return coach.list_problems()
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
