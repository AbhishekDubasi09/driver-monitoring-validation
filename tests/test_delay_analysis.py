"""Tests for the delay analysis, run on the session saved in results/."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "driver_monitoring"))

from delay_analysis import analyse  # noqa: E402

RESULTS = os.path.join(ROOT, "results")


@pytest.fixture(scope="module")
def result():
    return analyse(RESULTS)


@pytest.fixture(scope="module")
def summary():
    with open(os.path.join(RESULTS, "live_summary.json")) as f:
        return json.load(f)


def test_reported_reaction_time_is_the_raw_estimate_crossing(result, summary):
    # The README relies on this: the reported number does not include the median filter or the zone debounce.
    for name, r in result["reaction"].items():
        assert r["raw_estimate_s"] == pytest.approx(summary["reaction_time_s"][name], abs=1e-6)


def test_estimate_arrives_after_the_true_gaze(result):
    for r in result["reaction"].values():
        assert 0 < r["added_by_estimate_ms"] < 300
        assert r["added_by_median_ms"] >= 0
        assert r["added_by_debounce_ms"] >= 0


def test_the_estimate_has_a_constant_delay_of_about_one_frame(result):
    lag = result["lag"]
    assert 20 <= lag["best_lag_ms"] <= 120
    assert lag["rmse_at_best_deg"] < 0.7 * lag["rmse_at_zero_deg"]


def test_every_true_glance_is_matched_and_starts_late(result):
    g = result["glances"]
    assert g["n_true"] == g["n_measured"] == g["n_matched"] == 6
    assert 50 < g["mean_start_delay_ms"] < 300
    assert abs(g["mean_duration_error_ms"]) < 100


def test_glance_durations_sit_close_to_a_two_second_threshold(result):
    # why a duration threshold near two seconds is risky at this timing precision
    assert result["glances"]["true_within_100ms_of_threshold"] >= 2


def test_reaches_are_found_within_a_tenth_of_a_second(result):
    reaches = result["reaches"]
    assert reaches["n_true"] == reaches["n_matched"] == 2
    for e in reaches["episodes"]:
        assert abs(e["start_delay_ms"]) < 150 and abs(e["end_delay_ms"]) < 150
