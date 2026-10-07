"""Figure for the delay analysis: where the reaction-time error comes from, and the best-fit delay."""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from delay_analysis import analyse  # noqa: E402
from session_metrics import OUT, load  # noqa: E402

COL = dict(est="#0072B2", truth="#222222", true_t="#222222", raw="#D55E00", zone="#009E73", band="#E8E8E8")


def make(out=OUT, path="delay_breakdown.png"):
    df, _, summary = load(out)
    res = analyse(out)
    cen = summary["calibration"]["centroids_deg"]
    lo = 0.5 * (cen["road"] + cen["hazard_right"])
    hi = 0.5 * (cen["hazard_right"] + cen["passenger"])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), gridspec_kw=dict(width_ratios=[1, 1, 0.9]))
    for ax, (name, r) in zip(axes[:2], res["reaction"].items()):
        te = r["onset_s"]
        w = df[(df.t > te - 0.6) & (df.t < te + 2.2)]
        ax.axhspan(lo, hi, color=COL["band"], label="hazard-side zone")
        ax.plot(w.t - te, w.gt_gaze, color=COL["truth"], lw=2, label="true gaze (simulator)")
        ax.plot(w.t - te, w.est_yaw, color=COL["est"], lw=1.6, label="estimated gaze")
        ax.axvline(r["true_arrival_s"], color=COL["true_t"], ls="--", lw=1)
        ax.axvline(r["raw_estimate_s"], color=COL["raw"], ls="--", lw=1.4)
        ax.axvline(r["debounced_zone_s"], color=COL["zone"], ls="--", lw=1.4)
        ax.set_title(f"Pedestrian {name[-1]}: true arrival {1000 * r['true_arrival_s']:.0f} ms, reported "
                     f"{1000 * r['raw_estimate_s']:.0f} ms", fontsize=10)
        ax.set_xlabel("time since the pedestrian appeared (s)")
        ax.set_ylabel("horizontal gaze angle (deg)")
        note = (f"estimate +{r['added_by_estimate_ms']:.0f} ms, "
                f"median filter +{r['added_by_median_ms']:.0f} ms,\n"
                f"zone debounce +{r['added_by_debounce_ms']:.0f} ms (zone display only)")
        ax.text(0.02, 0.04, note, transform=ax.transAxes, fontsize=8.5, va="bottom")
    axes[0].legend(fontsize=8, loc="upper left")
    lag = res["lag"]
    ax = axes[2]
    ax.plot(lag["lags_ms"], lag["rmse_deg"], color=COL["est"], lw=2)
    ax.axvline(lag["best_lag_ms"], color=COL["raw"], ls="--", lw=1.4)
    ax.set_xlabel("delay applied to the true gaze (ms)")
    ax.set_ylabel("RMSE of the gaze estimate (deg)")
    ax.set_title(f"Best fit at {lag['best_lag_ms']:.0f} ms: RMSE {lag['rmse_at_zero_deg']:.2f} to "
                 f"{lag['rmse_at_best_deg']:.2f} deg", fontsize=10)
    for a in axes:
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    print(make(out, sys.argv[2] if len(sys.argv) > 2 else "delay_breakdown.png"))
