"""Turns two score sheets into SWITCH, STAY or TEST_MORE.

Plain code with rules locked before the run. The AI never decides this step.
"""

from __future__ import annotations


def decide(current: dict, candidate: dict, rules: dict) -> dict:
    """Apply the locked rules. Checks run in order, so safety failures win."""
    limit = rules["max_error_rate_pct"]
    for label, sheet in (("current", current), ("candidate", candidate)):
        if sheet["error_rate_pct"] > limit:
            return _result("TEST_MORE", f"{label} model failed on {sheet['error_rate_pct']}% of calls (limit {limit}%)")
    if current["cost_usd"] is None or candidate["cost_usd"] is None:
        return _result("TEST_MORE", "a model has no known price, so cost cannot be compared")

    if candidate["invented_facts"] > rules["max_invented_facts"]:
        return _result("STAY", f"candidate invented {candidate['invented_facts']} facts "
                               f"(limit {rules['max_invented_facts']})")
    extra_wrong = candidate["wrong"] - current["wrong"]
    if extra_wrong > rules["max_extra_wrong_answers"]:
        return _result("STAY", f"candidate got {extra_wrong} more answers wrong")

    ratio_limit = rules.get("max_slowdown_ratio")
    old_speed, new_speed = current.get("median_seconds"), candidate.get("median_seconds")
    if ratio_limit and old_speed and new_speed and new_speed > old_speed * ratio_limit:
        return _result("STAY", f"candidate is {new_speed / old_speed:.1f} times slower (limit {ratio_limit})")

    now, new = current["cost_usd"], candidate["cost_usd"]
    # If the current model is free, a paid candidate has no saving to offer.
    saving_pct = 100.0 if now == new == 0 else ((now - new) / now * 100 if now else -100.0)

    if candidate["correct"] > current["correct"]:
        allowed = rules["max_cost_increase_pct_for_quality_gain"]
        if -saving_pct <= allowed:
            return _result("SWITCH", f"{candidate['correct'] - current['correct']} more correct, "
                                     f"cost change {-saving_pct:+.0f}%")
        return _result("STAY", f"better quality, but cost rises {-saving_pct:.0f}% (limit {allowed}%)")

    if candidate["correct"] == current["correct"] and saving_pct >= rules["min_cost_saving_pct"] and now > 0:
        return _result("SWITCH", f"same score and {saving_pct:.0f}% cheaper")

    return _result("STAY", "no improvement large enough to justify switching")


def _result(verdict: str, reason: str) -> dict:
    return {"verdict": verdict, "reason": reason}
