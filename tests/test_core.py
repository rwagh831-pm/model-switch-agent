"""Offline tests. No API key needed and no cost. Run with: python -m pytest"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from msa import lock, runner, scoring, verdict  # noqa: E402
from msa.agent import assess_release, html_to_text, is_allowed_url, verify_quotes  # noqa: E402

RULES = {"max_invented_facts": 0, "max_extra_wrong_answers": 0, "min_cost_saving_pct": 20,
         "max_cost_increase_pct_for_quality_gain": 50, "max_error_rate_pct": 10, "max_slowdown_ratio": 2.0}


def sheet(correct=25, wrong=5, errors=0, invented=0, cost=1.0, seconds=1.0):
    total = correct + wrong + errors
    return {"correct": correct, "wrong": wrong, "errors": errors, "invented_facts": invented,
            "cost_usd": cost, "error_rate_pct": round(errors / total * 100, 1), "median_seconds": seconds}


# Version 1 bug: real pay figures from the profile were flagged as invented.
def test_profile_numbers_are_allowed_automatically():
    testset, profile = runner.load_testset()
    for number in ("1250000", "1600000", "9000000000", "80000", "4.2"):
        assert number in testset["allowed_numbers"]
    text = "Her current CTC is 1250000 INR and she expects 1600000 INR."
    assert scoring.find_invented_facts(text, testset["allowed_numbers"], testset["allowed_orgs"]) == []


# Version 1 bug: a free model 4.5 times slower was recommended.
def test_much_slower_model_is_not_recommended():
    assert verdict.decide(sheet(29, 1, seconds=1.13), sheet(29, 1, cost=0.0, seconds=5.09), RULES)["verdict"] == "STAY"
    assert verdict.decide(sheet(25, 5, seconds=1.0), sheet(25, 5, cost=0.5, seconds=1.5), RULES)["verdict"] == "SWITCH"


def test_repeated_runs_keep_the_worst_result():
    testset, profile = runner.load_testset()
    result = runner.run_repeated("stub:perfect", testset, profile, repeats=3)
    assert result["correct_each_run"] == [30, 30, 30] and result["repeats"] == 3


# The tests have to be able to catch bad models.
def test_liar_model_scores_badly_and_never_gets_switch():
    testset, profile = runner.load_testset()
    good = runner.run_tests("stub:perfect", testset, profile)
    liar = runner.run_tests("stub:liar", testset, profile)
    assert good["correct"] == good["cases"]
    assert liar["invented_facts"] > 0
    assert verdict.decide(good, liar, RULES)["verdict"] == "STAY"


def test_broken_model_gets_test_more():
    testset, profile = runner.load_testset()
    good = runner.run_tests("stub:perfect", testset, profile)
    broken = runner.run_tests("stub:broken", testset, profile)
    assert broken["errors"] == broken["cases"]
    assert verdict.decide(good, broken, RULES)["verdict"] == "TEST_MORE"


# Verdict rules
@pytest.mark.parametrize("current, candidate, expected", [
    (sheet(25, 5, cost=1.0), sheet(25, 5, cost=0.5), "SWITCH"),     # same score, half the cost
    (sheet(25, 5, cost=1.0), sheet(25, 5, cost=0.9), "STAY"),       # saving too small
    (sheet(25, 5, cost=1.0), sheet(27, 3, cost=1.4), "SWITCH"),     # better, cost within limit
    (sheet(25, 5, cost=1.0), sheet(27, 3, cost=2.0), "STAY"),       # better, but far too costly
    (sheet(25, 5, cost=1.0), sheet(24, 6, cost=0.1), "STAY"),       # cheaper, but more mistakes
    (sheet(25, 5, cost=1.0), sheet(28, 2, invented=1, cost=0.1), "STAY"),  # invention blocks a switch
    (sheet(25, 5, cost=1.0), sheet(25, 0, errors=5, cost=0.1), "TEST_MORE"),  # too many failed calls
    (sheet(25, 5, cost=None), sheet(25, 5, cost=0.1), "TEST_MORE"),  # unknown price
    (sheet(25, 5, cost=0.0), sheet(27, 3, cost=1.0), "STAY"),       # free today, paid candidate
])
def test_verdict_rules(current, candidate, expected):
    assert verdict.decide(current, candidate, RULES)["verdict"] == expected


# Scoring
def field(label="Company", want="fill", match="contains", value="Northwind", **extra):
    return {"id": "x", "kind": "field", "label": label, "want": want, "match": match, "value": value, **extra}


def test_name_in_company_field_is_wrong():
    result = scoring.score_field(field(forbid_name=True), '{"action": "fill", "value": "Meera Joshi"}', ["meera", "joshi"])
    assert not result["correct"]


def test_filling_a_private_field_is_wrong():
    case = {"id": "pan", "kind": "field", "label": "PAN", "want": "ask"}
    assert not scoring.score_field(case, '{"action": "fill", "value": "ABCDE1234F"}', [])["correct"]
    assert scoring.score_field(case, '{"action": "ask", "value": ""}', [])["correct"]


def test_number_only_rejects_words():
    case = field(match="number_only", value="1250000")
    assert not scoring.score_field(case, '{"action": "fill", "value": "12.5 lakh"}', [])["correct"]
    assert scoring.score_field(case, '{"action": "fill", "value": "12,50,000"}', [])["correct"]


def test_invalid_json_is_wrong():
    assert not scoring.score_field(field(), "Northwind", [])["correct"]


def test_invented_facts_are_flagged():
    flags = scoring.find_invented_facts("She led 40 people at Nimbus Solutions Ltd.", ["6"], ["northwind billing"])
    assert len(flags) == 2
    assert scoring.find_invented_facts("She served 120 clinics at Northwind Billing Pvt Ltd.", ["120"], ["northwind billing"]) == []


# Lock
@pytest.fixture
def temp_lock(tmp_path, monkeypatch):
    (tmp_path / "testset").mkdir()
    for name in lock.LOCKED_FILES:
        (tmp_path / name).write_text("original", encoding="utf-8")
    monkeypatch.setattr(lock, "ROOT", tmp_path)
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "results" / "lock.json")
    return tmp_path


def test_lock_detects_changed_rules(temp_lock):
    with pytest.raises(RuntimeError, match="Nothing is locked"):
        lock.verify_lock()
    lock.create_lock()
    lock.verify_lock()
    (temp_lock / "decision_rules.json").write_text("easier rules", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after locking"):
        lock.verify_lock()


def test_lock_cannot_be_silently_replaced(temp_lock):
    lock.create_lock()
    with pytest.raises(RuntimeError, match="already exists"):
        lock.create_lock()


# Agent guards
def test_invented_quote_is_rejected():
    pages = {"u": "The new model costs $1 per million input tokens and is available today."}
    assert verify_quotes(["costs $1 per million input tokens"], pages) == []
    assert verify_quotes(["costs $0.01 per million input tokens"], pages)
    assert verify_quotes(["costs"], pages)  # too short to count as evidence


def test_agent_only_fetches_named_site():
    assert is_allowed_url("https://docs.example.com/a", "example.com")
    assert not is_allowed_url("http://example.com/a", "example.com")
    assert not is_allowed_url("https://example.com.evil.net/a", "example.com")
    assert not is_allowed_url("https://localhost/a", "example.com")


def test_html_to_text_removes_scripts():
    assert html_to_text("<p>Hello</p><script>steal()</script> <b>world</b>") == "Hello world"


def test_non_https_release_url_refused():
    with pytest.raises(ValueError):
        asyncio.run(assess_release("http://example.com", "task"))
