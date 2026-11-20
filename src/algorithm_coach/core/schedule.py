"""Describe and check a desired daily run time without starting any scheduler."""

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..errors import CoachError

NEAR_MIDNIGHT = time(23, 30)


def _zone(name: object, field: str) -> ZoneInfo:
    """Resolve an IANA timezone name.

    Inputs: A timezone name and its field label.
    Outputs: A ZoneInfo object, or a validation error.
    Logic: Reject abbreviations and offsets that are not IANA names.
    Dependencies: zoneinfo and CoachError.
    """
    if not isinstance(name, str) or not name or len(name) > 100:
        raise CoachError("validation_error", f"{field} must be an IANA timezone name.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CoachError("validation_error", f"{field} must be an available IANA timezone name.") from exc


def _local_run(day: date, at: time, zone: ZoneInfo) -> tuple[datetime, str | None]:
    """Resolve one wall-clock run time on one local date.

    Inputs: A local date, a wall-clock time, and a timezone.
    Outputs: The aware run instant and an optional DST adjustment code.
    Logic: Move a missing time past the gap. Use the first of two repeated times.
    Dependencies: zoneinfo fold semantics.
    """
    naive = datetime.combine(day, at)
    first = naive.replace(tzinfo=zone, fold=0)
    resolved = first.astimezone(timezone.utc).astimezone(zone)
    if resolved.replace(tzinfo=None) != naive:
        return resolved, "dst_gap"
    if naive.replace(tzinfo=zone, fold=1).utcoffset() != first.utcoffset():
        return first, "dst_fold"
    return first, None


def _runs(at: time, zone: ZoneInfo, now: datetime, count: int) -> list[dict]:
    """List the next run instants after a reference time.

    Inputs: A wall-clock time, timezone, aware reference time, and count.
    Outputs: Local and UTC instants with their training dates.
    Logic: The training date is the local date of each run in the zone.
    Dependencies: _local_run.
    """
    runs = []
    day = now.astimezone(zone).date()
    while len(runs) < count:
        instant, adjustment = _local_run(day, at, zone)
        if instant > now:
            item = {"local": instant.isoformat(), "utc": instant.astimezone(timezone.utc).isoformat(),
                    "training_date": instant.date().isoformat()}
            if adjustment:
                item["adjustment"] = adjustment
            runs.append(item)
        day += timedelta(days=1)
    return runs


def _parse_time(value: str) -> time:
    """Read a validated HH:MM setting.

    Inputs: A configuration run_time string.
    Outputs: A time object.
    Logic: The configuration validator already checked the format.
    Dependencies: datetime.time.
    """
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def describe_schedule(run_time: str | None, timezone_name: str, now: datetime, count: int = 3) -> dict:
    """Describe the desired daily trigger for a host or system scheduler.

    Inputs: Saved run_time and timezone, an aware current time, and a run count.
    Outputs: Scheduler expressions, next runs, and warnings.
    Logic: Produce data only. The host scheduler remains the actual trigger.
    Dependencies: _zone, _runs, and _local_run.
    """
    zone = _zone(timezone_name, "timezone")
    result = {"run_time": run_time, "timezone": timezone_name, "configured": run_time is not None,
              "authority": "host_scheduler", "scheduler_control": False}
    if run_time is None:
        result["message"] = "No preferred run time is saved. The host scheduler alone decides when runs start."
        return result
    at = _parse_time(run_time)
    result["rrule"] = f"FREQ=DAILY;BYHOUR={at.hour};BYMINUTE={at.minute}"
    result["cron"] = f"{at.minute} {at.hour} * * *"
    result["scheduler_timezone_required"] = timezone_name
    result["next_runs"] = _runs(at, zone, now, count)
    warnings = []
    if at >= NEAR_MIDNIGHT:
        warnings.append({"code": "near_midnight", "message": "A run that passes midnight plans the next local date."})
    start = now.astimezone(zone).date()
    affected = []
    for offset in range(366):
        day = start + timedelta(days=offset)
        code = _local_run(day, at, zone)[1]
        if code:
            affected.append({"date": day.isoformat(), "adjustment": code})
    if affected:
        warnings.append({"code": "dst_affected_dates", "dates": affected,
                         "message": "Daylight saving time moves or repeats this local time on these dates."})
    result["warnings"] = warnings
    return result


def _observed_time(rrule: str | None, cron: str | None) -> tuple[time, list[dict]]:
    """Read a daily trigger from a host rrule or cron expression.

    Inputs: Exactly one rrule or five-field cron expression.
    Outputs: The wall-clock time and unsupported-rule differences.
    Logic: Accept only simple daily rules; report anything else as a difference.
    Dependencies: re and CoachError.
    """
    if (rrule is None) == (cron is None):
        raise CoachError("validation_error", "Provide exactly one observed rrule or cron expression.")
    differences = []
    if rrule is not None:
        if not isinstance(rrule, str) or len(rrule) > 300:
            raise CoachError("validation_error", "The observed rrule must be short text.")
        parts = {}
        for piece in rrule.removeprefix("RRULE:").split(";"):
            key, _, value = piece.partition("=")
            parts[key.strip().upper()] = value.strip()
        if parts.get("FREQ") != "DAILY":
            differences.append({"field": "frequency", "observed": parts.get("FREQ"), "expected": "DAILY"})
        extra = sorted(set(parts) - {"FREQ", "BYHOUR", "BYMINUTE", "BYSECOND", "INTERVAL"})
        if extra or parts.get("INTERVAL", "1") != "1":
            differences.append({"field": "rule_parts", "observed": extra or [f"INTERVAL={parts['INTERVAL']}"], "expected": []})
        hour, minute = parts.get("BYHOUR", ""), parts.get("BYMINUTE", "0")
    else:
        fields = cron.split() if isinstance(cron, str) else []
        if len(fields) != 5:
            raise CoachError("validation_error", "The observed cron expression needs five fields.")
        minute, hour = fields[0], fields[1]
        if fields[2:] != ["*", "*", "*"]:
            differences.append({"field": "rule_parts", "observed": fields[2:], "expected": ["*", "*", "*"]})
    if not re.fullmatch(r"\d{1,2}", hour) or not re.fullmatch(r"\d{1,2}", minute) or int(hour) > 23 or int(minute) > 59:
        raise CoachError("validation_error", "The observed rule needs one fixed hour and minute.")
    return time(int(hour), int(minute)), differences


def check_schedule(run_time: str | None, timezone_name: str, now: datetime, observed_rrule: str | None = None,
                   observed_cron: str | None = None, observed_timezone: str | None = None) -> dict:
    """Compare the saved run time with a host scheduler's observed rule.

    Inputs: Saved settings, current time, an observed rule, and the scheduler timezone.
    Outputs: A match flag, differences, and the observed next runs in both zones.
    Logic: Report what is in effect. Never change the host task.
    Dependencies: describe_schedule, _observed_time, and _runs.
    """
    zone = _zone(timezone_name, "timezone")
    observed_zone_name = timezone_name if observed_timezone is None else observed_timezone
    observed_zone = _zone(observed_zone_name, "observed timezone")
    at, differences = _observed_time(observed_rrule, observed_cron)
    if run_time is None:
        differences.append({"field": "run_time", "observed": at.strftime("%H:%M"), "expected": None})
    elif _parse_time(run_time) != at:
        differences.append({"field": "run_time", "observed": at.strftime("%H:%M"), "expected": run_time})
    if observed_zone_name != timezone_name:
        differences.append({"field": "timezone", "observed": observed_zone_name, "expected": timezone_name,
                            "code": "timezone_mismatch"})
    runs = _runs(at, observed_zone, now, 3)
    for item in runs:
        local = datetime.fromisoformat(item["utc"]).astimezone(zone)
        item["workspace_local"] = local.isoformat()
        item["training_date"] = local.date().isoformat()
    return {"match": not differences, "differences": differences, "observed_next_runs": runs,
            "expected": describe_schedule(run_time, timezone_name, now)}
