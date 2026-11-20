"""Validate metadata-only catalog imports without fetching or trusting content."""

from copy import deepcopy
import re

from ..errors import CoachError

CATALOG_METADATA_FIELDS = ("id", "title", "difficulty", "tags", "url")
DIFFICULTIES = ("easy", "medium", "hard")


def validate_catalog(problems: list[dict]) -> list[dict]:
    """Normalize a bounded metadata import and reject unsafe or unknown fields.

    Inputs: A non-empty list of problem metadata objects.
    Outputs: Independent, normalized metadata sorted by numeric problem ID.
    Logic: Check canonical IDs, labels, tags, and official HTTPS problem links.
    Dependencies: CoachError and regular expressions. No network access occurs.
    """
    if not isinstance(problems, list) or not 1 <= len(problems) <= 10000:
        raise CoachError("validation_error", "Catalog imports must contain 1 to 10000 metadata objects.")
    result = []
    identifiers = set()
    for problem in problems:
        if not isinstance(problem, dict) or set(problem) != set(CATALOG_METADATA_FIELDS):
            raise CoachError("validation_error", "Each catalog entry needs exactly id, title, difficulty, tags, and url.")
        normalized = deepcopy(problem)
        identifier = normalized["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"leetcode:[1-9][0-9]{0,11}", identifier):
            raise CoachError("validation_error", "Problem IDs must use canonical leetcode:<positive integer> form.")
        if identifier in identifiers:
            raise CoachError("validation_error", "Catalog imports must not contain duplicate problem IDs.")
        identifiers.add(identifier)
        title = normalized["title"]
        if not isinstance(title, str) or not title.strip() or not title.isprintable() or len(title) > 200:
            raise CoachError("validation_error", "Problem titles must be printable text from 1 to 200 characters.")
        normalized["title"] = title.strip()
        difficulty = normalized["difficulty"]
        if not isinstance(difficulty, str) or difficulty not in DIFFICULTIES:
            raise CoachError("validation_error", "Problem difficulty must be easy, medium, or hard.")
        tags = normalized["tags"]
        if not isinstance(tags, list) or not 1 <= len(tags) <= 30:
            raise CoachError("validation_error", "Problem tags must contain 1 to 30 distinct labels.")
        seen_tags = set()
        for tag in tags:
            if not isinstance(tag, str) or len(tag) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", tag):
                raise CoachError("validation_error", "Tags must be short lowercase labels separated by hyphens.")
            if tag in seen_tags:
                raise CoachError("validation_error", "Problem tags must not contain duplicates.")
            seen_tags.add(tag)
        normalized["tags"] = sorted(seen_tags)
        url = normalized["url"]
        if not isinstance(url, str) or len(url) > 300 or not re.fullmatch(r"https://leetcode\.com/problems/[a-z0-9]+(?:-[a-z0-9]+)*/", url):
            raise CoachError("validation_error", "Problem URLs must be official HTTPS leetcode.com/problems/<slug>/ links without extra URL parts.")
        result.append((int(identifier.split(":")[1]), normalized))
    return [problem for _, problem in sorted(result)]
