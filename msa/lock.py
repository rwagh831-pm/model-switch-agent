"""Locks the rules and test set before any run.

A SHA-256 fingerprint changes if even one character changes. If the rules are
edited after locking, comparisons refuse to run. On its own this only stops
accidental changes. Committing the lock file to git before running is what
gives other people evidence of when the rules were set.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED_FILES = ["decision_rules.json", "testset/cases.json", "testset/candidate.md"]
LOCK_PATH = ROOT / "results" / "lock.json"


def fingerprints() -> dict:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in LOCKED_FILES}


def create_lock() -> dict:
    if LOCK_PATH.exists():
        raise RuntimeError(f"A lock already exists at {LOCK_PATH}. Delete it deliberately to start a new test.")
    LOCK_PATH.parent.mkdir(exist_ok=True)
    data = {"locked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprints": fingerprints()}
    LOCK_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def verify_lock() -> dict:
    """Return the lock, or raise if it is missing or the files have changed."""
    if not LOCK_PATH.exists():
        raise RuntimeError("Nothing is locked yet. Run: python run.py lock")
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    changed = [n for n, h in fingerprints().items() if data["fingerprints"].get(n) != h]
    if changed:
        raise RuntimeError(f"Locked files changed after locking: {', '.join(changed)}")
    return data
