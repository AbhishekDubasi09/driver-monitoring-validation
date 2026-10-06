"""
Live driver-monitoring pipeline (SIMULATED virtual cameras -> OpenCV + MediaPipe, evaluated while the session runs).

  Unity (play mode) --TCP/JPEG--> this process:  face landmarks + iris + hand landmarks (MediaPipe Tasks),
  gaze-zone classification, blink / PERCLOS, glance statistics, speech activity, hands-on-wheel, hazard reaction time,
  a live dashboard window and a recorded annotated video.  Ground truth from the simulator is used ONLY for the
  initial calibration routine (labelled fixation targets) and is stored separately for post-session validation.

Not real eye tracking: the "camera" is a render of a synthetic character on the same PC; no headset is used.
"""
import argparse, collections, json, math, os, socket, struct, threading, time
import cv2, numpy as np, pandas as pd
import mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
    _sw, _sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
except Exception:
    _sw, _sh = 1920, 1080
_vh = min(1080, int((_sh - 250) // 2 * 2)); _vw = min(1920, int(_vh * 16 / 9) // 2 * 2)
VIEW = (_vw, _vh)         # dashboard window size: always fits the visible screen incl. title bar and taskbar
import sys; sys.path.insert(0, HERE)
from typo import font_path
MODELS = os.path.join(HERE, "models")
FPS = 30

# ---- design tokens: neutral greys with a single amber accent (BGR) ----
BG = (26, 26, 26); PANEL = (38, 38, 38); EDGE = (72, 72, 72); INK = (235, 235, 235); MUTED = (160, 160, 160)
LIGHT = (235, 235, 235); MID = (170, 170, 170); DIM = (110, 110, 110)
GREEN = LIGHT; RED = LIGHT; BLUE = MID; PURPLE = DIM; GREY = MID
C_BLUE, C_ORANGE, C_AQUA, C_MAG, C_YEL, C_RED = MID, LIGHT, LIGHT, DIM, MID, LIGHT
ACCENT = LIGHT
ZONE_COL = {"road": (44, 160, 44), "hazard_right": (40, 39, 214), "left_mirror": (180, 119, 31), "passenger": (189, 103, 148), "eyes_closed": MUTED, "n/a": MUTED}   # BGR: green, red, blue, purple
ZONE_TXT = {"road": "Road ahead", "hazard_right": "Right (hazard side)", "left_mirror": "Left mirror", "passenger": "Passenger", "eyes_closed": "Eyes closed", "n/a": "Calibrating"}
OFF_ROAD = {"left_mirror", "passenger"}

R_IRIS, L_IRIS = 468, 473
R_CORN = (33, 133); L_CORN = (362, 263)
R_EYE = [33, 160, 158, 133, 153, 144]; L_EYE = [362, 385, 387, 263, 373, 380]
HAND_CONN = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(17,18),(18,19),(19,20),(0,17)]
DASH_ROI = (515.0, 130.0, 640.0, 300.0)       # centre display region in the hand-camera image (800x450 basis)
SKIN_L = (150, 215, 300, 310); SKIN_R = (400, 200, 515, 300)       # rim regions where the left / right hand rests (rig geometry)
SKIN_LO, SKIN_HI = (3, 40, 90), (24, 200, 255)                       # HSV skin range for this render (OpenCV hue 0-180)
THR_L, THR_R, DASH_THR = 0.20, 0.20, 0.20


def skin_frac(img, roi):
    sc = img.shape[1] / 800.0
    x0, y0, x1, y1 = [int(v * sc) for v in roi]
    m = cv2.inRange(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), SKIN_LO, SKIN_HI)
    return float(m.mean() / 255.0)
       # centre display region in the hand-camera image (800x450 basis)
WHEEL_ELL = (398.0, 214.0, 192.0, 166.0)     # wheel ring in the hand-camera image (800x450 basis)


def font(sz, bold=False):
    return ImageFont.truetype(font_path("Bold" if bold else "Regular"), sz)       # DIN 1451 if installed in ./fonts, otherwise Bahnschrift
F = {k: font(s, b) for k, (s, b) in dict(t=(28, True), h=(16, True), s=(15, False), sb=(16, True), v=(28, True), vs=(21, True), badge=(21, True), tiny=(12, False)).items()}


class Receiver(threading.Thread):
    """Reads the Unity stream; keeps the newest complete frame (3 cameras); logs ground truth + events for EVERY frame."""
    def __init__(self, port, out):
        super().__init__(daemon=True)
        self.port, self.out = port, out
        self.lock = threading.Lock(); self.cur = {}; self.ready = None
        self.ended = False; self.connected = False; self.n_recv = 0; self.n_dropped = 0
        self.gt_rows = []; self.events = []; self.writers = {}; self.written = {}
        self.t_first = None

    def _recv(self, conn, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk: raise ConnectionError
            buf += chunk
        return bytes(buf)

    def _raw(self, cam, img, t):
        if cam not in (0, 1): return
        if cam not in self.writers:
            h, w = img.shape[:2]
            self.writers[cam] = cv2.VideoWriter(os.path.join(self.out, f"raw_cam{cam}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h)); self.written[cam] = -1
        target = int(round(t * FPS))
        while self.written[cam] < target:
            self.writers[cam].write(img); self.written[cam] += 1

    def run(self):
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.port)); srv.listen(1)
        conn, _ = srv.accept(); conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1); self.connected = True
        try:
            while True:
                hl, jl = struct.unpack("<ii", self._recv(conn, 8))
                hdr = json.loads(self._recv(conn, hl)); jpg = self._recv(conn, jl) if jl else b""
                if hdr.get("end"): self.ended = True; break
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                f, cam = hdr["f"], hdr["cam"]; self.n_recv += 1
                self._raw(cam, img, hdr["t"])
                if cam == 0:
                    g = dict(hdr["gt"]); g.update(f=f, t=hdr["t"], unix=hdr["unix"]); self.gt_rows.append(g)
                    if g["evt"]: self.events.append((hdr["t"], g["evt"]))
                d = self.cur.setdefault(f, {"hdr": {}, "img": {}}); d["hdr"][cam] = hdr; d["img"][cam] = img
                if len(d["img"]) == 3:
                    with self.lock:
                        if self.ready is not None: self.n_dropped += 1
                        self.ready = (f, d)
                    for k in [k for k in self.cur if k <= f]: self.cur.pop(k, None)
        except (ConnectionError, OSError):
            self.ended = True
        for w in self.writers.values(): w.release()


class Analyzer:
    """Online statistics. Calibration: regress total gaze yaw from (MediaPipe head yaw, iris ratio) on labelled targets."""
    def __init__(self):
        self.cal_x, self.cal_y, self.cal_lab = [], [], []
        self.model = None; self.centroids = {}; self.ear_base = None
        self.est_hist = collections.deque(maxlen=3)
        self.zone = "n/a"; self.zone_raw_hist = collections.deque(maxlen=2)
        self.last_est = 0.0
        self.t_prev = None; self.t_meas0 = None
        self.time_in = collections.defaultdict(float)
        self.glance_open = None; self.glances = []             # (zone, t0, dur)
        self.blink_state = False; self.blinks = []; self.closed_hist = collections.deque()
        self.jaw_hist = collections.deque(); self.speech_thr = None; self.jaw_base = []
        self.speaking = False; self.t_speak = 0.0
        self.hands_hist = []; self.hand_frames = 0; self.both_frames = 0
        self.events = []; self.rt = {}; self.haz_run = {}
        self.cal_done = False; self.raw_prev = None; self.raw_run_start = 0.0; self.dash_events = 0

    # ---- helpers ----
    def feed_cal(self, x, y, lab):
        self.cal_x.append(x); self.cal_y.append(y); self.cal_lab.append(lab)

    def finish_cal(self):
        X = np.array(self.cal_x); y = np.array(self.cal_y); lab = np.array(self.cal_lab)
        A = np.c_[X, np.ones(len(X))]
        self.model, *_ = np.linalg.lstsq(A, y, rcond=None)
        est = A @ self.model
        self.centroids = {l: float(np.median(est[lab == l])) for l in np.unique(lab)}
        self.cal_rmse = float(np.sqrt(np.mean((est - y) ** 2)))
        self.cal_done = True

    def predict(self, x):
        return float(np.r_[x, 1.0] @ self.model)

    def classify(self, est):
        return min(self.centroids, key=lambda k: abs(self.centroids[k] - est))


def live_features(face_res, hand_res, shape_face, shape_hand, img_h=None):
    h, w = shape_face[:2]; row = {"face": 0, "n_hands": 0, "hands_on_wheel": 0}
    pts = None
    if face_res.face_landmarks:
        lm = face_res.face_landmarks[0]; pts = np.array([[p.x * w, p.y * h] for p in lm])
        d = lambda a, b: np.linalg.norm(a - b)
        ear = lambda idx: (d(pts[idx[1]], pts[idx[5]]) + d(pts[idx[2]], pts[idx[4]])) / (2 * d(pts[idx[0]], pts[idx[3]]) + 1e-9)
        gr = lambda iris, c: float(np.dot(pts[iris] - pts[c[0]], pts[c[1]] - pts[c[0]]) / (np.dot(pts[c[1]] - pts[c[0]], pts[c[1]] - pts[c[0]]) + 1e-9))
        bs = {c.category_name: c.score for c in face_res.face_blendshapes[0]}
        m = np.array(face_res.facial_transformation_matrixes[0]); R = m[:3, :3]
        row.update(face=1, ear=(ear(R_EYE) + ear(L_EYE)) / 2, iris_h=(gr(R_IRIS, R_CORN) + gr(L_IRIS, L_CORN)) / 2,
                   blink_bs=max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0)), jaw=bs.get("jawOpen", 0.0), mouth_ap=float(d(pts[13], pts[14]) / (d(pts[10], pts[152]) + 1e-9)),
                   head_yaw=math.degrees(math.atan2(R[0, 2], R[2, 2])), head_pitch=math.degrees(math.asin(-np.clip(R[1, 2], -1, 1))))
    hands = []
    hh, hw = shape_hand[:2]; sc_ = hw / 800.0
    for i, hl in enumerate(hand_res.hand_landmarks):
        p = np.array([[q.x * hw, q.y * hh] for q in hl])
        cx, cy, a, b = [v_ * sc_ for v_ in WHEEL_ELL]
        rn = lambda q: math.hypot((q[0] - cx) / a, (q[1] - cy) / b)
        on = any(0.55 <= rn(p[k]) <= 1.35 for k in (5, 9, 13))
        side = hand_res.handedness[i][0].category_name if hand_res.handedness else "?"
        x0d, y0d, x1d, y1d = [v_ * sc_ for v_ in DASH_ROI]
        in_dash = x0d <= p[8][0] <= x1d and y0d <= p[8][1] <= y1d
        hands.append((p, on, side, in_dash))
    row["n_hands"] = len(hands)                                              # MediaPipe landmark detections (reported separately)
    if img_h is not None:
        row["skin_l"], row["skin_r"], row["skin_dash"] = skin_frac(img_h, SKIN_L), skin_frac(img_h, SKIN_R), skin_frac(img_h, DASH_ROI)
    else:
        row["skin_l"] = row["skin_r"] = row["skin_dash"] = 0.0
    row["hands_on_wheel"] = int(row["skin_l"] > THR_L) + int(row["skin_r"] > THR_R)
    row["hand_dash"] = int(row["skin_l"] > THR_L and row["skin_r"] <= THR_R)     # right hand left the wheel toward the dashboard
    return row, pts, hands


# ------------------------------------------------------------------------------------------------ dashboard
class Dash:
    W, H = 1920, 1080
    FACE = (24, 76, 1080, 608); HANDS = (1128, 76, 768, 432); SCENE = (1128, 520, 768, 432); PLOT = (24, 696, 1080, 256); TILES_Y, TILES_H = 964, 82
    NT = 9

    def __init__(self):
        self.base = np.full((self.H, self.W, 3), BG, np.uint8)
        for (x, y, w, h) in (self.FACE, self.HANDS, self.SCENE, self.PLOT):
            cv2.rectangle(self.base, (x - 1, y - 1), (x + w, y + h), EDGE, 1)
        cv2.rectangle(self.base, (0, 0), (self.W, 64), PANEL, -1); cv2.line(self.base, (0, 64), (self.W, 64), EDGE, 1)
        self.hist = collections.deque(maxlen=900)

    @staticmethod
    def paste(canvas, img, rect):
        x, y, w, h = rect; canvas[y:y + h, x:x + w] = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

    def plot_series(self, canvas, r, xs, ys, ylo, yhi, col, t_now, win=20.0, zones=None):
        x0, y0, w, h = r
        sel = [(t, v, (zones[i] if zones is not None else None)) for i, (t, v) in enumerate(zip(xs, ys)) if t >= t_now - win]
        hh_ = int(h * 0.64)
        pts = [(int(x0 + (t - (t_now - win)) / win * w), int(y0 + h - 4 - (np.clip(v, ylo, yhi) - ylo) / (yhi - ylo) * hh_)) for t, v, _ in sel]
        if len(pts) > 1:
            if zones is None: cv2.polylines(canvas, [np.array(pts, np.int32)], False, col, 2, cv2.LINE_AA)
            else:
                for (p, q, s_) in zip(pts[:-1], pts[1:], sel[1:]): cv2.line(canvas, p, q, ZONE_COL.get(s_[2], MUTED), 3, cv2.LINE_AA)

    def render(self, face_img, hand_img, scene_img, st):
        c = self.base.copy()
        self.paste(c, face_img, self.FACE); self.paste(c, hand_img, self.HANDS); self.paste(c, scene_img, self.SCENE)
        px, py, pw, ph = self.PLOT; gapp = 8; rowh = (ph - 2 * gapp) // 3
        rects = [(px, py + i * (rowh + gapp), pw, rowh) for i in range(3)]
        H = list(self.hist); ts = [h["t"] for h in H]; t_now = st["t"]
        for r in rects: cv2.rectangle(c, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), PANEL, -1)
        if H:
            ylo, yhi = -45, 55
            for lab, cen in st["centroids"].items():
                yy = int(rects[0][1] + rects[0][3] - 4 - (cen - ylo) / (yhi - ylo) * int(rects[0][3] * 0.64))
                cv2.line(c, (rects[0][0], yy), (rects[0][0] + rects[0][2], yy), EDGE, 1)
            self.plot_series(c, rects[0], ts, [h["est"] for h in H], ylo, yhi, INK, t_now, zones=[h["zone"] for h in H])
            self.plot_series(c, rects[1], ts, [h["ear"] for h in H], 0.0, 0.45, (180, 119, 31), t_now)
            self.plot_series(c, rects[2], ts, [h["jaw_s"] for h in H], 0.0, 0.015, (189, 103, 148), t_now)
            if st["speech_thr"]:
                yy = int(rects[2][1] + rects[2][3] - 4 - min(st["speech_thr"], 0.015) / 0.015 * int(rects[2][3] * 0.64)); cv2.line(c, (rects[2][0], yy), (rects[2][0] + rects[2][2], yy), MUTED, 1)
            for (te, name) in st["events"]:
                if t_now - 20 <= te <= t_now:
                    xx = int(px + (te - (t_now - 20)) / 20 * pw)
                    for r in rects: cv2.line(c, (xx, r[1]), (xx, r[1] + r[3]), (255, 255, 255), 2, cv2.LINE_AA)
        # tiles
        tx0 = 24; tw = (self.W - 48 - (self.NT - 1) * 12) // self.NT
        for i in range(self.NT):
            x = tx0 + i * (tw + 12)
            cv2.rectangle(c, (x, self.TILES_Y), (x + tw, self.TILES_Y + self.TILES_H), PANEL, -1)
            cv2.rectangle(c, (x, self.TILES_Y), (x + tw, self.TILES_Y + self.TILES_H), EDGE, 1)
        zcol = ZONE_COL.get(st["zone"], MUTED)
        fx, fy, fw, fh = self.FACE
        if int(time.time() * 2) % 2 == 0: cv2.circle(c, (self.W - 420, 32), 8, (255, 255, 255), -1, cv2.LINE_AA)
        banner = st.get("banner")
        if banner: cv2.rectangle(c, (fx + 16, fy + fh - 70), (fx + 16 + 760, fy + fh - 22), banner[1], -1)
        if st.get("dash_touch"): cv2.rectangle(c, (self.HANDS[0] + 8, self.HANDS[1] + self.HANDS[3] - 54), (self.HANDS[0] + 8 + 380, self.HANDS[1] + self.HANDS[3] - 14), LIGHT, -1)

        im = Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(im)
        rgb = lambda col: (col[2], col[1], col[0])
        d.text((24, 14), "Driver monitoring, live session", font=F["t"], fill=rgb(INK))
        d.text((self.W - 404, 18), "live", font=F["badge"], fill=rgb(INK))
        d.text((self.W - 340, 12), f"{st['phase']}   t = {st['t']:5.1f} s", font=F["sb"], fill=rgb(INK))
        d.text((self.W - 340, 36), f"{st['fps']:4.1f} fps, {st['lat_ms']:3.0f} ms latency", font=F["tiny"], fill=rgb(MUTED))
        d.text((fx + 24, fy + 12), ZONE_TXT.get(st["zone"], st["zone"]), font=F["badge"], fill=rgb(INK))
        d.text((fx + 24, fy + 42), f"gaze yaw {st['est']:+5.1f}°    head yaw {st['head_yaw'] * st.get('head_sign', 1):+5.1f}°", font=F["s"], fill=rgb(MUTED))
        d.text((self.HANDS[0] + 16, self.HANDS[1] + 12), "Hand camera", font=F["h"], fill=rgb(INK))
        d.text((self.SCENE[0] + 16, self.SCENE[1] + 12), "Scene camera (not analysed)", font=F["h"], fill=rgb(INK))
        d.text((px + 12, rects[0][1] + 6), "Gaze yaw (deg, + = right)", font=F["tiny"], fill=rgb(MUTED))
        d.text((px + 12, rects[1][1] + 6), "Eye aspect ratio", font=F["tiny"], fill=rgb(MUTED))
        d.text((px + 12, rects[2][1] + 6), "Mouth movement (lip aperture, 1 s window)", font=F["tiny"], fill=rgb(MUTED))
        if banner: d.text((fx + 32, fy + fh - 66), banner[0], font=F["badge"], fill=((20, 20, 20) if banner[1][0] > 150 else (255, 255, 255)))
        if st.get("dash_touch"): d.text((self.HANDS[0] + 20, self.HANDS[1] + self.HANDS[3] - 50), "Hazard: hand off wheel", font=F["badge"], fill=(20, 20, 20))
        labels = [("Gaze zone", ZONE_TXT.get(st["zone"], "—").split(" (")[0], F["vs"]),
                  ("Eyes off road", f"{st['eor_pct']:4.1f} %", F["v"]),
                  ("Longest glance", f"{st['max_glance']:3.1f} s", F["v"]),
                  ("Blinks per min", f"{st['blink_rate']:4.1f}", F["v"]),
                  ("PERCLOS (60 s)", f"{st['perclos']:4.1f} %", F["v"]),
                  ("Speaking", ("yes" if st["speaking"] else "no") + f"  {st['speech_pct']:3.0f}%", F["vs"]),
                  ("Hands on wheel", f"{st['hands_on']} / 2", F["v"]),
                  ("Hand reaches", f"{st['dash_events']}", F["v"]),
                  ("Hazard reaction", st["rt_txt"], F["vs"])]
        for i, (lab, val, fnt) in enumerate(labels):
            x = tx0 + i * (tw + 12) + 16
            d.text((x, self.TILES_Y + 9), lab, font=F["tiny"], fill=rgb(MUTED))
            d.text((x, self.TILES_Y + 32), val, font=fnt, fill=rgb(INK))
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


# ------------------------------------------------------------------------------------------------ main
class HandWorker(threading.Thread):
    """Runs the hand landmarker on the newest hand-camera frame, asynchronously, so face inference is not blocked."""
    def __init__(self, model_path):
        super().__init__(daemon=True)
        self.m = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=model_path), running_mode=vision.RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3, min_tracking_confidence=0.3))
        self.slot = None; self.lock = threading.Lock(); self.result = None; self.stop = False; self.ts_prev = -1
        self.n_runs = 0

    def submit(self, img, t):
        with self.lock: self.slot = (img, t)

    def run(self):
        while not self.stop:
            with self.lock: s = self.slot; self.slot = None
            if s is None: time.sleep(0.002); continue
            img, t = s
            ts = max(self.ts_prev + 1, int(t * 1000)); self.ts_prev = ts
            res = self.m.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)), ts)
            self.result = (res, t, img.shape); self.n_runs += 1


class Session:
    def __init__(self, rx, out):
        self.rx, self.out = rx, out
        self.an = Analyzer(); self.dash = Dash(); self.hist = collections.deque(maxlen=900)
        self.rows = []; self.jaw_series = collections.deque(); self.events_seen = 0
        self.proc_times = collections.deque(maxlen=30)
        self.pkg = None; self.pkg_lock = threading.Lock(); self.done = False; self.dash_run = 0

    def infer(self, face, hw):
        rx, an = self.rx, self.an
        ts_prev = -1
        while True:
            with rx.lock: item = rx.ready; rx.ready = None
            if item is None:
                if rx.ended: break
                time.sleep(0.001); continue
            f, d = item; hdr = d["hdr"][0]; t = hdr["t"]; gt = hdr["gt"]; tw0 = time.time()
            img_f, img_h, img_s = d["img"][0], d["img"][1], d["img"][2]
            hw.submit(img_h, t)
            ts_ms = max(ts_prev + 1, int(t * 1000)); ts_prev = ts_ms
            fres = face.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img_f, cv2.COLOR_BGR2RGB)), ts_ms)
            hres, ht, hshape = hw.result if hw.result is not None else (type("E", (), {"hand_landmarks": [], "handedness": []})(), t, img_h.shape)
            feat, pts, hands = live_features(fres, hres, img_f.shape, hshape, img_h)
            dt = 0.0 if an.t_prev is None else max(0.0, t - an.t_prev); an.t_prev = t
            closed = bool(feat["face"] and feat["blink_bs"] > 0.30)
            # ---- calibration on labelled targets (first 12 s) ----
            if feat["face"]:
                if gt["cal"] and not closed and t > 0.6:
                    an.feed_cal([feat["head_yaw"], feat["iris_h"]], gt["head_yaw"] + gt["eye_yaw"], gt["label"])
                if (not gt["cal"]) and (not an.cal_done) and len(an.cal_x) > 60:
                    an.finish_cal()
                    base = np.array([j for _, j in self.jaw_series]) if self.jaw_series else np.array([0.0])
                    an.speech_thr = max(0.0015, 5.0 * float(np.std(base)) + 0.001)
                    an.t_meas0 = t
                    print(f"[live] calibration done: n={len(an.cal_x)} rmse {an.cal_rmse:.2f} deg, centroids { {k: round(v, 1) for k, v in an.centroids.items()} }", flush=True)
            est = an.last_est
            if feat["face"] and an.cal_done:
                if not closed:
                    an.est_hist.append(an.predict([feat["head_yaw"], feat["iris_h"]])); est = float(np.median(an.est_hist)); an.last_est = est
                zone_raw = "eyes_closed" if closed else an.classify(est)
                if zone_raw != "eyes_closed":
                    if zone_raw != an.raw_prev: an.raw_run_start = t
                    an.raw_prev = zone_raw; an.zone_raw_hist.append(zone_raw)
                    if len(an.zone_raw_hist) == 2 and an.zone_raw_hist[0] == an.zone_raw_hist[1]: an.zone = zone_raw
            zone = an.zone if an.cal_done else "n/a"
            # ---- speech activity (variability of jaw-open score over 1 s) ----
            if feat["face"]: self.jaw_series.append((t, feat["mouth_ap"]))
            while self.jaw_series and self.jaw_series[0][0] < t - 1.0: self.jaw_series.popleft()
            jaw_s = float(np.std([j for _, j in self.jaw_series])) if len(self.jaw_series) > 5 else 0.0
            if an.cal_done and an.speech_thr is not None:
                an.speaking = jaw_s > an.speech_thr
                if an.speaking: an.t_speak += dt
            # ---- blinks / PERCLOS ----
            if feat["face"]:
                if closed and not an.blink_state: an.blink_state = True; an.blinks.append(t)
                if (not closed) and feat["blink_bs"] < 0.15: an.blink_state = False
                an.closed_hist.append((t, 1.0 if closed else 0.0, dt))
            while an.closed_hist and an.closed_hist[0][0] < t - 60: an.closed_hist.popleft()
            # ---- glances / zone time ----
            if an.cal_done and dt > 0:
                an.time_in[zone] += dt
                if zone in OFF_ROAD:
                    if an.glance_open is None: an.glance_open = [zone, t, 0.0]
                    an.glance_open[2] = t - an.glance_open[1]
                elif an.glance_open is not None:
                    an.glances.append(tuple(an.glance_open)); an.glance_open = None
            # ---- hand at the centre display (debounced episodes) ----
            self.dash_run = (self.dash_run + 1) if feat["hand_dash"] else 0
            if self.dash_run == 3: an.dash_events += 1
            dash_touch = self.dash_run >= 3
            # ---- events + reaction time ----
            while self.events_seen < len(rx.events):
                te, name = rx.events[self.events_seen]; self.events_seen += 1; an.events.append((te, name))
            for (te, name) in an.events:
                if name in an.rt or not name.startswith("HAZARD"): continue
                if t >= te and zone == "hazard_right":
                    start = an.raw_run_start if an.raw_run_start >= te else t
                    an.rt[name] = start - te
            tot = sum(an.time_in.values()) or 1e-9
            eor = sum(an.time_in[z] for z in OFF_ROAD) / tot * 100 if an.cal_done else 0.0
            max_gl = max([g[2] for g in an.glances] + ([an.glance_open[2]] if an.glance_open else [0.0]))
            nb = sum(1 for b in an.blinks if b > t - 30); span = min(30.0, max(t, 1.0))
            perclos = (sum(c_ * dd for _, c_, dd in an.closed_hist) / max(sum(dd for _, _, dd in an.closed_hist), 1e-9)) * 100
            speech_pct = an.t_speak / max(t - (an.t_meas0 or t), 1e-9) * 100 if an.cal_done else 0.0
            rt_txt = " · ".join(f"{an.rt[k]:.2f}s" if k in an.rt else "—" for k in ("HAZARD_ONSET_1", "HAZARD_ONSET_2"))
            now = time.time(); lat_ms = (now - hdr["unix"]) * 1000; self.proc_times.append(now)
            fps_proc = (len(self.proc_times) - 1) / (self.proc_times[-1] - self.proc_times[0]) if len(self.proc_times) > 2 else 0.0
            banner = None
            for (te, name) in an.events:
                if te <= t < te + 4.0: banner = (f"Hazard {name[-1]}: pedestrian", LIGHT)
            if gt["cal"]: banner = ("Calibration", (80, 80, 80))
            if dash_touch: banner = ("Hazard: hand off wheel, reaching to dashboard", C_ORANGE)
            self.hist.append(dict(t=t, est=est, zone=zone, ear=feat.get("ear", 0.3), jaw_s=jaw_s))
            st = dict(head_sign=(1.0 if an.model is None or an.model[0] >= 0 else -1.0), t=t, phase=("calibration" if gt["cal"] else "measurement"), fps=fps_proc, lat_ms=lat_ms, zone=zone, est=est, head_yaw=feat.get("head_yaw", 0.0),
                      centroids=dict(an.centroids), events=list(an.events), speech_thr=an.speech_thr, banner=banner, eor_pct=eor, max_glance=max_gl,
                      blink_rate=nb / span * 60, perclos=perclos, speaking=an.speaking, speech_pct=speech_pct, hands_on=feat["hands_on_wheel"], hands_l=int(feat["skin_l"] > THR_L), hands_r=int(feat["skin_r"] > THR_R), rt_txt=rt_txt, dash_touch=dash_touch, dash_events=an.dash_events)
            with self.pkg_lock:
                self.pkg = dict(img_f=img_f, img_h=img_h, img_s=img_s, pts=pts, hands=hands, st=st, zone=zone, hist=list(self.hist))
            self.rows.append(dict(frame=f, t=t, unix=hdr["unix"], latency_ms=lat_ms, proc_ms=(time.time() - tw0) * 1000,
                                  face=feat["face"], closed=int(closed), ear=feat.get("ear", np.nan), iris_h=feat.get("iris_h", np.nan), blink_bs=feat.get("blink_bs", np.nan),
                                  jaw=feat.get("jaw", np.nan), mouth_ap=feat.get("mouth_ap", np.nan), jaw_s=jaw_s, head_yaw_mp=feat.get("head_yaw", np.nan), head_pitch_mp=feat.get("head_pitch", np.nan),
                                  est_yaw=est, zone=zone, speaking=int(an.speaking), n_hands=feat["n_hands"], hands_on_wheel=feat["hands_on_wheel"], hand_dash=feat["hand_dash"], skin_l=feat["skin_l"], skin_r=feat["skin_r"], skin_dash=feat["skin_dash"], cal=gt["cal"]))
        self.done = True

    def render_loop(self, show):
        import subprocess, imageio_ffmpeg
        self.tmp_video = os.path.join(self.out, "_annotated_live_tmp.mp4")
        ff = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{Dash.W}x{Dash.H}", "-r", str(FPS), "-i", "-",
                               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", self.tmp_video], stdin=subprocess.PIPE)
        written = -1
        last_t = -1.0; wait_img = None; last_view = None
        while not (self.done and self.pkg is None):
            with self.pkg_lock: p = self.pkg; self.pkg = None
            if p is None:
                if self.done: break
                if show and last_view is not None:       # repaint the last frame so the window never goes blank between frames
                    cv2.imshow("Driver Monitoring - Live", last_view)
                    if cv2.waitKey(8) & 0xFF == ord("q"): break
                elif show:                                 # keep the window responsive while waiting for the first frame
                    if wait_img is None:
                        wait_img = np.full((720, 1280, 3), BG, np.uint8)
                        cv2.putText(wait_img, "Waiting for Unity...", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (238, 233, 230), 2, cv2.LINE_AA)
                    cv2.imshow("Driver Monitoring - Live", wait_img)
                    if cv2.waitKey(30) & 0xFF == ord("q"): break
                else:
                    time.sleep(0.002)
                continue
            st = p["st"]; vis_f = p["img_f"].copy(); vis_h = p["img_h"].copy(); zone = p["zone"]
            if p["pts"] is not None:
                pts = p["pts"]
                for idx in R_EYE + L_EYE: cv2.circle(vis_f, tuple(pts[idx].astype(int)), 2, (0, 255, 255), -1, cv2.LINE_AA)
                for idx in range(468, 478): cv2.circle(vis_f, tuple(pts[idx].astype(int)), 3, (0, 255, 0), -1, cv2.LINE_AA)
                x0, y0 = pts.min(0).astype(int); x1, y1 = pts.max(0).astype(int)
                cv2.rectangle(vis_f, (x0 - 8, y0 - 8), (x1 + 8, y1 + 8), (235, 235, 235), 2, cv2.LINE_AA)
            sc_ = vis_h.shape[1] / 800.0
            cx, cy, ea, eb = [v_ * sc_ for v_ in WHEEL_ELL]; cv2.ellipse(vis_h, (int(cx), int(cy)), (int(ea), int(eb)), 0, 0, 360, (90, 90, 90), 1, cv2.LINE_AA)
            x0d, y0d, x1d, y1d = [int(v_ * sc_) for v_ in DASH_ROI]; cv2.rectangle(vis_h, (x0d, y0d), (x1d, y1d), (190, 190, 190), 1, cv2.LINE_AA)
            for roi, ok_ in ((SKIN_L, st["hands_l"]), (SKIN_R, st["hands_r"])):
                a_, b_, c_, d_ = [int(v_ * sc_) for v_ in roi]
                cv2.rectangle(vis_h, (a_, b_), (c_, d_), (235, 235, 235) if ok_ else (120, 120, 120), 2, cv2.LINE_AA)
            for (hp, on, side, ind) in p["hands"]:
                palm_w = np.linalg.norm(hp[5] - hp[17]); palm_l = np.linalg.norm(hp[0] - hp[9])
                if palm_l < 20 or palm_w < 0.45 * palm_l: continue                  # collapsed / implausible skeleton: do not draw
                col = (0, 200, 255)
                for (i, j) in HAND_CONN: cv2.line(vis_h, tuple(hp[i].astype(int)), tuple(hp[j].astype(int)), col, 2, cv2.LINE_AA)
                for q in hp: cv2.circle(vis_h, tuple(q.astype(int)), 3, col, -1, cv2.LINE_AA)
            self.dash.hist = collections.deque(p["hist"], maxlen=900)
            canvas = self.dash.render(vis_f, vis_h, p["img_s"], st)
            target = int(round(st["t"] * FPS))
            buf = canvas.tobytes()
            while written < target: ff.stdin.write(buf); written += 1
            if show:
                last_view = cv2.resize(canvas, VIEW, interpolation=cv2.INTER_AREA)
                cv2.imshow("Driver Monitoring - Live", last_view)
                if cv2.waitKey(1) & 0xFF == ord("q"): break
        ff.stdin.close(); ff.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    ap.add_argument("--no-window", action="store_true")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)

    face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=os.path.join(MODELS, "face_landmarker.task")), running_mode=vision.RunningMode.VIDEO,
        num_faces=1, output_face_blendshapes=True, output_facial_transformation_matrixes=True))
    hw = HandWorker(os.path.join(MODELS, "hand_landmarker.task")); hw.start()
    rx = Receiver(a.port, a.out); rx.start()
    print(f"[live] listening on 127.0.0.1:{a.port} - start Unity (play mode) ...", flush=True)
    s = Session(rx, a.out)
    if not a.no_window:
        cv2.namedWindow("Driver Monitoring - Live", cv2.WINDOW_AUTOSIZE); cv2.moveWindow("Driver Monitoring - Live", 0, 0)
    th = threading.Thread(target=s.infer, args=(face, hw), daemon=True); th.start()
    try:
        s.render_loop(not a.no_window)
    finally:
        s.done = True; th.join(timeout=5); hw.stop = True; cv2.destroyAllWindows()

    import subprocess, imageio_ffmpeg
    ffexe = imageio_ffmpeg.get_ffmpeg_exe()
    def encode(src, dst, crf=17):
        subprocess.run([ffexe, "-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst], check=False)
    if os.path.exists(s.tmp_video):
        encode(s.tmp_video, os.path.join(a.out, "annotated_live.mp4"), 16); os.remove(s.tmp_video)
    for k in (0, 1):
        raw = os.path.join(a.out, f"raw_cam{k}.mp4")
        if os.path.exists(raw): encode(raw, os.path.join(a.out, f"raw_cam{k}_h264.mp4"), 18); os.remove(raw)
    an = s.an; df = pd.DataFrame(s.rows)
    df.to_csv(os.path.join(a.out, "live_measurements.csv"), index=False)
    pd.DataFrame(rx.gt_rows).to_csv(os.path.join(a.out, "simulator_ground_truth.csv"), index=False)
    summary = dict(frames_received_cam0=len(rx.gt_rows), frames_processed=len(df), frames_dropped_by_pipeline=int(rx.n_dropped), hand_detector_runs=hw.n_runs,
                   calibration=dict(rmse_deg=getattr(an, "cal_rmse", None), centroids_deg={k: float(v) for k, v in an.centroids.items()}, n_samples=len(an.cal_x)),
                   events=an.events, reaction_time_s=an.rt, glances=an.glances, blinks_detected=len(an.blinks),
                   speech_threshold=an.speech_thr, time_in_zone_s=dict(an.time_in),
                   median_latency_ms=float(df.latency_ms.median()) if len(df) else None, p95_latency_ms=float(df.latency_ms.quantile(0.95)) if len(df) else None,
                   median_proc_ms=float(df.proc_ms.median()) if len(df) else None)
    with open(os.path.join(a.out, "live_summary.json"), "w") as fh: json.dump(summary, fh, indent=2, default=str)
    print("[live] session finished:", json.dumps({k: summary[k] for k in ("frames_received_cam0", "frames_processed", "reaction_time_s", "median_latency_ms", "median_proc_ms", "hand_detector_runs")}, default=str), flush=True)


if __name__ == "__main__":
    main()
