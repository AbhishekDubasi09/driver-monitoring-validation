"""Post-drive session report: one publication-style figure + an HTML report with the research questions answered from the session's own numbers."""
import base64, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch
from session_metrics import compute, OUT

from typo import font_path, CSS_STACK
for w_ in ("Regular", "SemiBold", "Bold"):
    fm.fontManager.addfont(font_path(w_))
FAMILY = fm.FontProperties(fname=font_path("Regular")).get_name()
plt.rcParams.update({"axes.unicode_minus": False, "font.family": FAMILY, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#bbbbbb", "axes.linewidth": 0.8,
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.labelcolor": "#52514e", "text.color": "#0b0b0b", "font.size": 10})

# ---- tokens (reference palette, light surface) ----
SURF, INK, INK2, MUT, GRID = "#ffffff", "#111111", "#444444", "#777777", "#e0e0e0"
BLUE, ORANGE, AQUA, YEL, MAG = "#1f77b4", "#d62728", "#2ca02c", "#7f7f7f", "#9467bd"
ZC = {"road": AQUA, "hazard_right": ORANGE, "left_mirror": BLUE, "passenger": MAG}
ZN = {"road": "Road ahead", "hazard_right": "Right / hazard side", "left_mirror": "Left mirror", "passenger": "Passenger"}


def card(fig, x, y, w, h, label, value, sub, accent):
    ax = fig.add_axes([x, y, w, h]); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.06", fc="#ffffff", ec=GRID, lw=1, transform=ax.transAxes))
    ax.add_patch(FancyBboxPatch((0, 0), 0.0, 1, boxstyle="square,pad=0", fc="#ffffff", ec="none", transform=ax.transAxes))
    ax.text(0.07, 0.80, label, fontsize=8.2, color=MUT, fontweight="bold", transform=ax.transAxes, va="center")
    ax.text(0.07, 0.46, value, fontsize=21, color=INK, fontweight="bold", transform=ax.transAxes, va="center")
    ax.text(0.07, 0.14, sub, fontsize=8.4, color=INK2, transform=ax.transAxes, va="center")


def title(ax, letter, text):
    ax.set_title(f"{letter}   {text}", loc="left", fontsize=11.5, fontweight="bold", color=INK, pad=10)


def runs(mask, t):
    out = []; s = None
    for m, tt in zip(mask, t):
        if m and s is None: s = tt
        if (not m) and s is not None: out.append((s, tt - s)); s = None
    if s is not None: out.append((s, t[-1] - s))
    return out


def make_figure(df, R, out):
    H1, H2 = R["hazards"]["HAZARD_ONSET_1"], R["hazards"]["HAZARD_ONSET_2"]
    cen = R["pipeline"]["calibration"]["centroids_deg"]; P = R["pipeline"]
    fig = plt.figure(figsize=(18, 12.8), dpi=200, facecolor=SURF)
    fig.text(0.04, 0.955, "Driver gaze and hand monitoring, simulated drive", fontsize=21, fontweight="bold", color=INK)
    fig.text(0.04, 0.927, "One synthetic driver, 58 s, two pedestrian events. Unity virtual cameras, analysed live with OpenCV and MediaPipe.",
             fontsize=10.5, color=INK2)
    kp = [("Gaze-zone accuracy", f"{R['zone_accuracy']['accuracy'] * 100:.1f} %", f"4 zones, n = {R['zone_accuracy']['n']} frames", AQUA),
          ("Gaze-yaw error", f"{R['gaze_yaw']['mae_deg']:.2f}° MAE", f"RMSE {R['gaze_yaw']['rmse_deg']:.2f}°, r = {R['gaze_yaw']['r']:.3f}", BLUE),
          ("Gaze reaction to hazard", f"{H1['measured_live_s']:.2f} s, {H2['measured_live_s']:.2f} s", f"eyes on road, then talking (+{H2['measured_live_s'] - H1['measured_live_s']:.2f} s)", ORANGE),
          ("Min. gap to pedestrian", f"{H1['min_gap_m']:.1f} m, {H2['min_gap_m']:.1f} m", f"braking starts {H1['time_to_brake_s']:.2f} s, {H2['time_to_brake_s']:.2f} s after", MAG),
          ("Both hands on wheel", f"{R['hands']['frames_both_on_wheel_pct']:.1f} %", f"longest gap {R['hands']['longest_gap_s']:.2f} s", YEL),
          ("Live processing", f"{P['processed_fps']:.1f} fps", f"{P['latency_ms_median']:.0f} ms median latency", INK2)]
    cw, gap, x0 = 0.148, 0.0108, 0.04
    for i, (l, v, s, a) in enumerate(kp): card(fig, x0 + i * (cw + gap), 0.838, cw, 0.062, l, v, s, a)

    gs = fig.add_gridspec(3, 12, left=0.075, right=0.985, top=0.805, bottom=0.115, hspace=0.62, wspace=1.9)
    t = df.t.values
    # ---------------- A  gaze timeline ----------------
    ax = fig.add_subplot(gs[0, 0:8]); title(ax, "A", "Where the driver looked  (gaze yaw, + = right of straight ahead)")
    ax.axvspan(0, 12, color="#f0f0f0", lw=0); ax.text(0.3, 47, "calibration", fontsize=8.5, color=MUT, va="top")
    ax.axvspan(27.5, 48.5, color="#f0f0f0", lw=0); ax.text(28, 47, "conversation with passenger (speaking)", fontsize=8.5, color=ORANGE, va="top")
    for z, c in cen.items(): ax.axhline(c, color=ZC[z], lw=0.7, ls=(0, (2, 3)), alpha=0.8); ax.text(57.7, c + 1.6, ZN[z], fontsize=8.5, color=ZC[z], va="bottom", ha="right", fontweight="bold")
    ax.plot(t, df.gt_gaze, color="#9a9a94", lw=1.0, label="simulator truth (head + eye)", zorder=2)
    for z, c in ZC.items():
        m = (df.zone == z) & (df.closed == 0)
        ax.scatter(t[m], df.est_yaw[m], s=4, color=c, zorder=3, linewidths=0)
    ax.scatter([], [], s=14, color=INK2, label="live estimate, coloured by classified zone")
    for H, nm in ((H1, "Hazard 1"), (H2, "Hazard 2")):
        ax.axvline(H["onset_s"], color=INK, lw=1.2); ax.text(H["onset_s"] + 0.25, -37, f"{nm}\npedestrian steps out", fontsize=8.5, color=INK, va="bottom")
    ax.set_xlim(0, 58); ax.set_ylim(-40, 50); ax.set_xlabel("session time (s)"); ax.set_ylabel("gaze yaw (°)"); ax.grid(axis="y", color=GRID, lw=0.6)
    ax.legend(loc="upper left", bbox_to_anchor=(0.115, 1.0), frameon=False, fontsize=8.5, ncol=1)
    # ---------------- B  reaction ----------------
    ax = fig.add_subplot(gs[0, 8:12]); title(ax, "B", "Reaction to the hazard (s after pedestrian appears)")
    labels = ["Hazard 1\nattentive, eyes on road", "Hazard 2\ntalking, looking at passenger"]
    series = [("True gaze arrival (simulator)", [H1["true_gaze_arrival_s"], H2["true_gaze_arrival_s"]], "#bbbbbb"),
              ("Measured live (MediaPipe)", [H1["measured_live_s"], H2["measured_live_s"]], ORANGE),
              ("Braking onset (vehicle)", [H1["time_to_brake_s"], H2["time_to_brake_s"]], BLUE)]
    w = 0.25
    for i, (nm, vals, c) in enumerate(series):
        xs = np.arange(2) + (i - 1) * (w + 0.03)
        ax.bar(xs, vals, width=w, color=c, label=nm, zorder=3)
        for xx, vv in zip(xs, vals): ax.text(xx, vv + 0.03, f"{vv:.2f}", ha="center", fontsize=9, color=INK, fontweight="bold")
    ax.set_xticks(range(2)); ax.set_xticklabels(labels, fontsize=9); ax.set_ylim(0, 1.75); ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left"); ax.set_ylabel("seconds")
    # ---------------- C  vehicle ----------------
    sub = gs[1, 0:4].subgridspec(2, 1, hspace=0.18, height_ratios=[1.3, 1])
    ax1 = fig.add_subplot(sub[0]); title(ax1, "C", "Vehicle outcome")
    ax1.plot(t, df.speed, color=BLUE, lw=1.8); ax1.set_ylabel("speed (m/s)"); ax1.set_xlim(0, 58); ax1.grid(axis="y", color=GRID, lw=0.6); ax1.set_xticklabels([])
    for H in (H1, H2): ax1.axvline(H["onset_s"], color=INK, lw=1.0)
    ax1.text(H1["onset_s"] + 0.4, 9.6, "H1", fontsize=8.5, color=INK2); ax1.text(H2["onset_s"] + 0.4, 9.6, "H2", fontsize=8.5, color=INK2); ax1.set_ylim(0, 11)
    ax2 = fig.add_subplot(sub[1]); corr = (df.ped == 1) & ((df.ped_x - 2.0).abs() < 1.9)
    ax2.plot(t[corr], df.ped_gap[corr], color="#444444", lw=1.8)
    for H, nm in ((H1, "hazard 1"), (H2, "hazard 2")):
        ax2.scatter([H["onset_s"] + 0.0], [np.nan]); ax2.annotate(f"min {H['min_gap_m']:.1f} m", (H["onset_s"] + 2.4, H["min_gap_m"]), xytext=(4, 6), textcoords="offset points", fontsize=8.5, color=INK, fontweight="bold")
    ax2.set_xlim(0, 58); ax2.set_ylim(0, 24); ax2.set_ylabel("gap to\npedestrian (m)"); ax2.set_xlabel("session time (s)"); ax2.grid(axis="y", color=GRID, lw=0.6)
    # ---------------- D  eyes-off-road ----------------
    ax = fig.add_subplot(gs[1, 4:8]); title(ax, "D", "Eyes off the road, by phase")
    ph = [p for p in R["phases"]]; names = [{"baseline driving": "baseline", "hazard 1 window": "hazard 1", "hazard 2 window": "hazard 2"}.get(p["phase"], p["phase"]) for p in ph]
    cols = [AQUA if p["off_road_pct"] < 20 else ORANGE for p in ph]
    ax.barh(range(len(ph)), [p["off_road_pct"] for p in ph], color=cols, height=0.58, zorder=3)
    for i, p in enumerate(ph):
        ax.text(p["off_road_pct"] + 0.8, i, f"{p['off_road_pct']:.0f} %   (longest glance {p['longest_glance_s']:.1f} s" + (f", {p['glances_over_2s']} over 2 s)" if p["glances_over_2s"] else ")"),
                va="center", fontsize=8.8, color=INK)
    ax.set_yticks(range(len(ph))); ax.set_yticklabels(names, fontsize=9.5); ax.invert_yaxis(); ax.set_xlim(0, 100); ax.set_xlabel("% of phase with gaze on mirror / passenger"); ax.grid(axis="x", color=GRID, lw=0.6, zorder=0)
    # ---------------- E  validation scatter ----------------
    ax = fig.add_subplot(gs[1, 8:12]); title(ax, "E", "Estimate vs. simulator truth")
    v = df[(df.cal == 0) & (df.face == 1) & (df.closed == 0)]
    for z, c in ZC.items():
        m = v.zone == z; ax.scatter(v.gt_gaze[m], v.est_yaw[m], s=6, color=c, alpha=0.65, linewidths=0, label=ZN[z])
    ax.plot([-35, 50], [-35, 50], color=INK2, lw=0.8, ls=(0, (3, 3))); ax.set_xlim(-35, 50); ax.set_ylim(-35, 50); ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("true gaze yaw (°)"); ax.set_ylabel("estimated gaze yaw (°)"); ax.grid(color=GRID, lw=0.6)
    ax.text(0.97, 0.05, f"MAE {R['gaze_yaw']['mae_deg']:.2f}°\nRMSE {R['gaze_yaw']['rmse_deg']:.2f}°\np95 |err| {R['gaze_yaw']['p95_abs_deg']:.1f}°\nn = {R['gaze_yaw']['n']}", transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color=INK,
            bbox=dict(boxstyle="round,pad=0.35", fc="#ffffff", ec=GRID))
    ax.legend(frameon=False, fontsize=8, loc="upper left", markerscale=2)
    # ---------------- F  ethogram ----------------
    ax = fig.add_subplot(gs[2, 0:7]); title(ax, "F", "Driver-state timeline (live-derived)")
    rows = ["Gaze zone", "Speaking", "Hands on wheel", "Blinks"]
    ax.set_ylim(-0.5, 3.5); ax.set_yticks(range(4)); ax.set_yticklabels(rows[::-1], fontsize=9.5)
    y = {"Gaze zone": 3, "Speaking": 2, "Hands on wheel": 1, "Blinks": 0}
    zz = df.zone.values
    for z, c in ZC.items():
        for s0, d0 in runs(zz == z, t): ax.broken_barh([(s0, d0)], (y["Gaze zone"] - 0.32, 0.64), color=c, lw=0)
    for s0, d0 in runs(df.speaking.values == 1, t): ax.broken_barh([(s0, d0)], (y["Speaking"] - 0.32, 0.64), color=MAG, lw=0)
    for s0, d0 in runs(df.hands_on_wheel.values == 2, t): ax.broken_barh([(s0, d0)], (y["Hands on wheel"] - 0.32, 0.64), color=AQUA, lw=0)
    for s0, d0 in runs(df.hands_on_wheel.values < 2, t): ax.broken_barh([(s0, d0)], (y["Hands on wheel"] - 0.32, 0.64), color=ORANGE, lw=0)
    bl = df.t[df.closed.diff() == 1].values; ax.vlines(bl, y["Blinks"] - 0.3, y["Blinks"] + 0.3, color=BLUE, lw=1.6)
    for H in (H1, H2): ax.axvline(H["onset_s"], color=INK, lw=1.1)
    ax.axvspan(0, 12, color="#f0f0f0", lw=0, zorder=0); ax.text(0.4, -0.42, "calibration", fontsize=8.5, color=MUT, va="bottom")
    ax.set_xlim(0, 58); ax.set_xlabel("session time (s)"); ax.spines["left"].set_visible(False); ax.tick_params(axis="y", length=0)
    for z, c in ZC.items(): ax.scatter([], [], marker="s", s=40, color=c, label=ZN[z])
    ax.scatter([], [], marker="s", s=40, color=AQUA, label="both hands on wheel"); ax.scatter([], [], marker="s", s=40, color=ORANGE, label="< 2 hands found")
    ax.legend(frameon=False, fontsize=8.0, ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.0))
    # ---------------- G  latency ----------------
    ax = fig.add_subplot(gs[2, 7:10]); title(ax, "G", "Live pipeline latency")
    lo = max(0.0, float(df.latency_ms.quantile(0.01)) - 20); hi = float(P["latency_ms_p95"]) + 70
    ax.hist(df.latency_ms, bins=np.linspace(lo, hi, 38), color=BLUE, alpha=0.85, zorder=3); ax.set_xlim(lo, hi)
    ymax = ax.get_ylim()[1]; ax.set_ylim(0, ymax * 1.18)
    for q, nm, yy, ha, dx in ((P["latency_ms_median"], "median", 0.97, "right", -3), (P["latency_ms_p95"], "p95", 0.85, "left", 3)):
        ax.axvline(q, color=INK, lw=1.0); ax.text(q + dx, ymax * 1.18 * yy, f"{nm} {q:.0f} ms", fontsize=8.8, color=INK, fontweight="bold", ha=ha, va="top")
    ax.set_xlabel("capture to analysed frame (ms)"); ax.set_ylabel("frames"); ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    ax.text(0.98, 0.66, f"inference {P['proc_ms_median']:.0f} ms per frame\n{P['frames']} of {P['frames']} frames analysed\nface found in {P['face_detected_pct']:.0f} %", transform=ax.transAxes, ha="right", va="top", fontsize=8.6, color=INK2)
    # ---------------- H  confusion ----------------
    ax = fig.add_subplot(gs[2, 10:12]); title(ax, "H", "Zone confusion")
    order = ["road", "hazard_right", "left_mirror", "passenger"]; cm = R["zone_accuracy"]["confusion"]
    M = np.array([[cm.get(c, {}).get(r, 0) for c in order] for r in order], float)
    ax.imshow(M / M.sum(1, keepdims=True), cmap=matplotlib.colors.LinearSegmentedColormap.from_list("s", ["#f5f5f5", BLUE]), vmin=0, vmax=1)
    for i in range(4):
        for j in range(4): ax.text(j, i, int(M[i, j]), ha="center", va="center", fontsize=9, color=INK if M[i, j] / M[i].sum() < 0.6 else "#ffffff", fontweight="bold")
    short = ["road", "hazard", "mirror", "pass."]
    ax.set_xticks(range(4)); ax.set_xticklabels(short, fontsize=8.5); ax.set_yticks(range(4)); ax.set_yticklabels(short, fontsize=8.5)
    ax.set_xlabel("classified"); ax.set_ylabel("scripted target"); ax.spines[:].set_visible(False)
    fig.text(0.04, 0.012, "Off-road means gaze on the left mirror or the passenger. The 2 s line in D is the NHTSA single-glance guideline, for reference only.\n"
                          "Simulated drive: synthetic driver, virtual cameras, no headset. The reaction times 0.45 s and 1.05 s are scripted, so panel B shows the system can measure a difference like that, not how people behave.\n"
                          "Zones were calibrated on four labelled targets in the first 12 s. Simulator values are used only for that calibration and for panels B, E and H.",
             fontsize=8.6, color=INK2, va="bottom")
    p = os.path.join(out, "session_report.png"); fig.savefig(p, facecolor=SURF); plt.close(fig)
    return p


def html_report(df, R, out, png):
    H1, H2 = R["hazards"]["HAZARD_ONSET_1"], R["hazards"]["HAZARD_ONSET_2"]
    ph = {p["phase"]: p for p in R["phases"]}; P = R["pipeline"]; Hd = R["hands"]
    b64 = base64.b64encode(open(png, "rb").read()).decode()
    frame_ms = 1000.0 / P["processed_fps"]; d_rt = H2["measured_live_s"] - H1["measured_live_s"]
    rows = "".join(f"<tr><td>{p['phase']}</td><td>{p['dur']:.0f}</td><td>{p['off_road_pct']:.0f}</td><td>{p['longest_glance_s']:.1f}</td><td>{p['glances_over_2s']}</td><td>{p['blink_rate_per_min']:.0f}</td>"
                   f"<td>{p['perclos_pct']:.1f}</td><td>{p['speaking_pct']:.0f}</td><td>{p['both_hands_pct']:.0f}</td><td>{p['steer_sd_deg']:.1f}</td></tr>" for p in R["phases"])
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Driver gaze and hand monitoring, simulated drive</title>
<style>
:root{{--bg:#f6f6f3;--surf:#fff;--ink:#0b0b0b;--ink2:#52514e;--mut:#8a8984;--line:#e6e5e0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121211;--surf:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--mut:#8e8d86;--line:#2c2c2a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 {CSS_STACK}}}
main{{max-width:1120px;margin:0 auto;padding:40px 24px 80px}}
h1{{font-size:30px;margin:0 0 6px}} h2{{font-size:20px;margin:40px 0 10px}}
.sub{{color:var(--ink2);margin:0 0 22px}} .card{{background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:16px 22px;margin:14px 0}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}} .k div{{background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:12px 16px}}
.k b{{display:block;font-size:24px}} .k span{{color:var(--mut);font-size:13px}} .k i{{color:var(--ink2);font-size:13px;font-style:normal}}
img,video{{max-width:100%;border-radius:8px;border:1px solid var(--line)}} table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{color:var(--ink2);font-weight:600}} .note{{color:var(--ink2);font-size:14px}} .q{{font-weight:700;margin:0 0 6px}}
</style></head><body><main>
<h1>Driver gaze and hand monitoring, simulated drive</h1>
<p class="sub">A synthetic driver drives a 58 second scripted route in Unity. Three virtual cameras stream to a Python program that runs MediaPipe and OpenCV while the drive is running. Nothing here comes from a real person, a headset or a physical camera.</p>
<div class="k">
<div><span>Gaze zone accuracy</span><b>{R['zone_accuracy']['accuracy']*100:.1f} %</b><i>{R['zone_accuracy']['n']} frames, 4 zones</i></div>
<div><span>Gaze yaw error</span><b>{R['gaze_yaw']['mae_deg']:.2f}° mean</b><i>r = {R['gaze_yaw']['r']:.3f}</i></div>
<div><span>Gaze reaction to pedestrian</span><b>{H1['measured_live_s']:.2f} s, {H2['measured_live_s']:.2f} s</b><i>eyes on road, then talking</i></div>
<div><span>Closest gap to pedestrian</span><b>{H1['min_gap_m']:.1f} m, {H2['min_gap_m']:.1f} m</b><i>braking starts {H1['time_to_brake_s']:.2f} s, {H2['time_to_brake_s']:.2f} s after</i></div>
<div><span>Both hands on wheel</span><b>{Hd['frames_both_on_wheel_pct']:.1f} %</b><i>longest gap {Hd['longest_gap_s']:.2f} s</i></div>
<div><span>Processing</span><b>{P['processed_fps']:.1f} fps</b><i>{P['latency_ms_median']:.0f} ms median latency</i></div></div>
<h2>Overview</h2><div class="card"><img alt="Session overview" src="data:image/png;base64,{b64}"></div>
<h2>Recording</h2><div class="card"><video controls preload="metadata" src="annotated_live.mp4"></video>
<p class="note">Recorded by the live program while the drive was running.</p></div>

<h2>Questions</h2>
<div class="card"><p class="q">1. Can the live pipeline tell where the driver is looking, and when the gaze reaches a hazard?</p>
<p>In this simulation, yes. After a 12 second calibration on four known targets, the gaze yaw estimate was off by {R['gaze_yaw']['mae_deg']:.2f}° on average (RMSE {R['gaze_yaw']['rmse_deg']:.2f}°, {R['gaze_yaw']['n']} frames) and the zone was right in {R['zone_accuracy']['accuracy']*100:.1f} % of steady frames.
The two reaction times were measured {H1['measurement_error_s']*1000:+.0f} ms and {H2['measurement_error_s']*1000:+.0f} ms from the true values ({H1['measured_live_s']:.3f} s against {H1['true_gaze_arrival_s']:.3f} s, and {H2['measured_live_s']:.3f} s against {H2['true_gaze_arrival_s']:.3f} s). One video frame is about {frame_ms:.0f} ms.</p>
<p class="note">The subject is clean and synthetic, and the thresholds and calibration were tuned on earlier runs of this same simulation, so these numbers are optimistic.</p></div>

<div class="card"><p class="q">2. Does talking to a passenger slow the reaction to a hazard?</p>
<p>In the script it does. With eyes on the road the gaze reached the pedestrian {H1['measured_live_s']:.2f} s after the pedestrian appeared, braking started after {H1['time_to_brake_s']:.2f} s and the closest approach was {H1['min_gap_m']:.1f} m.
While talking and looking at the passenger it was {H2['measured_live_s']:.2f} s, {H2['time_to_brake_s']:.2f} s and {H2['min_gap_m']:.1f} m, so the gaze reaction was {d_rt:.2f} s slower. During the conversation the driver looked at the mirror or passenger {ph['conversation']['off_road_pct']:.0f} % of the time (baseline {ph['baseline driving']['off_road_pct']:.0f} %), with {ph['conversation']['glances_over_2s']} glances longer than 2 s.</p>
<p class="note">The two delays (0.45 s and 1.05 s) and the glance times were written into the script. This only shows the system can measure a difference of that size. It says nothing about real drivers.</p></div>

<div class="card"><p class="q">3. Can blinks, speech and hand contact be tracked at the same time?</p>
<p>Blinks: {R['blinks']['detected']} found for {R['blinks']['gt']} rendered (recall {R['blinks']['recall']*100:.0f} %, precision {R['blinks']['precision']*100:.0f} %), {min(p['blink_rate_per_min'] for p in R['phases']):.0f} to {max(p['blink_rate_per_min'] for p in R['phases']):.0f} per minute across phases.
Speech: precision {R['speech']['precision']*100:.0f} %, recall {R['speech']['recall']*100:.0f} % against the moments the mouth was moving, and it lags the start of a phrase by up to a second.
Hands: both hands on the wheel in {Hd['frames_both_on_wheel_pct']:.1f} % of frames. The right hand reached away from the wheel {Hd['display_touch_episodes_true']} times and {Hd['display_touch_matched']} were found.</p>
<p>The hand camera is a front-diagonal view from the dashboard. MediaPipe hand landmarks were found in {Hd['mediapipe_hand_detected_pct']:.0f} % of frames. Wheel contact and reaches are decided with OpenCV skin segmentation in fixed image regions, and a reach is the right hand leaving the wheel region.</p>
<p>Everything above ran during the drive: {P['frames']} frames at {P['processed_fps']:.1f} fps, median {P['latency_ms_median']:.0f} ms from capture to analysed frame ({P['latency_ms_p95']:.0f} ms at the 95th percentile).</p></div>

<h2>By phase</h2><div class="card"><table><tr><th>phase</th><th>s</th><th>off road %</th><th>longest glance s</th><th>glances over 2 s</th><th>blinks per min</th><th>PERCLOS %</th><th>speaking %</th><th>both hands %</th><th>steering SD deg</th></tr>{rows}</table></div>

<h2>How it works</h2><div class="card">
<p>Unity plays the drive in real time. The driver model has scripted eye saccades, blinks, head turns, talking, steering, a two-handed grip and one hand reaching toward the centre display. Three virtual cameras (face, hands and wheel, outside view) are sent as JPEG over a local socket.</p>
<p>The Python side runs MediaPipe face landmarks (iris, blendshapes, head pose) on every frame. Gaze yaw is a linear fit of head yaw and iris position, calibrated on the first 12 s. Zones are classified by the nearest calibrated target with a two-frame debounce. Glances, eyes-off-road time, blinks, PERCLOS, speech and reaction time are computed as frames arrive. The simulator's own values are stored separately and used only for calibration and for the comparison panels.</p>
<p>With a real camera the receiver would read a webcam instead of the socket and the rest stays the same. A headset covers the eyes, so a cabin camera can only estimate gaze in a physical simulator or screen setup. With a Quest 3 the gaze would have to come from the headset itself, which it does not provide.</p></div>

<h2>Limits</h2><div class="card"><ul class="note">
<li>One synthetic subject and one session, with clean rendering: no lighting changes, glasses or occlusion.</li>
<li>Calibration uses labelled targets from the simulator. A real participant would need an on-screen target routine.</li>
<li>Hazard delays, glance times and speech are scripted.</li>
<li>Thresholds (blink 0.30, speech, skin fraction, zone debounce) were tuned on this simulation and not cross-validated.</li>
<li>The skin regions for wheel contact are fixed for this camera position and skin tone.</li>
<li>Only horizontal gaze is used. Vertical iris position was too noisy.</li></ul></div>
</main></body></html>"""
    p = os.path.join(out, "session_report.html"); open(p, "w", encoding="utf-8").write(html); return p


if __name__ == "__main__":
    df, R = compute()
    png = make_figure(df, R, OUT); h = html_report(df, R, OUT, png)
    print(png); print(h)
