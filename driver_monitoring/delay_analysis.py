"""Where does the measured delay come from, and how well are glance and reach timings recovered?

Works on a saved session (live_measurements.csv, simulator_ground_truth.csv, live_summary.json) and needs no
simulator, camera or model files.

Three questions, each answered against the simulator's ground truth:

1. Reaction time. The simulator knows the frame at which the driver's gaze really arrives on the hazard side.
   The pipeline reports a later time. How much of the gap comes from the gaze estimate itself, from the
   three-frame median filter, and from the two-frame debounce on the zone?
2. Glances. Are the durations of looks away from the road recovered, and does a threshold near the true duration
   (two seconds is a common one) classify the glances the same way as the ground truth does?
3. Reaches. How late are the start and the end of a reach to the display detected?
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_metrics import OFF_ROAD, OUT, load, runs  # noqa: E402

GLANCE_THRESHOLD_S = 2.0


def first_time(mask, t, after):
    """First time at or after `after` where mask is true, or nan."""
    sel = (t >= after) & mask
    return float(t[sel].min()) if sel.any() else float("nan")


def reaction_breakdown(df, summary):
    """Stepwise delay of the reaction time: true gaze -> raw estimate -> median filter -> debounced zone."""
    cen = summary["calibration"]["centroids_deg"]
    lo = 0.5 * (cen["road"] + cen["hazard_right"])
    hi = 0.5 * (cen["hazard_right"] + cen["passenger"])
    t = df.t.values
    in_band = lambda x: (x >= lo) & (x <= hi)  # noqa: E731
    est = df.est_yaw.values
    est_med = pd.Series(est).rolling(3, center=True, min_periods=1).median().values
    out = {}
    for te, name in ((e[0], e[1]) for e in summary["events"]):
        if not name.startswith("HAZARD"):
            continue
        true_t = first_time(in_band(df.gt_gaze.values), t, te)
        raw_t = first_time(in_band(est), t, te)
        med_t = first_time(in_band(est_med), t, te)
        zone_t = first_time((df.zone == "hazard_right").values, t, te)
        out[name] = dict(
            onset_s=te,
            true_arrival_s=true_t - te,
            raw_estimate_s=raw_t - te,
            median_filtered_s=med_t - te,
            debounced_zone_s=zone_t - te,
            error_total_ms=1000 * (zone_t - true_t),
            added_by_estimate_ms=1000 * (raw_t - true_t),
            added_by_median_ms=1000 * (med_t - raw_t),
            added_by_debounce_ms=1000 * (zone_t - med_t),
        )
    return out


def true_zone(df, summary):
    """Zone the true gaze angle falls in, by the same nearest-target rule the pipeline uses."""
    cen = summary["calibration"]["centroids_deg"]
    names = list(cen)
    d = np.abs(df.gt_gaze.values[:, None] - np.array([cen[n] for n in names])[None, :])
    return pd.Series(np.array(names)[d.argmin(axis=1)], index=df.index)


def glance_timing(df, summary):
    """Looks away from the road after calibration: true gaze angle against the measured zone."""
    d = df[df.cal == 0]
    t = d.t.values
    truth = runs(true_zone(d, summary).isin(OFF_ROAD).values, t)
    meas = runs(d.zone.isin(OFF_ROAD).values, t)
    pairs = []
    for t0, dur in truth:
        m = [(s, e) for s, e in meas if abs(s - t0) < 1.5]
        if m:
            s, e = m[0]
            pairs.append(dict(true_start_s=t0, true_duration_s=dur, measured_start_s=s, measured_duration_s=e,
                              start_delay_ms=1000 * (s - t0), duration_error_ms=1000 * (e - dur)))
    over = lambda ds: int(sum(x > GLANCE_THRESHOLD_S for x in ds))  # noqa: E731
    return dict(
        n_true=len(truth), n_measured=len(meas), n_matched=len(pairs), pairs=pairs,
        mean_start_delay_ms=float(np.mean([p["start_delay_ms"] for p in pairs])) if pairs else None,
        mean_duration_error_ms=float(np.mean([p["duration_error_ms"] for p in pairs])) if pairs else None,
        threshold_s=GLANCE_THRESHOLD_S,
        true_within_100ms_of_threshold=int(sum(abs(x - GLANCE_THRESHOLD_S) < 0.1 for _, x in truth)),
        longer_than_threshold_true=over([x for _, x in truth]),
        longer_than_threshold_measured=over([x for _, x in meas]),
        durations_true_s=[round(x, 3) for _, x in truth],
        durations_measured_s=[round(x, 3) for _, x in meas],
    )


def estimate_lag(df, max_lag_s=0.4, step_s=0.005):
    """Time shift of the gaze estimate relative to the true gaze angle that minimises the error.

    A shift that is large compared with the noise points at a constant delay (for example in how frames are
    timestamped) and not at the estimator being noisy.
    """
    ok = ((df.cal == 0) & (df.face == 1) & (df.closed == 0)).values
    t = df.t.values
    est, gt = df.est_yaw.values, df.gt_gaze.values
    lags = np.arange(0.0, max_lag_s + step_s, step_s)
    rmse = []
    for lag in lags:
        shifted = np.interp(t - lag, t, gt)          # true gaze as it was `lag` seconds earlier
        valid = ok & (t - lag >= t[0])
        rmse.append(float(np.sqrt(np.mean((est[valid] - shifted[valid]) ** 2))))
    best = int(np.argmin(rmse))
    return dict(best_lag_ms=float(1000 * lags[best]), rmse_at_best_deg=rmse[best], rmse_at_zero_deg=rmse[0],
                lags_ms=[float(1000 * x) for x in lags], rmse_deg=rmse)


def reach_timing(df):
    """Reaches to the display: detected (skin in the display region) against the simulator's reach signal."""
    def episodes(mask, t, min_frames=3):
        out, start, n = [], None, 0
        prev = t[0]
        for m, tt in zip(mask, t):
            if m:
                n += 1
                start = tt if start is None else start
            else:
                if start is not None and n >= min_frames:
                    out.append((start, prev))
                start, n = None, 0
            prev = tt
        if start is not None and n >= min_frames:
            out.append((start, t[-1]))
        return out

    t = df.t.values
    det = episodes((df.hand_dash == 1).values, t)
    tru = episodes((df.reach > 0.5).values, t)
    rows = []
    for a, b in tru:
        m = [(s, e) for s, e in det if abs(s - a) < 2.5]
        if m:
            s, e = m[0]
            rows.append(dict(true_start_s=a, true_end_s=b, detected_start_s=s, detected_end_s=e,
                             start_delay_ms=1000 * (s - a), end_delay_ms=1000 * (e - b)))
    return dict(n_true=len(tru), n_detected=len(det), n_matched=len(rows), episodes=rows)


def analyse(out=OUT):
    df, _, summary = load(out)
    return dict(reaction=reaction_breakdown(df, summary), glances=glance_timing(df, summary),
                lag=estimate_lag(df), reaches=reach_timing(df),
                capture_to_analysis_ms=dict(median=summary["median_latency_ms"], p95=summary["p95_latency_ms"]))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    result = analyse(out)
    with open(os.path.join(out, "delay_analysis.json"), "w") as f:
        json.dump(result, f, indent=2, default=float)
    print(json.dumps(result, indent=1, default=float)[:5000])
