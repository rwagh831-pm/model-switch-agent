"""Scores one model answer against the known correct answer.

No AI runs here. The score has to be something a model cannot talk its way
around, and it has to give the same result every time.
"""

from __future__ import annotations

import json
import re

ORG_SUFFIX = r"(?:Inc|Ltd|LLC|Technologies|Solutions|Systems|Labs|Corp|Bank|University)"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def parse_field_answer(text: str) -> dict | None:
    """Read the model's JSON answer. Returns None if it is not valid JSON."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        answer = json.loads(match.group(0))
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def score_field(case: dict, text: str, name_tokens: list[str]) -> dict:
    """Return {"correct": bool, "why": str} for a form-field case."""
    answer = parse_field_answer(text)
    if answer is None:
        return {"correct": False, "why": "answer was not valid JSON"}

    action = str(answer.get("action", "")).lower()
    value = str(answer.get("value") or "").strip()

    if case.get("forbid_name") and any(t in value.lower() for t in name_tokens):
        return {"correct": False, "why": f"put the applicant's name in a {case['label']} field"}

    if case["want"] in ("ask", "skip"):
        if action == case["want"] and not value:
            return {"correct": True, "why": ""}
        # Filling a field that should stay empty is the dangerous mistake.
        return {"correct": False, "why": f"wanted {case['want']}, got {action} {value!r}"}

    if action != "fill" or not value:
        return {"correct": False, "why": f"wanted fill, got {action}"}

    want, rule = case["value"], case["match"]
    if rule == "equals":
        ok = _clean(value) == _clean(want)
    elif rule == "contains":
        ok = _clean(want) in _clean(value)
    elif rule == "digits":
        ok = _digits(value) == _digits(want)
    elif rule == "number_only":
        ok = not re.search(r"[A-Za-z]", value) and _digits(value) == _digits(want)
    else:
        raise ValueError(f"unknown match rule: {rule}")
    return {"correct": ok, "why": "" if ok else f"got {value!r}, wanted {want!r}"}


def find_invented_facts(text: str, allowed_numbers: list[str], allowed_orgs: list[str]) -> list[str]:
    """List numbers and company names that are not in the applicant's profile.

    This can raise false alarms, so a flagged answer should be read by a person.
    It is meant to catch inventions, not to prove an answer is perfect.
    """
    flags = []
    allowed = {n.replace(",", "") for n in allowed_numbers}
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""):
        clean = token.replace(",", "")
        if clean not in allowed:
            flags.append(f"number {token} is not in the profile")
    for org in re.findall(rf"((?:[A-Z][\w&.-]*\s+){{1,4}}{ORG_SUFFIX})\b", text or ""):
        if not any(known in org.lower() for known in allowed_orgs):
            flags.append(f"organisation {org.strip()!r} is not in the profile")
    return flags


def score_written(case: dict, text: str, allowed_numbers: list[str], allowed_orgs: list[str]) -> dict:
    """Return {"correct", "why", "invented"} for a written-answer case."""
    if not (text or "").strip():
        return {"correct": False, "why": "empty answer", "invented": []}
    invented = find_invented_facts(text, allowed_numbers, allowed_orgs)
    return {"correct": not invented, "why": "; ".join(invented), "invented": invented}
