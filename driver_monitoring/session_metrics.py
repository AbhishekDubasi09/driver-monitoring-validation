"""Post-session metrics: joins the live measurements with the simulator ground truth (validation only) and derives the study numbers."""
import json, os
import numpy as np, pandas as pd

OUT = os.environ.get("DRIVER_MONITORING_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
OFF_ROAD = {"left_mirror", "passenger"}
PHASES = {"calibration": (0, 12), "baseline driving": (12, 22), "hazard 1 window": (22, 27), "conversation": (27.5, 48.5), "hazard 2 window": (46, 51), "recovery": (51, 58)}


def load(out=OUT):
    m = pd.read_csv(os.path.join(out, "live_measurements.csv")); g = pd.read_csv(os.path.join(out, "simulator_ground_truth.csv"))
    s = json.load(open(os.path.join(out, "live_summary.json")))
    df = m.merge(g, left_on="frame", right_on="f", suffixes=("", "_gt"))
    df["gt_gaze"] = df.head_yaw + df.eye_yaw
    return df, g, s


def runs(mask, t):
    """contiguous True runs -> [(t0, dur)]"""
    out = []; start = None
    for i, (mk, tt) in enumerate(zip(mask, t)):
        if mk and start is None: start = tt
        if (not mk) and start is not None: out.append((start, tt - start)); start = None
    if start is not None: out.append((start, t[-1] - start))
    return out


def compute(out=OUT):
    df, g, s = load(out)
    R = {}
    meas = df[df.cal == 0].copy()
    # ---------- gaze-yaw validation ----------
    v = meas[(meas.face == 1) & (meas.closed == 0)]
    err = v.est_yaw - v.gt_gaze
    R["gaze_yaw"] = dict(n=int(len(v)), mae_deg=float(err.abs().mean()), rmse_deg=float(np.sqrt((err ** 2).mean())), bias_deg=float(err.mean()),
                         r=float(np.corrcoef(v.est_yaw, v.gt_gaze)[0, 1]), p95_abs_deg=float(err.abs().quantile(0.95)))
    # ---------- zone accuracy (exclude 0.35 s after each intent change and closed-eye frames) ----------
    lab = df.label.values; tt = df.t.values
    change = np.r_[0, np.where(lab[1:] != lab[:-1])[0] + 1]; settle = np.zeros(len(df), bool)
    for c in change: settle |= (tt >= tt[c]) & (tt < tt[c] + 0.5)
    z = df[(df.cal == 0) & (~settle) & (df.closed == 0) & (df.zone != "n/a")]
    zl = df.loc[z.index, "label"]
    R["zone_accuracy"] = dict(n=int(len(z)), accuracy=float((z.zone == zl).mean()),
                              per_class={k: float((z.zone[zl == k] == k).mean()) for k in sorted(zl.unique())},
                              confusion=pd.crosstab(zl, z.zone).to_dict())
    # ---------- hazard reactions ----------
    ev = {k: float(t) for t, k in s["events"]}
    cen = s["calibration"]["centroids_deg"]
    thr = 0.5 * (cen["road"] + cen["hazard_right"]); thr_hi = 0.5 * (cen["hazard_right"] + cen["passenger"])
    H = {}
    for i, (name, lat) in enumerate((("HAZARD_ONSET_1", 0.45), ("HAZARD_ONSET_2", 1.05))):
        te = ev.get(name)
        if te is None: continue
        after = df[(df.t >= te) & (df.t < te + 4.0)]
        band = (after.gt_gaze >= thr) & (after.gt_gaze <= thr_hi)          # true gaze inside the hazard-zone band
        true_arr = after[band].t.min() if band.any() else np.nan
        # gaze direction before onset (what the driver was doing when the hazard appeared)
        pre = df[(df.t > te - 1.0) & (df.t < te)]
        pre_lab = pre.label.mode().iloc[0] if len(pre) else "?"
        win = df[(df.t >= te) & (df.t < te + 9.0)]
        corr = win[(win.ped == 1) & ((win.ped_x - 2.0).abs() < 1.9)]           # pedestrian inside the car's lane corridor
        gap_min = float(corr.ped_gap.min()) if len(corr) else float("nan"); v0 = float(df[(df.t < te) & (df.t > te - 1)].speed.mean())
        brake_t = win[win.speed < v0 - 0.3].t.min() if (win.speed < v0 - 0.3).any() else np.nan
        stop_t = win[win.speed < 0.3].t.min() if (win.speed < 0.3).any() else np.nan
        H[name] = dict(onset_s=te, scripted_latency_s=lat, true_gaze_arrival_s=float(true_arr - te) if not np.isnan(true_arr) else None,
                       measured_live_s=s["reaction_time_s"].get(name), pre_onset_gaze=pre_lab,
                       time_to_brake_s=float(brake_t - te) if not np.isnan(brake_t) else None, min_gap_m=gap_min, speed_at_onset_ms=v0,
                       stopped_after_s=float(stop_t - te) if not np.isnan(stop_t) else None)
        if H[name]["measured_live_s"] is not None and H[name]["true_gaze_arrival_s"] is not None:
            H[name]["measurement_error_s"] = H[name]["measured_live_s"] - H[name]["true_gaze_arrival_s"]
    R["hazards"] = H; R["zone_threshold_deg"] = float(thr)
    # ---------- phase table ----------
    dt = np.median(np.diff(df.t.values))
    rows = []
    for name, (a, b) in PHASES.items():
        w = df[(df.t >= a) & (df.t < b)]
        if name == "calibration" or len(w) < 5: continue
        d_ = np.r_[np.diff(w.t.values), dt]
        off = (w.zone.isin(OFF_ROAD)).values
        gl = runs(off, w.t.values)
        blinks = int(((w.closed.diff() == 1)).sum())
        rows.append(dict(phase=name, start=a, end=b, dur=float(b - a), off_road_pct=float((d_ * off).sum() / d_.sum() * 100),
                         n_glances=len(gl), longest_glance_s=float(max([d for _, d in gl] + [0])), glances_over_2s=int(sum(d > 2 for _, d in gl)),
                         blink_rate_per_min=float(blinks / (b - a) * 60), perclos_pct=float((d_ * w.closed.values).sum() / d_.sum() * 100),
                         speaking_pct=float((d_ * w.speaking.values).sum() / d_.sum() * 100), both_hands_pct=float((d_ * (w.hands_on_wheel == 2).values).sum() / d_.sum() * 100),
                         steer_sd_deg=float(w.steer.std()), speed_mean_ms=float(w.speed.mean())))
    R["phases"] = rows
    # ---------- blink validation: GT peaks vs detected closures ----------
    gt_blinks = []
    last = -9
    for t_, b_ in zip(df.t, df.blink):
        if b_ > 0.6 and t_ - last > 0.15: gt_blinks.append(t_)
        if b_ > 0.6: last = t_
    det = df.t[(df.closed.diff() == 1)].values
    tp = sum(any(abs(d - g_) < 0.3 for d in det) for g_ in gt_blinks)
    R["blinks"] = dict(gt=len(gt_blinks), detected=int(len(det)), recall=float(tp / max(1, len(gt_blinks))), precision=float(sum(any(abs(d - g_) < 0.3 for g_ in gt_blinks) for d in det) / max(1, len(det))))
    # ---------- speech validation (GT = mouth actually moving in the simulator within a 1 s window) ----------
    gt_speak = (df.jaw_gt.rolling(30, min_periods=1, center=True).max() > 0.08).astype(int)
    pred = df.speaking.astype(int); m_ = df.cal == 0
    tp_ = int(((pred == 1) & (gt_speak == 1) & m_).sum()); fp_ = int(((pred == 1) & (gt_speak == 0) & m_).sum()); fn_ = int(((pred == 0) & (gt_speak == 1) & m_).sum()); tn_ = int(((pred == 0) & (gt_speak == 0) & m_).sum())
    R["speech"] = dict(tp=tp_, fp=fp_, fn=fn_, tn=tn_, accuracy=float((tp_ + tn_) / max(1, tp_ + fp_ + fn_ + tn_)), precision=float(tp_ / max(1, tp_ + fp_)), recall=float(tp_ / max(1, tp_ + fn_)))
    # ---------- hands (wheel contact = OpenCV skin regions; display touch = skin in the display region; MediaPipe landmarks reported separately) ----------
    def episodes(mask, t, min_frames=3):
        out = []; start = None; n = 0
        for m_, tt in zip(mask, t):
            if m_:
                n += 1
                if start is None: start = tt
            else:
                if start is not None and n >= min_frames: out.append((start, tt - start))
                start = None; n = 0
        if start is not None and n >= min_frames: out.append((start, t[-1] - start))
        return out
    det_dash = episodes((df.hand_dash == 1).values, df.t.values)
    true_dash = episodes((df.reach > 0.5).values, df.t.values)
    matched = sum(any(abs(d0 - g0) < 2.5 for d0, _ in det_dash) for g0, _ in true_dash)
    R["hands"] = dict(frames_both_on_wheel_pct=float((df.hands_on_wheel == 2).mean() * 100), frames_one_hand_pct=float((df.hands_on_wheel == 1).mean() * 100),
                      frames_no_hand_pct=float((df.hands_on_wheel == 0).mean() * 100), longest_gap_s=float(max([d for _, d in runs((df.hands_on_wheel < 2).values, df.t.values)] + [0])),
                      one_hand_while_reaching_pct=float((df[df.reach > 0.5].hands_on_wheel == 1).mean() * 100) if (df.reach > 0.5).any() else None,
                      display_touch_episodes_detected=len(det_dash), display_touch_episodes_true=len(true_dash), display_touch_matched=int(matched),
                      mediapipe_hand_detected_pct=float((df.n_hands > 0).mean() * 100))
    # ---------- pipeline ----------
    dur = float(df.t.max() - df.t.min())
    R["pipeline"] = dict(frames=int(len(df)), duration_s=dur, processed_fps=float(len(df) / dur), face_detected_pct=float(df.face.mean() * 100),
                         latency_ms_median=float(df.latency_ms.median()), latency_ms_p95=float(df.latency_ms.quantile(0.95)), proc_ms_median=float(df.proc_ms.median()), proc_ms_p95=float(df.proc_ms.quantile(0.95)),
                         hand_detector_runs=s.get("hand_detector_runs"), calibration=s["calibration"])
    json.dump(R, open(os.path.join(out, "session_metrics.json"), "w"), indent=2, default=float)
    return df, R


if __name__ == "__main__":
    df, R = compute()
    print(json.dumps(R, indent=1, default=float)[:6000])
