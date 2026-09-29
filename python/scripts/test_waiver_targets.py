"""Self-check for waiver_targets.py's INSURANCE/STARTER classification."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from waiver_targets import classify_candidate  # noqa: E402

MY_RB = {"name": "My Guy", "team": "DAL", "position": "RB", "depth_chart_order": 1}
MY_WR = {"name": "My Wideout", "team": "SF", "position": "WR", "depth_chart_order": 1}


def test_handcuff_is_insurance() -> None:
    # depth_chart_order 2 on their own team also reads as a near-lead STARTER
    # in its own right -- both tags firing together is correct here.
    candidate = {"team": "DAL", "position": "RB", "depth_chart_order": 3}
    tag, reason = classify_candidate(candidate, [MY_RB, MY_WR], {}, week=None)
    assert tag == "INSURANCE"
    assert "My Guy" in reason


def test_bye_overlap_is_insurance() -> None:
    candidate = {"team": "NYG", "position": "RB", "depth_chart_order": 3}
    tag, reason = classify_candidate(candidate, [MY_RB, MY_WR], {"DAL": "7"}, week=7)
    assert tag == "INSURANCE"
    assert "bye" in reason


def test_bye_only_fires_within_window() -> None:
    candidate = {"team": "NYG", "position": "RB", "depth_chart_order": 3}
    tag, _ = classify_candidate(candidate, [MY_RB, MY_WR], {"DAL": "7"}, week=3)
    assert tag == ""


def test_low_depth_order_is_starter() -> None:
    candidate = {"team": "NYG", "position": "RB", "depth_chart_order": 1}
    tag, reason = classify_candidate(candidate, [MY_RB, MY_WR], {}, week=None)
    assert tag == "STARTER"
    assert "depth chart #1" in reason


def test_handcuff_and_starter_can_both_fire() -> None:
    candidate = {"team": "SF", "position": "WR", "depth_chart_order": 2}
    tag, _ = classify_candidate(candidate, [MY_RB, MY_WR], {}, week=None)
    assert tag == "INSURANCE+STARTER"  # backs up MY_WR (depth 1) and is a depth-2 starter in own right


def test_no_signal_is_blank() -> None:
    candidate = {"team": "KC", "position": "TE", "depth_chart_order": 3}
    tag, reason = classify_candidate(candidate, [MY_RB, MY_WR], {}, week=None)
    assert tag == ""
    assert reason == ""


if __name__ == "__main__":
    test_handcuff_is_insurance()
    test_bye_overlap_is_insurance()
    test_bye_only_fires_within_window()
    test_low_depth_order_is_starter()
    test_handcuff_and_starter_can_both_fire()
    test_no_signal_is_blank()
    print("ok")
