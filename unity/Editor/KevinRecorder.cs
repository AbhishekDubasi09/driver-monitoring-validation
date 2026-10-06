using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using KevinDriver;

/// <summary>Edit-mode verification helper: steps the scenario to a time and renders the three cameras to PNG (for looking at, not for the study).</summary>
public static class KevinRecorder
{
    static string Arg(string name, string def)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
        return def;
    }

    static void Save(Camera cam, int w, int h, string path)
    {
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
        var prev = cam.targetTexture; cam.targetTexture = rt;
        for (int k = 0; k < 3; k++) cam.Render();          // warm-up renders (async shader compilation)
        RenderTexture.active = rt;
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
        File.WriteAllBytes(path, tex.EncodeToPNG());
        RenderTexture.active = null; cam.targetTexture = prev;
        UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex);
    }

    // Finds where the centre touchscreen is: raycasts hand-camera pixels onto the interior mesh and prints car-local hit points.
    public static void ProbeScreen()
    {
        EditorSceneManager.OpenScene(KevinSceneBuilder.ScenePath);
        var sc = UnityEngine.Object.FindFirstObjectByType<DriveScenario>(); var st = sc.GetComponent<KevinLiveStreamer>(); var cam = st.cams[1];
        sc.ResetScenario(); sc.Tick(0.1f, 1f / 30f);
        var interior = KevinDriverBehaviour.Find(sc.car, "RMCar26_Interior_LOD0");
        var mc = interior.gameObject.AddComponent<MeshCollider>(); mc.sharedMesh = interior.GetComponent<MeshFilter>().sharedMesh;
        Physics.SyncTransforms();
        foreach (var px in new[] { new Vector2(707, 116), new Vector2(660, 90), new Vector2(750, 140), new Vector2(690, 160), new Vector2(740, 80) })
        {
            var ray = cam.ScreenPointToRay(new Vector3(px.x / 800f * cam.pixelWidth, (450f - px.y) / 450f * cam.pixelHeight, 0));
            if (cam.targetTexture == null) { var rt = new RenderTexture(800, 450, 24); cam.targetTexture = rt; ray = cam.ScreenPointToRay(new Vector3(px.x, 450f - px.y, 0)); }
            if (Physics.Raycast(ray, out var hit, 5f)) Debug.Log("[KD] probe px=" + px + " hitCar=" + sc.car.InverseTransformPoint(hit.point).ToString("F3") + " normalCar=" + sc.car.InverseTransformDirection(hit.normal).ToString("F3"));
            else Debug.Log("[KD] probe px=" + px + " no hit");
        }
    }

    // Steps real editor frames (blendshapes only refresh between frames) and saves a mouth close-up per jaw variant.
    public static void MouthTest()
    {
        string outDir = Arg("-kdOut", Path.Combine(Path.GetTempPath(), "driver_monitoring_shots", "mouth"));
        Directory.CreateDirectory(outDir);
        EditorSceneManager.OpenScene(KevinSceneBuilder.ScenePath);
        var sc = UnityEngine.Object.FindFirstObjectByType<DriveScenario>(); var beh = sc.driver; sc.ResetScenario();
        var jc = new GameObject("jc").AddComponent<Camera>(); jc.nearClipPlane = 0.03f; jc.fieldOfView = 14;
        float t = 24f; const float dt = 1f / 30f;
        for (int i = 0; i < 700; i++) sc.Tick(i * dt * 0.0343f, dt);      // fast-forward the scenario state a little
        var ax = new[] { new Vector3(1, 0, 0), new Vector3(-1, 0, 0), new Vector3(0, 1, 0), new Vector3(0, -1, 0), new Vector3(0, 0, 1), new Vector3(0, 0, -1) };
        // variants: (jawMax, share, axis index, label)
        var V = new System.Collections.Generic.List<(float max, float share, int axi, string label)> { (0f, 0f, 0, "closed") , (0f, 1f, 0, "blend_only") };
        for (int k = 0; k < 6; k++) V.Add((18f, 0f, k, "bone_ax" + k));
        int vi = 0, tick = 0;
        EditorApplication.CallbackFunction step = null;
        step = () =>
        {
            if (vi >= V.Count) { EditorApplication.update -= step; UnityEngine.Object.DestroyImmediate(jc.gameObject); Debug.Log("[KD] mouth test done"); EditorApplication.Exit(0); return; }
            var v = V[vi];
            beh.jawMaxDeg = v.max; beh.jawBlendshapeShare = v.share; beh.jawAxis = ax[v.axi]; beh.forceJaw = v.label == "closed" ? 0f : 0.9f; beh.talking = false;
            var headJ = KevinDriverBehaviour.Find(beh.transform, "CC_Base_Head");
            jc.transform.position = headJ.position + sc.car.forward * 1.1f + sc.car.right * 0.14f; jc.transform.LookAt(headJ.position - sc.car.up * 0.085f);
            beh.Tick(t, dt);
            tick++;
            if (tick == 4) { Save(jc, 600, 700, Path.Combine(outDir, vi + "_" + v.label + ".png")); vi++; tick = 0; }
        };
        EditorApplication.update += step;
    }

    // Automatic grip fit: searches anchor offsets, finger tilt and palm roll that put the rim tube inside the closed fingers.
    public static void GripFit()
    {
        EditorSceneManager.OpenScene(KevinSceneBuilder.ScenePath);
        var sc = UnityEngine.Object.FindFirstObjectByType<DriveScenario>(); var beh = sc.driver; sc.ResetScenario();
        float t = 0f; const float dt = 1f / 30f;
        while (t < 8f) { sc.Tick(t, dt); t += dt; }
        var results = new System.Collections.Generic.List<(float cost, float o, float r, float tilt, float roll, float cs, int mode)>();
        foreach (int mode in new[] { 0, 1 })
        for (float o = -0.045f; o <= 0.0751f; o += 0.015f)
            for (float r = -0.045f; r <= 0.0751f; r += 0.015f)
                foreach (float tilt in new[] { -0.4f, 0f, 0.4f, 0.8f, 1.5f })
                    foreach (float roll in new[] { -90f, -60f, -30f, 0f, 30f, 60f, 90f })
                        foreach (float cs in new[] { 0.8f, 1.0f, 1.2f, 1.4f })
                        {
                            beh.gripMode = mode; beh.gripAnchorOut = o; beh.gripAnchorRear = r; beh.gripFingerTilt = tilt; beh.gripRollDeg = roll; beh.gripCurlScale = cs;
                            beh.Tick(t, dt);
                            results.Add((beh.GripCost(true) + beh.GripCost(false), o, r, tilt, roll, cs, mode));
                        }
        results.Sort((a, b) => a.cost.CompareTo(b.cost));
        for (int i = 0; i < 6; i++) Debug.Log("[KD] gripfit #" + i + " cost=" + results[i].cost.ToString("0.000000") + " out=" + results[i].o.ToString("0.000") + " rear=" + results[i].r.ToString("0.000") + " tilt=" + results[i].tilt + " roll=" + results[i].roll + " curlScale=" + results[i].cs + " mode=" + results[i].mode + " (wristRoll check below)");
        Debug.Log("[KD] gripfit evaluated " + results.Count);
    }

    public static void Shots()
    {
        string outDir = Arg("-kdOut", Path.Combine(Path.GetTempPath(), "driver_monitoring_shots"));
        var ts = Arg("-kdT", "3").Split(',');
        Directory.CreateDirectory(outDir);
        EditorSceneManager.OpenScene(KevinSceneBuilder.ScenePath);
        var sc = UnityEngine.Object.FindFirstObjectByType<DriveScenario>();
        var st = sc.GetComponent<KevinLiveStreamer>();
        // optional experiment knobs for hand pose tuning
        var beh = sc.driver;
        string fa = Arg("-kdFingerAxis", null); if (fa != null) { var p = fa.Split(','); beh.fingerAxis = new Vector3(float.Parse(p[0]), float.Parse(p[1]), float.Parse(p[2])); }
        string ja = Arg("-kdJawAxis", null); if (ja != null) { var p = ja.Split(','); beh.jawAxis = new Vector3(float.Parse(p[0]), float.Parse(p[1]), float.Parse(p[2])); }
        string fj = Arg("-kdForceJaw", null); if (fj != null) beh.forceJaw = float.Parse(fj, System.Globalization.CultureInfo.InvariantCulture);
        string jm = Arg("-kdJawMax", null); if (jm != null) beh.jawMaxDeg = float.Parse(jm, System.Globalization.CultureInfo.InvariantCulture);
        string tt = Arg("-kdTouch", null); if (tt != null) { var p = tt.Split(','); beh.touchTargetCar = new Vector3(float.Parse(p[0]), float.Parse(p[1]), float.Parse(p[2])); }
        string gf = Arg("-kdGrip", null); if (gf != null) { var p = gf.Split(','); beh.gripAnchorOut = float.Parse(p[0]); beh.gripAnchorRear = float.Parse(p[1]); beh.gripFingerTilt = float.Parse(p[2]); if (p.Length > 3) beh.gripRollDeg = float.Parse(p[3]); if (p.Length > 4) beh.gripCurlScale = float.Parse(p[4]); if (p.Length > 5) beh.gripMode = int.Parse(p[5]); }
        string ang = Arg("-kdAngles", null); if (ang != null) { var p = ang.Split(','); beh.leftHandAngleDeg = float.Parse(p[0]); beh.rightHandAngleDeg = float.Parse(p[1]); }
        string lcs = Arg("-kdLeftSign", null); if (lcs != null) beh.leftCurlSign = float.Parse(lcs);
        string gc = Arg("-kdGripCurl", null); if (gc != null) { var p = gc.Split(','); beh.gripCurl = new Vector3(float.Parse(p[0]), float.Parse(p[1]), float.Parse(p[2])); }
        string cp = Arg("-kdHandCam", null);
        if (cp != null) { var p = cp.Split(','); st.cams[1].transform.position = sc.car.TransformPoint(new Vector3(float.Parse(p[0]), float.Parse(p[1]), float.Parse(p[2]))); st.cams[1].transform.LookAt(sc.car.TransformPoint(new Vector3(float.Parse(p[3]), float.Parse(p[4]), float.Parse(p[5])))); }
        sc.ResetScenario();
        float t = 0f; const float dt = 1f / 30f;
        string hfov = Arg("-kdHandFov", null); if (hfov != null) st.cams[1].fieldOfView = float.Parse(hfov, System.Globalization.CultureInfo.InvariantCulture);
        foreach (var tsv in ts)
        {
            float target = float.Parse(tsv, System.Globalization.CultureInfo.InvariantCulture);
            while (t < target) { sc.Tick(t, dt); t += dt; }
            if (Arg("-kdReach", null) != null) { beh.reach = float.Parse(Arg("-kdReach", "0"), System.Globalization.CultureInfo.InvariantCulture); beh.tap = float.Parse(Arg("-kdTap", "0"), System.Globalization.CultureInfo.InvariantCulture); }
            sc.Tick(t, dt);
            if (Arg("-kdReach", null) != null) { beh.reach = float.Parse(Arg("-kdReach", "0"), System.Globalization.CultureInfo.InvariantCulture); beh.tap = float.Parse(Arg("-kdTap", "0"), System.Globalization.CultureInfo.InvariantCulture); beh.Tick(t, dt); }
            if (Arg("-kdHandDbg", "0") == "1")
            {
                var hid = new System.Collections.Generic.List<Renderer>();
                foreach (var r in sc.car.GetComponentsInChildren<Renderer>())
                {
                    string n = r.name;
                    if (r.transform.IsChildOf(beh.transform)) continue;
                    if (n.Contains("Body") || n.Contains("Door") || n.Contains("Window") || n.Contains("Glass") || n.Contains("Paint") || n.Contains("Spoiler") || n.Contains("Interior")) { if (r.enabled) { r.enabled = false; hid.Add(r); } }
                }
                var dc = new GameObject("hd").AddComponent<Camera>(); dc.nearClipPlane = 0.03f; dc.fieldOfView = 16;
                foreach (var side in new[] { "L", "R" })
                {
                    var hnd = KevinDriverBehaviour.Find(beh.transform, "CC_Base_" + side + "_Hand"); float sgn = side == "L" ? -1f : 1f;
                    var views = new[] { ("side", sc.car.right * sgn * 0.6f + sc.car.up * 0.05f), ("front", sc.car.forward * 0.6f + sc.car.up * 0.12f), ("top", sc.car.up * 0.6f - sc.car.forward * 0.05f) };
                    foreach (var (nm, off) in views)
                    {
                        dc.transform.position = hnd.position + off; dc.transform.LookAt(hnd.position + sc.car.forward * 0.05f);
                        Save(dc, 700, 700, Path.Combine(outDir, "hd_" + side + "_" + nm + "_t" + target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
                    }
                }
                UnityEngine.Object.DestroyImmediate(dc.gameObject); foreach (var r in hid) r.enabled = true;
            }
            if (Arg("-kdHi", "0") == "1") Save(st.cams[1], 1600, 900, Path.Combine(outDir, "handsHi_t" + target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
            if (Arg("-kdJawSweep", "0") == "1")
            {
                var jc = new GameObject("jc").AddComponent<Camera>(); jc.nearClipPlane = 0.03f; jc.fieldOfView = 14;
                var headJ = KevinDriverBehaviour.Find(beh.transform, "CC_Base_Head");
                jc.transform.position = headJ.position + sc.car.forward * 1.1f + sc.car.right * 0.14f; jc.transform.LookAt(headJ.position - sc.car.up * 0.085f);
                var axes = new[] { new Vector3(1, 0, 0), new Vector3(-1, 0, 0), new Vector3(0, 1, 0), new Vector3(0, -1, 0), new Vector3(0, 0, 1), new Vector3(0, 0, -1) };
                beh.forceJaw = 0f; beh.jawMaxDeg = 16f; beh.Tick(t, dt); Save(jc, 600, 700, Path.Combine(outDir, "jaw_closed.png"));
                for (int k = 0; k < axes.Length; k++)
                {
                    beh.jawAxis = axes[k]; beh.forceJaw = 0.9f; for (int s = 0; s < 40; s++) beh.Tick(t, dt);
                    Save(jc, 600, 700, Path.Combine(outDir, "jaw_ax" + k + ".png"));
                }
                UnityEngine.Object.DestroyImmediate(jc.gameObject);
            }
            if (Arg("-kdClose", "0") == "1")
            {
                var cc = new GameObject("close").AddComponent<Camera>(); cc.nearClipPlane = 0.03f; cc.fieldOfView = 24;
                var headT = KevinDriverBehaviour.Find(beh.transform, "CC_Base_Head");
                cc.transform.position = headT.position + sc.car.forward * 0.9f + sc.car.up * 0.02f + sc.car.right * 0.12f; cc.transform.LookAt(headT.position - sc.car.up * 0.07f);
                Save(cc, 900, 900, Path.Combine(outDir, "closeface_t" + target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
                var wc = KevinDriverBehaviour.Find(sc.car, "RMCar26_SteeringWheel");
                var rh = KevinDriverBehaviour.Find(beh.transform, "CC_Base_R_Hand");
                cc.fieldOfView = 30; cc.transform.position = rh.position + sc.car.forward * 0.55f + sc.car.up * 0.25f - sc.car.right * 0.05f; cc.transform.LookAt(rh.position);
                Save(cc, 900, 900, Path.Combine(outDir, "closeRH_t" + target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
                var lh = KevinDriverBehaviour.Find(beh.transform, "CC_Base_L_Hand");
                cc.transform.position = lh.position + sc.car.forward * 0.55f + sc.car.up * 0.25f + sc.car.right * 0.05f; cc.transform.LookAt(lh.position);
                Save(cc, 900, 900, Path.Combine(outDir, "closeLH_t" + target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
                UnityEngine.Object.DestroyImmediate(cc.gameObject);
            }
            string tag = target.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
            {
                var smrs = beh.GetComponentsInChildren<SkinnedMeshRenderer>(); string rb = "";
                foreach (var smr in smrs) { int gi = smr.sharedMesh.GetBlendShapeIndex("Jaw_Open"); if (gi >= 0) rb += smr.name + ":" + smr.GetBlendShapeWeight(gi).ToString("0.0") + " "; }
                Debug.Log("[KD] t=" + tag + " Jaw01=" + beh.Jaw01.ToString("0.000") + " talking=" + beh.talking + " readback " + rb + " wristRoll L=" + beh.WristTwistL.ToString("0.0") + " R=" + beh.WristTwistR.ToString("0.0"));
            }
            Save(st.cams[0], 960, 540, Path.Combine(outDir, "face_t" + tag + ".png"));
            Save(st.cams[1], 800, 450, Path.Combine(outDir, "hands_t" + tag + ".png"));
            Save(st.cams[2], 960, 540, Path.Combine(outDir, "scene_t" + tag + ".png"));
            if (Arg("-kdDebug", "0") == "1")
            {
                var dbg = new GameObject("dbg").AddComponent<Camera>(); dbg.fieldOfView = 40; dbg.nearClipPlane = 0.05f;
                var hidden = new System.Collections.Generic.List<Renderer>();
                foreach (var r in sc.car.GetComponentsInChildren<Renderer>())
                {
                    string n = r.name;
                    if (n.Contains("Body") || n.Contains("Door") || n.Contains("Window") || n.Contains("Glass") || n.Contains("Wheel") && !n.Contains("Steering") || n.Contains("Rotor") || n.Contains("Paint") || n.Contains("Spoiler")) { if (r.enabled) { r.enabled = false; hidden.Add(r); } }
                }
                dbg.transform.position = sc.car.TransformPoint(new Vector3(-3.0f, 1.1f, 0.1f)); dbg.transform.LookAt(sc.car.TransformPoint(new Vector3(-0.38f, 0.85f, 0.1f)));
                Save(dbg, 1000, 700, Path.Combine(outDir, "dbg_side_t" + tag + ".png"));
                dbg.transform.position = sc.car.TransformPoint(new Vector3(-0.38f, 3.0f, 0.1f)); dbg.transform.LookAt(sc.car.TransformPoint(new Vector3(-0.38f, 0.85f, 0.1f)), sc.car.forward);
                Save(dbg, 1000, 700, Path.Combine(outDir, "dbg_top_t" + tag + ".png"));
                foreach (var r in hidden) r.enabled = true;
                UnityEngine.Object.DestroyImmediate(dbg.gameObject);
            }
        }
        Debug.Log("[KD] shots written to " + outDir);
    }
}
