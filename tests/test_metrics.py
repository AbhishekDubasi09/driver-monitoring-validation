"""Tests for the metric code, using the session saved in results/."""
import json
import os
import shutil
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "driver_monitoring"))

from session_metrics import compute, runs  # noqa: E402


def test_runs_finds_contiguous_true_stretches():
    t = np.arange(10) * 0.1
    mask = np.array([0, 1, 1, 0, 0, 1, 1, 1, 0, 0], bool)
    assert runs(mask, t) == [(pytest.approx(0.1), pytest.approx(0.2)),
                             (pytest.approx(0.5), pytest.approx(0.3))]


def test_runs_closes_a_stretch_that_reaches_the_end():
    t = np.arange(5) * 0.5
    mask = np.array([0, 0, 1, 1, 1], bool)
    assert runs(mask, t) == [(pytest.approx(1.0), pytest.approx(1.0))]


def test_runs_with_nothing_true_is_empty():
    assert runs(np.zeros(6, bool), np.arange(6) * 0.1) == []


@pytest.fixture(scope="module")
def recomputed(tmp_path_factory):
    # compute() writes session_metrics.json next to its inputs, so work on a copy
    work = tmp_path_factory.mktemp("session")
    for name in ("live_measurements.csv", "simulator_ground_truth.csv", "live_summary.json"):
        shutil.copy(os.path.join(ROOT, "results", name), work / name)
    _, result = compute(str(work))
    return result


@pytest.fixture(scope="module")
def saved():
    with open(os.path.join(ROOT, "results", "session_metrics.json")) as f:
        return json.load(f)


def test_regression_gaze_yaw(recomputed, saved):
    for key in ("n", "mae_deg", "rmse_deg", "r"):
        assert recomputed["gaze_yaw"][key] == pytest.approx(saved["gaze_yaw"][key])


def test_regression_zone_accuracy(recomputed, saved):
    assert recomputed["zone_accuracy"]["accuracy"] == pytest.approx(saved["zone_accuracy"]["accuracy"])


def test_regression_hazard_reactions(recomputed, saved):
    for name in ("HAZARD_ONSET_1", "HAZARD_ONSET_2"):
        assert recomputed["hazards"][name]["measured_live_s"] == pytest.approx(saved["hazards"][name]["measured_live_s"])
        assert recomputed["hazards"][name]["true_gaze_arrival_s"] == pytest.approx(saved["hazards"][name]["true_gaze_arrival_s"])


def test_regression_hands_and_blinks(recomputed, saved):
    assert recomputed["hands"]["display_touch_matched"] == saved["hands"]["display_touch_matched"]
    assert recomputed["hands"]["frames_both_on_wheel_pct"] == pytest.approx(saved["hands"]["frames_both_on_wheel_pct"])
    assert recomputed["blinks"]["detected"] == saved["blinks"]["detected"]


def test_gaze_error_stays_within_a_loose_bound(recomputed):
    # guards against a silent change in the metric code, not a claim about real drivers
    assert recomputed["gaze_yaw"]["mae_deg"] < 2.0
    assert recomputed["zone_accuracy"]["accuracy"] > 0.95
