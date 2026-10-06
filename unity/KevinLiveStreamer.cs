using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace KevinDriver
{
    /// <summary>
    /// Runs the scripted drive in real time (play mode) and streams the virtual cameras to a local Python process over TCP.
    /// Wire format per message: [int32 headerLen][int32 jpegLen][header JSON][JPEG bytes]. Camera ids: 0 face, 1 hands, 2 scene.
    /// This is a SIMULATED virtual camera on the same PC (no headset, no physical camera).
    /// </summary>
    public class KevinLiveStreamer : MonoBehaviour
    {
        public static event Action SessionEnded;
        public DriveScenario scenario;
        public Camera[] cams;
        public int[] widths = { 1280, 1024, 640 };
        public int[] heights = { 720, 576, 360 };
        public int port = 5555;
        public int jpegQuality = 85;
        public int fps = 24;

        RenderTexture[] rts;
        TcpClient client; NetworkStream stream;
        readonly Queue<byte[]> outQ = new Queue<byte[]>();
        Thread sender; volatile bool run = true;
        double t0 = -1; int frame; bool ended;
        readonly object qLock = new object();
        static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        bool connecting;

        void Start()
        {
            QualitySettings.vSyncCount = 0; Application.targetFrameRate = fps; Application.runInBackground = true;
            rts = new RenderTexture[cams.Length];
            for (int i = 0; i < cams.Length; i++)
            {
                rts[i] = new RenderTexture(widths[i], heights[i], 24, GraphicsFormat.R8G8B8A8_SRGB);
                cams[i].targetTexture = rts[i];
            }
            scenario.ResetScenario();
            sender = new Thread(SendLoop) { IsBackground = true }; sender.Start();
            StartCoroutine(Capture());
        }

        void SendLoop()
        {
            while (run)
            {
                if (client == null || !client.Connected)
                {
                    try { client = new TcpClient(); client.NoDelay = true; client.Connect("127.0.0.1", port); stream = client.GetStream(); }
                    catch { client = null; Thread.Sleep(500); continue; }
                }
                byte[] msg = null;
                lock (qLock) { if (outQ.Count > 0) msg = outQ.Dequeue(); }
                if (msg == null) { Thread.Sleep(2); continue; }
                try { stream.Write(msg, 0, msg.Length); } catch { try { client.Close(); } catch { } client = null; }
            }
        }

        bool Connected { get { return client != null && client.Connected; } }

        void Enqueue(byte[] m)
        {
            lock (qLock) { outQ.Enqueue(m); while (outQ.Count > 90) outQ.Dequeue(); }   // live: drop oldest if the consumer lags
        }

        IEnumerator Capture()
        {
            var wait = new WaitForEndOfFrame();
            double lastTick = Time.timeAsDouble;
            while (true)
            {
                if (!Connected) { yield return null; continue; }
                if (t0 < 0) { t0 = Time.timeAsDouble + 2.0; scenario.ResetScenario(); }     // 2 s warm-up after connect
                float t = (float)(Time.timeAsDouble - t0);
                float dt = Mathf.Clamp(Time.deltaTime, 0.001f, 0.1f);
                if (t >= 0f && !ended)
                {
                    scenario.Tick(t, dt);
                    if (t > scenario.sessionLength) { ended = true; Enqueue(Pack("{\"end\":true}", null)); StartCoroutine(Finish()); }
                }
                yield return wait;
                if (t < 0f || ended) continue;
                var gt = scenario.Gt; double unix = (DateTime.UtcNow - Epoch).TotalSeconds; int f = frame++;
                for (int i = 0; i < cams.Length; i++)
                {
                    int cam = i; var hdr = Header(f, cam, gt, unix);
                    AsyncGPUReadback.Request(rts[i], 0, TextureFormat.RGBA32, req =>
                    {
                        if (req.hasError) return;
                        NativeArray<byte> data = req.GetData<byte>();
                        byte[] jpg = ImageConversion.EncodeNativeArrayToJPG(data, GraphicsFormat.R8G8B8A8_SRGB, (uint)rts[cam].width, (uint)rts[cam].height, 0, jpegQuality).ToArray();
                        Enqueue(Pack(hdr, jpg));
                    });
                }
                yield return null;
            }
        }

        IEnumerator Finish()
        {
            yield return new WaitForSeconds(1.5f);
            run = false;
            if (SessionEnded != null) SessionEnded();
        }

        static string F(float v) { return v.ToString("0.####", CultureInfo.InvariantCulture); }

        string Header(int f, int cam, DriveScenario.GroundTruth g, double unix)
        {
            var sb = new StringBuilder(512);
            sb.Append("{\"f\":").Append(f).Append(",\"cam\":").Append(cam)
              .Append(",\"t\":").Append(F(g.t)).Append(",\"unix\":").Append(unix.ToString("0.0000", CultureInfo.InvariantCulture))
              .Append(",\"gt\":{")
              .Append("\"label\":\"").Append(g.label).Append("\",\"phase\":\"").Append(g.phase).Append("\",\"evt\":\"").Append(g.evt).Append("\",")
              .Append("\"cal\":").Append(g.cal ? 1 : 0).Append(",\"talking\":").Append(g.talking ? 1 : 0).Append(",\"ped\":").Append(g.pedActive ? 1 : 0)
              .Append(",\"speed\":").Append(F(g.speed)).Append(",\"steer\":").Append(F(g.steer)).Append(",\"ped_gap\":").Append(F(g.pedGap)).Append(",\"ped_yaw\":").Append(F(g.pedYaw)).Append(",\"ped_x\":").Append(F(g.pedX)).Append(",\"car_z\":").Append(F(g.carZ))
              .Append(",\"head_yaw\":").Append(F(g.headYaw)).Append(",\"head_pitch\":").Append(F(g.headPitch))
              .Append(",\"eye_yaw\":").Append(F(g.eyeYaw)).Append(",\"eye_pitch\":").Append(F(g.eyePitch))
              .Append(",\"blink\":").Append(F(g.blink)).Append(",\"jaw\":").Append(F(g.jaw)).Append(",\"reach\":").Append(F(g.reach)).Append("}}");
            return sb.ToString();
        }

        static byte[] Pack(string hdr, byte[] jpg)
        {
            byte[] h = Encoding.UTF8.GetBytes(hdr); int jl = jpg == null ? 0 : jpg.Length;
            byte[] m = new byte[8 + h.Length + jl];
            BitConverter.GetBytes(h.Length).CopyTo(m, 0); BitConverter.GetBytes(jl).CopyTo(m, 4);
            h.CopyTo(m, 8); if (jl > 0) jpg.CopyTo(m, 8 + h.Length);
            return m;
        }

        void OnDestroy() { run = false; try { client?.Close(); } catch { } }
    }
}
