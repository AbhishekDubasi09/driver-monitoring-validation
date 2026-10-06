using System.Collections.Generic;
using UnityEngine;

namespace KevinDriver
{
    /// <summary>
    /// Procedural "driver" for the Kevin CC5 character. SIMULATED behaviour: a scenario script sets the gaze intent,
    /// this component turns it into eye saccades, head motion, blinks, talking (jaw bone + blendshapes), steering,
    /// a two-handed rim grasp and an occasional reach to the centre touchscreen. Nothing here is measured from a real person.
    /// </summary>
    public class KevinDriverBehaviour : MonoBehaviour
    {
        public Transform carRoot;
        public Transform steeringWheel;
        public int seed = 7;

        [Header("Seat pose (car-local)")]
        public Vector3 hipPosCar = new Vector3(-0.38f, 0.50f, 0.04f);
        public float leanBackDeg = 10f;
        public float leftHandAngleDeg = 150f, rightHandAngleDeg = 30f;    // position on the rim (0 = 3 o'clock, 90 = 12)
        public Vector3 fingerAxis = new Vector3(1, 0, 0);
        public Vector3 touchTargetCar = new Vector3(0.015f, 0.90f, 0.53f);   // centre touchscreen centre (car-local), from a mesh raycast probe
        public Vector3 touchNormalCar = new Vector3(-0.08f, 0.44f, -0.90f);

        [Header("Grasp tuning")]
        public float gripAnchorOut = 0.015f;       // fitted by Editor GripFit (wrap condition + wrist-roll limit)
        public float gripAnchorRear = 0.008f;
        public float gripFingerTilt = 0.8f;
        public float gripRollDeg = 30f;
        public int gripMode = 1;                   // 0: fingers inward, palm to the front   1: fingers forward, palm toward the wheel centre
        public float gripCurlScale = 1.4f;
        public float leftCurlSign = 1f;           // the left hand bones are mirrored, so its fingers curl about the opposite axis
        public Vector3 gripCurl = new Vector3(38f, 48f, 32f);      // proximal / middle / distal curl (deg), stops at a natural closed grip
        public float thumbCurl = 25f;
        [Header("Jaw")]
        public Vector3 jawAxis = new Vector3(0, 0, -1);        // found by a bone-axis test: opens the jaw, carries chin, beard, teeth and tongue
        public float jawMaxDeg = 10f;
        [Range(0, 1)] public float jawBlendshapeShare = 0.0f;

        // ---- commands (set by the scenario every frame) ----
        public Vector4 gazeIntent;          // headYaw, headPitch, eyeYaw, eyePitch (deg; yaw + = driver's right, pitch + = up)
        public bool talking;
        public float steerDeg;
        public float reach;                 // 0..1 right hand leaves the wheel toward the touchscreen
        public float tap;                   // 0..1 fingertip press
        public float forceJaw = -1f;        // test hook
        public float gripAmount = 1f;       // 0 = open hands resting on the rim (tracker initialisation), 1 = full grasp

        // ---- outputs (simulation ground truth) ----
        public float HeadYaw, HeadPitch, EyeYaw, EyePitch, Blink01, Jaw01;

        Transform hip, spine01, spine02, head, neck1, lEye, rEye, jawRoot;
        Transform lThigh, lCalf, lFoot, rThigh, rCalf, rFoot;
        Transform lUpper, lFore, lHand, rUpper, rFore, rHand, lTw1, lTw2, rTw1, rTw2;
        public float WristTwistL, WristTwistR;
        readonly List<Transform> lFingers = new List<Transform>(), rFingers = new List<Transform>();
        readonly Dictionary<Transform, Quaternion> restLocal = new Dictionary<Transform, Quaternion>();
        Quaternion headOffsetToCar, lEyeRestLocal, rEyeRestLocal;
        Vector3 restHipLocalPos;
        bool inited;
        Vector3 wheelCenter, wheelAxis, wheelU, wheelW; float wheelR;
        Quaternion wheelRestRot; Vector3 wheelRestPos;
        Vector3 wheelCenterL, wheelAxisL, wheelUL, wheelWL, wheelRestPosL; Quaternion wheelRestRotL;

        class HandInfo { public Vector3 fL, pL, palmCenterL, mid1L; public float len; }
        HandInfo lInfo, rInfo;

        readonly Dictionary<string, List<(SkinnedMeshRenderer smr, int idx)>> shapes = new Dictionary<string, List<(SkinnedMeshRenderer, int)>>();
        Vector2 eyeFrom, eyeTo, eyePos; float sacStart = -10f, sacDur = 0.05f;
        Vector2 headVel, headPos;
        System.Random rng;
        float nextBlink = 1.5f, blinkStart = -10f, blinkDur = 0.16f;
        bool speakingNow; float speechSwitch; float syllPhase; int viseme; float jawSmooth;
        static readonly string[] Visemes = { "V_Open", "V_Wide", "V_Tight_O", "V_Lip_Open", "V_Tight", "V_Explosive" };

        public static Transform Find(Transform root, string name)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true)) if (t.name == name) return t;
            return null;
        }

        public void Init()
        {
            var an = GetComponent<Animator>(); if (an) an.enabled = false;
            hip = Find(transform, "CC_Base_Hip"); spine01 = Find(transform, "CC_Base_Spine01"); spine02 = Find(transform, "CC_Base_Spine02");
            head = Find(transform, "CC_Base_Head"); neck1 = Find(transform, "CC_Base_NeckTwist01"); jawRoot = Find(transform, "CC_Base_JawRoot");
            lEye = Find(transform, "CC_Base_L_Eye"); rEye = Find(transform, "CC_Base_R_Eye");
            lThigh = Find(transform, "CC_Base_L_Thigh"); lCalf = Find(transform, "CC_Base_L_Calf"); lFoot = Find(transform, "CC_Base_L_Foot");
            rThigh = Find(transform, "CC_Base_R_Thigh"); rCalf = Find(transform, "CC_Base_R_Calf"); rFoot = Find(transform, "CC_Base_R_Foot");
            lUpper = Find(transform, "CC_Base_L_Upperarm"); lFore = Find(transform, "CC_Base_L_Forearm"); lHand = Find(transform, "CC_Base_L_Hand");
            rUpper = Find(transform, "CC_Base_R_Upperarm"); rFore = Find(transform, "CC_Base_R_Forearm"); rHand = Find(transform, "CC_Base_R_Hand");
            lTw1 = Find(transform, "CC_Base_L_ForearmTwist01"); lTw2 = Find(transform, "CC_Base_L_ForearmTwist02"); rTw1 = Find(transform, "CC_Base_R_ForearmTwist01"); rTw2 = Find(transform, "CC_Base_R_ForearmTwist02");
            lFingers.Clear(); rFingers.Clear();
            foreach (var fn in new[] { "Index", "Mid", "Ring", "Pinky", "Thumb" })
                for (int k = 1; k <= 3; k++)
                {
                    var a = Find(transform, "CC_Base_L_" + fn + k); if (a) lFingers.Add(a);
                    var b = Find(transform, "CC_Base_R_" + fn + k); if (b) rFingers.Add(b);
                }
            headOffsetToCar = Quaternion.Inverse(head.rotation) * (carRoot != null ? carRoot.rotation : transform.rotation);
            lEyeRestLocal = lEye.localRotation; rEyeRestLocal = rEye.localRotation;
            restLocal.Clear();
            var list = new List<Transform> { hip, spine01, spine02, head, neck1, lThigh, lCalf, lFoot, rThigh, rCalf, rFoot, lUpper, lFore, lHand, rUpper, rFore, rHand };
            if (jawRoot) list.Add(jawRoot);
            foreach (var tw in new[] { lTw1, lTw2, rTw1, rTw2 }) if (tw) list.Add(tw);
            list.AddRange(lFingers); list.AddRange(rFingers);
            foreach (var t in list) restLocal[t] = t.localRotation;
            restHipLocalPos = hip.localPosition;
            lInfo = Probe(lHand, lFingers); rInfo = Probe(rHand, rFingers);

            shapes.Clear();
            foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var m = smr.sharedMesh; if (m == null) continue;
                for (int i = 0; i < m.blendShapeCount; i++)
                {
                    string n = m.GetBlendShapeName(i);
                    if (!shapes.TryGetValue(n, out var l)) shapes[n] = l = new List<(SkinnedMeshRenderer, int)>();
                    l.Add((smr, i));
                }
            }
            SetupWheel();
            rng = new System.Random(seed);
            nextBlink = 1.5f; blinkStart = -10f; sacStart = -10f; eyePos = eyeFrom = eyeTo = Vector2.zero; headPos = Vector2.zero; headVel = Vector2.zero;
            speakingNow = false; speechSwitch = 0f;
            inited = true;
        }

        // hand geometry in the hand bone's local space: finger direction, palm direction (the way curled fingertips travel), palm centre, length
        HandInfo Probe(Transform hand, List<Transform> f)
        {
            var info = new HandInfo();
            Transform mid1 = f[3], mid3 = f[5], idx3 = f[2];
            info.fL = hand.InverseTransformDirection((mid1.position - hand.position).normalized);
            info.palmCenterL = hand.InverseTransformPoint(Vector3.Lerp(hand.position, mid1.position, 0.55f));
            info.mid1L = hand.InverseTransformPoint(mid1.position);
            Vector3 tipRest = mid3.position;
            var saved = new[] { f[3].localRotation, f[4].localRotation, f[5].localRotation };
            f[3].localRotation = saved[0] * Quaternion.AngleAxis(gripCurl.x, fingerAxis);
            f[4].localRotation = saved[1] * Quaternion.AngleAxis(gripCurl.y, fingerAxis);
            f[5].localRotation = saved[2] * Quaternion.AngleAxis(gripCurl.z, fingerAxis);
            Vector3 d = hand.InverseTransformDirection(mid3.position - tipRest);
            f[3].localRotation = saved[0]; f[4].localRotation = saved[1]; f[5].localRotation = saved[2];
            d -= Vector3.Project(d, info.fL);
            info.pL = d.normalized;
            info.len = Vector3.Distance(hand.position, idx3.position) + 0.025f;
            return info;
        }

        void SetupWheel()
        {
            if (steeringWheel == null) return;
            wheelRestRot = steeringWheel.rotation; wheelRestPos = steeringWheel.position;
            var rs = steeringWheel.GetComponentsInChildren<MeshRenderer>(true);
            Bounds b = new Bounds(); bool f = true;
            foreach (var r in rs) { if (f) { b = r.bounds; f = false; } else b.Encapsulate(r.bounds); }
            wheelCenter = b.center;
            var mf = rs[0].GetComponent<MeshFilter>(); Vector3 ext = mf.sharedMesh.bounds.extents;
            int thin = ext.x < ext.y ? (ext.x < ext.z ? 0 : 2) : (ext.y < ext.z ? 1 : 2);
            Vector3 la = thin == 0 ? Vector3.right : thin == 1 ? Vector3.up : Vector3.forward;
            wheelAxis = rs[0].transform.TransformDirection(la).normalized;
            if (Vector3.Dot(wheelAxis, -carRoot.forward) < 0) wheelAxis = -wheelAxis;
            wheelU = Vector3.ProjectOnPlane(carRoot.right, wheelAxis).normalized;
            wheelW = Vector3.Cross(wheelAxis, wheelU).normalized; if (Vector3.Dot(wheelW, carRoot.up) < 0) wheelW = -wheelW;
            float e0 = Mathf.Max(ext.x, ext.y, ext.z);
            var sc = rs[0].transform.lossyScale; wheelR = e0 * Mathf.Max(sc.x, sc.y, sc.z) * 0.92f;
            if (wheelR < 0.12f || wheelR > 0.30f) wheelR = 0.18f;
            wheelCenterL = carRoot.InverseTransformPoint(wheelCenter); wheelAxisL = carRoot.InverseTransformDirection(wheelAxis);
            wheelUL = carRoot.InverseTransformDirection(wheelU); wheelWL = carRoot.InverseTransformDirection(wheelW);
            wheelRestPosL = carRoot.InverseTransformPoint(wheelRestPos); wheelRestRotL = Quaternion.Inverse(carRoot.rotation) * wheelRestRot;
        }

        public void SetShape(string name, float w01)
        {
            if (!shapes.TryGetValue(name, out var l)) return;
            float w = Mathf.Clamp01(w01) * 100f;
            foreach (var (smr, idx) in l) smr.SetBlendShapeWeight(idx, w);
        }

        public void Tick(float time, float dt)
        {
            if (!inited) Init();
            UpdateGaze(time, dt);
            UpdateBlink(time);
            UpdateSpeech(time, dt);
            ApplyPose();
        }

        static void Aim(Transform bone, Transform child, Vector3 worldDir)
        {
            Vector3 cur = (child.position - bone.position).normalized;
            bone.rotation = Quaternion.FromToRotation(cur, worldDir.normalized) * bone.rotation;
        }

        void ApplyPose()
        {
            foreach (var kv in restLocal) kv.Key.localRotation = kv.Value;
            lEye.localRotation = lEyeRestLocal; rEye.localRotation = rEyeRestLocal;
            hip.localPosition = restHipLocalPos;
            Transform c = carRoot;
            hip.position = c.TransformPoint(hipPosCar);
            hip.rotation = Quaternion.AngleAxis(-leanBackDeg, c.right) * hip.rotation;
            Vector3 fwd = c.forward, up = c.up;
            Aim(lThigh, lCalf, fwd + up * 0.10f - c.right * 0.05f);
            Aim(rThigh, rCalf, fwd + up * 0.10f + c.right * 0.05f);
            Aim(lCalf, lFoot, fwd * 0.45f - up * 0.9f);
            Aim(rCalf, rFoot, fwd * 0.45f - up * 0.9f);
            lFoot.rotation = Quaternion.AngleAxis(-20f, c.right) * lFoot.rotation;
            rFoot.rotation = Quaternion.AngleAxis(-20f, c.right) * rFoot.rotation;

            head.rotation = Quaternion.AngleAxis(leanBackDeg * 0.9f, c.right) * head.rotation;
            Quaternion hq = Quaternion.AngleAxis(headPos.x, c.up) * Quaternion.AngleAxis(-headPos.y, c.right);
            neck1.rotation = Quaternion.Slerp(Quaternion.identity, hq, 0.3f) * neck1.rotation;
            head.rotation = Quaternion.Slerp(Quaternion.identity, hq, 0.7f) * head.rotation;
            // jaw bone: moves the lower teeth, tongue and the beard weights bound to it together with the jaw
            if (jawRoot) jawRoot.localRotation = restLocal[jawRoot] * Quaternion.AngleAxis(jawSmooth * jawMaxDeg, jawAxis);

            // steering wheel frame (re-derived from car-local constants every frame: the car moves)
            wheelCenter = c.TransformPoint(wheelCenterL); wheelAxis = c.TransformDirection(wheelAxisL);
            wheelU = c.TransformDirection(wheelUL); wheelW = c.TransformDirection(wheelWL);
            wheelRestPos = c.TransformPoint(wheelRestPosL); wheelRestRot = c.rotation * wheelRestRotL;
            Quaternion Q = Quaternion.AngleAxis(steerDeg, wheelAxis);
            if (steeringWheel != null)
            {
                steeringWheel.rotation = Q * wheelRestRot;
                steeringWheel.position = wheelCenter + Q * (wheelRestPos - wheelCenter);
            }
            PlaceHand(true, lUpper, lFore, lHand, lFingers, lInfo, leftHandAngleDeg, Q, 0f, 0f);
            PlaceHand(false, rUpper, rFore, rHand, rFingers, rInfo, rightHandAngleDeg, Q, reach, tap);
            ApplyEyes();
        }

        // ---- two-handed rim grasp, with an optional reach to the touchscreen (blend 0..1) ----
        void PlaceHand(bool left, Transform upper, Transform fore, Transform hand, List<Transform> fingers, HandInfo info, float angDeg, Quaternion Q, float reachBlend, float tapAmt)
        {
            Transform c = carRoot;
            float a = angDeg * Mathf.Deg2Rad;
            Vector3 rad = Q * (Mathf.Cos(a) * wheelU + Mathf.Sin(a) * wheelW);       // outward in the wheel plane
            Vector3 n = Q * wheelAxis;                                               // toward the driver
            Vector3 rim = wheelCenter + wheelR * rad;
            // grip frame: fingers point inward (slightly toward the front), palm faces the front of the rim
            Vector3 gf, gp;
            if (gripMode == 0) { gf = (-rad + (-n) * gripFingerTilt).normalized; gp = Vector3.ProjectOnPlane(-n, gf).normalized; }
            else { gf = ((-n) + (-rad) * gripFingerTilt).normalized; gp = Vector3.ProjectOnPlane(-rad, gf).normalized; }
            gp = Quaternion.AngleAxis(gripRollDeg * (left ? 1f : -1f), gf) * gp;
            Quaternion gripRot = Quaternion.LookRotation(gf, gp) * Quaternion.Inverse(Quaternion.LookRotation(info.fL, info.pL));
            Vector3 anchor = rim + rad * gripAnchorOut + n * gripAnchorRear;                  // where the finger bases (knuckle line) go
            Vector3 gripWrist = anchor - gripRot * (info.mid1L * hand.lossyScale.x);

            Vector3 wrist = gripWrist; Quaternion rot = gripRot; float idxCurl = 1f;
            bool reaching = reachBlend > 0.001f; Vector3 reachF = Vector3.forward, reachP = Vector3.up; float sBlend = 0f;
            if (reaching)
            {
                Vector3 touch = c.TransformPoint(touchTargetCar) + c.TransformDirection(touchNormalCar).normalized * (0.005f - 0.025f * tapAmt);
                Vector3 hover = touch + c.TransformDirection(touchNormalCar).normalized * 0.05f;
                Vector3 tip = Vector3.Lerp(hover, touch, tapAmt);
                Vector3 shoulder = upper.position;
                Vector3 rf = (tip - shoulder).normalized;
                Vector3 rp = Vector3.ProjectOnPlane(-c.up, rf).normalized;
                Quaternion reachRot = Quaternion.LookRotation(rf, rp) * Quaternion.Inverse(Quaternion.LookRotation(info.fL, info.pL));
                Vector3 reachWrist = tip - rf * info.len;
                float s = reachBlend * reachBlend * (3f - 2f * reachBlend);
                wrist = Vector3.Lerp(gripWrist, reachWrist, s); rot = Quaternion.Slerp(gripRot, reachRot, s); idxCurl = 1f - s;
                reachF = rf; reachP = rp; sBlend = s;
            }
            Vector3 pole = -c.up + (left ? -c.right : c.right) * 0.6f;
            TwoBone(upper, fore, hand, wrist, pole);
            if (reaching)
            {
                // choose the palm roll for the reach that needs the least forearm rotation (a real wrist cannot roll much beyond 90 degrees)
                float bestAbs = 1e9f; Quaternion bestRot = rot;
                foreach (float rollTry in new[] { -120f, -90f, -60f, -30f, 0f, 30f, 60f, 90f, 120f })
                {
                    Quaternion cand = Quaternion.LookRotation(reachF, Quaternion.AngleAxis(rollTry, reachF) * reachP) * Quaternion.Inverse(Quaternion.LookRotation(info.fL, info.pL));
                    hand.rotation = Quaternion.Slerp(gripRot, cand, sBlend);
                    float ab = Mathf.Abs(TwistOf(hand));
                    if (ab < bestAbs) { bestAbs = ab; bestRot = hand.rotation; }
                }
                rot = bestRot;
            }
            hand.rotation = rot;
            SpreadWristTwist(left, fore, hand, left ? lTw1 : rTw1, left ? lTw2 : rTw2);
            // fingers: wrap around the rim; during the reach the index finger extends, the others stay curled
            float gripAmt = gripAmount;
            for (int i = 0; i < fingers.Count; i++)
            {
                int finger = i / 3, joint = i % 3; float curl;
                if (finger == 4) curl = thumbCurl * (joint == 0 ? 0.6f : 1f);
                else
                {
                    curl = joint == 0 ? gripCurl.x : joint == 1 ? gripCurl.y : gripCurl.z; curl *= gripAmt * gripCurlScale;
                    if (finger == 0) curl *= idxCurl * 0.5f + (idxCurl < 1f ? 0f : 0.5f);      // index points, slightly bent
                    else if (reaching) curl *= Mathf.Lerp(1f, 0.30f + 0.12f * finger, sBlend);   // other fingers relax into a loose, graded curl (not a fist)
                }
                fingers[i].localRotation = fingers[i].localRotation * Quaternion.AngleAxis(curl * (left ? leftCurlSign : 1f), fingerAxis);
            }
        }

        // how well the fingers and palm surround the rim tube (used by the editor-side grip fit; lower is better)
        public float GripCost(bool left)
        {
            var hand = left ? lHand : rHand; var f = left ? lFingers : rFingers;
            float a = (left ? leftHandAngleDeg : rightHandAngleDeg) * Mathf.Deg2Rad;
            Quaternion Q = Quaternion.AngleAxis(steerDeg, wheelAxis);
            Vector3 T = wheelCenter + wheelR * (Q * (Mathf.Cos(a) * wheelU + Mathf.Sin(a) * wheelW));
            float Sq(float x) { return x * x; }
            float cost = 2f * Sq(Vector3.Distance(Vector3.Lerp(hand.position, f[3].position, 0.5f), T) - 0.034f);
            foreach (int i in new[] { 1, 4, 7, 10 }) cost += Sq(Vector3.Distance(f[i].position, T) - 0.026f);
            foreach (int i in new[] { 2, 5, 8, 11 }) cost += 0.5f * Sq(Vector3.Distance(f[i].position, T) - 0.026f);
            // wrap: the finger tips must sit on the far side of the rim tube from the palm (otherwise the hand just hovers over the rim)
            Vector3 toPalm = (hand.position - T).normalized;
            foreach (int i in new[] { 2, 5, 8, 11 })
            {
                float side = Vector3.Dot((f[i].position - T).normalized, toPalm);        // -1 = opposite the palm (wrapped)
                cost += 0.003f * Sq(Mathf.Max(0f, side + 0.2f));
            }
            // fingers must also reach the tube, not stop short of it
            foreach (int i in new[] { 2, 5, 8, 11 }) cost += 0.5f * Sq(Mathf.Max(0f, Vector3.Distance(f[i].position, T) - 0.03f));
            float tw = Mathf.Abs(left ? WristTwistL : WristTwistR);
            cost += 0.004f * Sq(Mathf.Max(0f, tw - 75f) / 45f);          // a real forearm cannot roll much beyond about 90 degrees
            return cost;
        }

        float TwistOf(Transform hand)
        {
            Quaternion d = hand.localRotation * Quaternion.Inverse(restLocal[hand]);
            Vector3 a = hand.localPosition.normalized;
            Vector3 v = Vector3.Project(new Vector3(d.x, d.y, d.z), a);
            float ang = 2f * Mathf.Atan2(Vector3.Dot(v, a), d.w) * Mathf.Rad2Deg;
            if (ang > 180f) ang -= 360f; if (ang < -180f) ang += 360f;
            return ang;
        }

        // The hand is rotated relative to the forearm; spread that roll over the forearm twist bones so the skin does not pinch at the wrist.
        void SpreadWristTwist(bool left, Transform fore, Transform hand, Transform tw1, Transform tw2)
        {
            if (tw1 == null || tw2 == null) return;
            Quaternion d = hand.localRotation * Quaternion.Inverse(restLocal[hand]);                 // hand rotation relative to its rest pose, in forearm space
            Vector3 a = hand.localPosition.normalized;                                               // forearm axis (forearm space)
            Vector3 v = Vector3.Project(new Vector3(d.x, d.y, d.z), a);
            float ang = 2f * Mathf.Atan2(Vector3.Dot(v, a), d.w) * Mathf.Rad2Deg;
            if (ang > 180f) ang -= 360f; if (ang < -180f) ang += 360f;
            if (left) WristTwistL = ang; else WristTwistR = ang;
            tw1.localRotation = Quaternion.AngleAxis(ang / 3f, a) * restLocal[tw1];
            tw2.localRotation = Quaternion.AngleAxis(ang / 3f, a) * restLocal[tw2];
        }

        static bool dbgLogged;
        static void TwoBone(Transform a, Transform b, Transform e, Vector3 target, Vector3 pole)
        {
            float la = Vector3.Distance(a.position, b.position), lb = Vector3.Distance(b.position, e.position);
            Vector3 toT = target - a.position;
            float d = Mathf.Clamp(toT.magnitude, 0.01f, la + lb - 0.001f);
            Vector3 dir = toT.normalized;
            float x = (d * d + la * la - lb * lb) / (2f * d);
            float h = Mathf.Sqrt(Mathf.Max(0f, la * la - x * x));
            Vector3 side = Vector3.ProjectOnPlane(pole, dir).normalized;
            Vector3 elbow = a.position + dir * x + side * h;
            Aim(a, b, elbow - a.position);
            Aim(b, e, target - b.position);
        }

        void UpdateGaze(float time, float dt)
        {
            Vector2 tgt = new Vector2(gazeIntent.z, gazeIntent.w);
            if ((tgt - eyeTo).magnitude > 0.6f)
            {
                eyeFrom = eyePos; eyeTo = tgt; sacStart = time;
                float amp = (eyeTo - eyeFrom).magnitude;
                sacDur = 0.022f + 0.0022f * amp;
                if (amp > 14f && time - blinkStart > 1.0f && rng.NextDouble() < 0.25) { blinkStart = time + 0.03f; blinkDur = 0.17f; }
            }
            float u = Mathf.Clamp01((time - sacStart) / sacDur); u = u * u * (3f - 2f * u);
            eyePos = Vector2.Lerp(eyeFrom, eyeTo, u);
            Vector2 jitter = new Vector2(0.30f * Mathf.Sin(time * 7.3f + seed) + 0.18f * Mathf.Sin(time * 13.1f), 0.25f * Mathf.Sin(time * 6.1f + 1.3f) + 0.12f * Mathf.Sin(time * 11.7f));
            EyeYaw = eyePos.x + jitter.x; EyePitch = eyePos.y + jitter.y;
            Vector2 ht = new Vector2(gazeIntent.x, gazeIntent.y);
            float st = 0.17f, w = 2f / st, x = w * dt, ex = 1f / (1f + x + 0.48f * x * x + 0.235f * x * x * x);
            Vector2 dv = headPos - ht; Vector2 tmp = (headVel + w * dv) * dt;
            headVel = (headVel - w * tmp) * ex; headPos = ht + (dv + tmp) * ex;
            HeadYaw = headPos.x; HeadPitch = headPos.y;
        }

        void ApplyEyes()
        {
            Quaternion face = head.rotation * headOffsetToCar;
            Quaternion delta = Quaternion.AngleAxis(EyeYaw, Vector3.up) * Quaternion.AngleAxis(-EyePitch, Vector3.right);
            Quaternion wd = face * delta * Quaternion.Inverse(face);
            lEye.rotation = wd * (lEye.parent.rotation * lEyeRestLocal);
            rEye.rotation = wd * (rEye.parent.rotation * rEyeRestLocal);
        }

        void UpdateBlink(float time)
        {
            if (time >= nextBlink && time - blinkStart > blinkDur)
            {
                blinkStart = time; blinkDur = 0.12f + (float)rng.NextDouble() * 0.08f;
                nextBlink = time + 2.5f + (float)rng.NextDouble() * 3.5f;
                if (rng.NextDouble() < 0.12) nextBlink = time + 0.35f;
            }
            float p = (time - blinkStart) / blinkDur, wgt = 0f;
            if (p >= 0f && p <= 1f) wgt = p < 0.35f ? Mathf.SmoothStep(0f, 1f, p / 0.35f) : Mathf.SmoothStep(1f, 0f, (p - 0.35f) / 0.65f);
            Blink01 = wgt;
            SetShape("Eye_Blink_L", wgt); SetShape("Eye_Blink_R", wgt);
        }

        void UpdateSpeech(float time, float dt)
        {
            float jawTarget = 0f; string v = null; float vw = 0f;
            if (!talking) { speakingNow = false; speechSwitch = time; }
            else
            {
                if (time >= speechSwitch)
                {
                    speakingNow = !speakingNow;
                    speechSwitch = time + (speakingNow ? 1.2f + (float)rng.NextDouble() * 1.8f : 0.35f + (float)rng.NextDouble() * 0.6f);
                }
                if (speakingNow)
                {
                    float prev = syllPhase;
                    syllPhase += dt * (4.0f + 1.2f * (float)System.Math.Sin(time * 1.7));
                    if (Mathf.Floor(syllPhase) != Mathf.Floor(prev)) viseme = rng.Next(Visemes.Length);
                    float a = Mathf.Pow(Mathf.Abs(Mathf.Sin(Mathf.PI * syllPhase)), 1.2f) * (0.65f + 0.35f * Mathf.PerlinNoise(time * 3.1f, seed));
                    jawTarget = 0.95f * a; v = Visemes[viseme]; vw = 0.45f * a;
                }
            }
            if (forceJaw >= 0f) { jawTarget = forceJaw; v = "V_Open"; vw = forceJaw; }
            jawSmooth = Mathf.Lerp(jawSmooth, jawTarget, 1f - Mathf.Exp(-dt * 30f));
            Jaw01 = jawSmooth;
            SetShape("Jaw_Open", jawSmooth * jawBlendshapeShare);          // the rest of the opening comes from the jaw bone (see ApplyPose)
            foreach (var n in Visemes) SetShape(n, n == v ? vw : 0f);
        }
    }
}
