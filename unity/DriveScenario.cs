using UnityEngine;

namespace KevinDriver
{
    /// <summary>
    /// Scripted ~58 s test drive (SIMULATION): calibration -> baseline -> hazard 1 (attentive) -> conversation with an
    /// off-screen passenger -> hazard 2 (while talking and looking at the passenger) -> recovery.
    /// Reaction latencies (L1, L2) are simulation parameters chosen by the experimenter, not measured human data.
    /// </summary>
    public class DriveScenario : MonoBehaviour
    {
        public KevinDriverBehaviour driver;
        public Transform car, pedestrian;
        public Animator pedAnimator;
        public float sessionLength = 58f;
        public float cruise = 9f;
        public float H1 = 22f, H2 = 46f;
        public float L1 = 0.45f, L2 = 1.05f;           // simulated gaze-reaction latencies (s)
        public float laneX = 2f;

        public struct GroundTruth
        {
            public float t, speed, carZ, steer, pedX, pedZ, pedGap, pedYaw;
            public string label, phase, evt;
            public bool cal, pedActive, talking;
            public float headYaw, headPitch, eyeYaw, eyePitch, blink, jaw;
            public float gazeYaw => headYaw + eyeYaw;
            public float reach;
        }
        public GroundTruth Gt;

        float carZ, speed;
        float[] onset = new float[2];
        bool[] fired = new bool[2];
        float[] lat; float[] brakeAt = { -1, -1 }; float[] pedStart = { -1, -1 };
        float pedX, pedZ; bool pedActive; int activeHaz = -1; float pedWalkSpeed = 1.5f;
        string pendingEvt = "";

        static readonly Vector4 Road = new Vector4(0, 0, 0, 0);
        static readonly Vector4 LeftMirror = new Vector4(-9, 0, -20, -1);
        static readonly Vector4 Passenger = new Vector4(22, 0, 16, -2);
        static readonly Vector4 HazardCal = new Vector4(5, 0, 9, 0);

        static float ReachProfile(float t, float t0, float t1)
        {
            const float ramp = 0.9f;
            if (t < t0 || t > t1) return 0f;
            return Mathf.Clamp01(Mathf.Min((t - t0) / ramp, (t1 - t) / ramp));
        }
        static float Pulse(float t, float t0, float w) { float u = (t - t0) / w; return (u < 0f || u > 1f) ? 0f : Mathf.Sin(u * Mathf.PI); }

        public void ResetScenario()
        {
            carZ = 0; speed = cruise; pedActive = false; activeHaz = -1; fired[0] = fired[1] = false;
            brakeAt[0] = brakeAt[1] = -1; pedStart[0] = pedStart[1] = -1;
            onset[0] = H1; onset[1] = H2; lat = new[] { L1, L2 };
            Place();
        }

        Vector3 EyeWorld() { return car.TransformPoint(new Vector3(-0.38f, 1.17f, -0.07f)); }

        float PedYaw()
        {
            Vector3 e = EyeWorld(); return Mathf.Atan2(pedX - e.x, pedZ - e.z) * Mathf.Rad2Deg;
        }

        Vector4 HazardIntent()
        {
            float y = Mathf.Clamp(Mathf.Max(11f, PedYaw()), 11f, 25f);     // driver fixates the hazard side (>= 11 deg right)
            return new Vector4(0.35f * y, 0, 0.65f * y, 0);
        }

        void Place()
        {
            car.position = new Vector3(laneX, 0, carZ);
            if (pedestrian)
            {
                pedestrian.gameObject.SetActive(pedActive);
                pedestrian.position = new Vector3(pedX, 0, pedZ);
                pedestrian.rotation = Quaternion.LookRotation(new Vector3(-1, 0, 0));
            }
        }

        public void Tick(float t, float dt)
        {
            // ---- gaze intent timeline ----
            Vector4 intent = Road; string label = "road"; string phase;
            bool cal = t < 12f;
            if (t < 12f)
            {
                phase = "calibration";
                if (t < 2) { intent = Road; label = "road"; }
                else if (t < 4) { intent = LeftMirror; label = "left_mirror"; }
                else if (t < 6) { intent = Passenger; label = "passenger"; }
                else if (t < 8) { intent = HazardCal; label = "hazard_right"; }
                else { intent = Road; label = "road"; }
            }
            else if (t < H1 + 0.001f) { phase = "baseline"; if (t > 15f && t < 16.2f) { intent = LeftMirror; label = "left_mirror"; } }
            else if (t < 27f) phase = "hazard1";
            else if (t < 50f) phase = "conversation";
            else phase = "recovery";

            if (t >= 29f && t < 31f || t >= 34f && t < 36.2f || t >= 39.5f && t < 41.5f || t >= 45f && t < 47.6f) { intent = Passenger; label = "passenger"; }
            if (t >= 53f && t < 54.2f) { intent = LeftMirror; label = "left_mirror"; }

            // ---- hazards ----
            for (int h = 0; h < 2; h++)
            {
                if (!fired[h] && t >= onset[h])
                {
                    fired[h] = true; activeHaz = h; pedActive = true; pedX = 6.8f; pedZ = carZ + 24f; pedStart[h] = t;
                    pendingEvt = "HAZARD_ONSET_" + (h + 1);
                    if (pedAnimator) pedAnimator.speed = 1f;
                }
            }
            if (pedActive)
            {
                pedX -= pedWalkSpeed * dt;
                if (pedX < -5.5f) { pedActive = false; }
            }
            for (int h = 0; h < 2; h++)
            {
                if (!fired[h]) continue;
                float g0 = onset[h] + lat[h];
                if (t >= g0 && t < g0 + 1.9f) { intent = HazardIntent(); label = "hazard_right"; }
                if (brakeAt[h] < 0 && t >= g0 + 0.25f) brakeAt[h] = t;
            }
            // ---- car speed: brake after the driver's reaction, resume once the pedestrian has cleared the lane ----
            // only the currently active hazard can trigger braking (a stale timestamp from hazard 1 must not brake for hazard 2)
            bool braking = activeHaz >= 0 && brakeAt[activeHaz] >= 0 && t >= brakeAt[activeHaz] && pedActive && pedX > laneX - 1.6f;
            if (braking) speed = Mathf.Max(0f, speed - 5.5f * dt); else speed = Mathf.Min(cruise, speed + 2.5f * dt);
            carZ += speed * dt;

            // ---- steering: small lane-keeping corrections + a drift while distracted ----
            float steer = 3.0f * Mathf.Sin(t * 0.55f) + 1.2f * Mathf.Sin(t * 1.9f + 1f);
            if (t > 29f && t < 48f) steer += 2.0f * Mathf.Sin(t * 0.8f + 2f);

            bool talk = t >= 27.5f && t < 48.5f;
            // ---- secondary manual task: right hand reaches to the centre touchscreen (eyes stay on the road) ----
            float reachBlend = Mathf.Max(ReachProfile(t, 17.0f, 20.4f), ReachProfile(t, 54.0f, 57.0f));
            float tapAmt = Mathf.Max(Pulse(t, 18.4f, 0.28f), Pulse(t, 19.0f, 0.28f), Pulse(t, 55.4f, 0.28f), Pulse(t, 56.0f, 0.28f));
            driver.reach = reachBlend; driver.tap = tapAmt;
            driver.gripAmount = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01((t - 2.0f) / 2.0f));      // open hands for the first 2 s, then grasp

            driver.carRoot = car;
            driver.gazeIntent = intent; driver.talking = talk; driver.steerDeg = steer;
            Place();
            driver.Tick(t, dt);

            float gap = pedActive ? pedZ - (carZ + 2.2f) : 99f;
            Gt = new GroundTruth
            {
                t = t, speed = speed, carZ = carZ, steer = steer, pedX = pedX, pedZ = pedZ, pedGap = gap, pedYaw = pedActive ? PedYaw() : 0f,
                label = label, phase = phase, evt = pendingEvt, cal = cal, pedActive = pedActive, talking = talk,
                headYaw = driver.HeadYaw, headPitch = driver.HeadPitch, eyeYaw = driver.EyeYaw, eyePitch = driver.EyePitch, blink = driver.Blink01, jaw = driver.Jaw01, reach = reachBlend
            };
            pendingEvt = "";
        }
    }
}
