using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using KevinDriver;

public static class KevinSceneBuilder
{
    public const string ScenePath = "Assets/Kevin_Driver/KevinDriver.unity";

    static Material Mat(Color c, float smooth = 0.1f)
    {
        var m = new Material(Shader.Find("Universal Render Pipeline/Lit")) { color = c };
        m.SetFloat("_Smoothness", smooth);
        return m;
    }

    static GameObject Box(string name, Vector3 pos, Vector3 scale, Material m, Transform parent)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Cube); g.name = name;
        Object.DestroyImmediate(g.GetComponent<Collider>());
        g.transform.SetParent(parent, false); g.transform.position = pos; g.transform.localScale = scale;
        g.GetComponent<Renderer>().sharedMaterial = m; g.isStatic = true;
        return g;
    }

    static void BuildWorld()
    {
        var root = new GameObject("World").transform;
        var asphalt = Mat(new Color(0.16f, 0.16f, 0.17f), 0.25f); var kerb = Mat(new Color(0.55f, 0.55f, 0.55f));
        var white = Mat(new Color(0.9f, 0.9f, 0.9f)); var grass = Mat(new Color(0.22f, 0.34f, 0.2f), 0f);
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane); ground.name = "Ground"; ground.transform.SetParent(root, false);
        ground.transform.position = new Vector3(0, -0.02f, 400); ground.transform.localScale = new Vector3(20, 1, 120); ground.GetComponent<Renderer>().sharedMaterial = grass;
        Box("Road", new Vector3(0, 0.0f, 400), new Vector3(8f, 0.04f, 900), asphalt, root);
        Box("SidewalkR", new Vector3(5.75f, 0.06f, 400), new Vector3(3.5f, 0.12f, 900), kerb, root);
        Box("SidewalkL", new Vector3(-5.75f, 0.06f, 400), new Vector3(3.5f, 0.12f, 900), kerb, root);
        Box("EdgeR", new Vector3(3.6f, 0.025f, 400), new Vector3(0.12f, 0.03f, 900), white, root);
        Box("EdgeL", new Vector3(-3.6f, 0.025f, 400), new Vector3(0.12f, 0.03f, 900), white, root);
        for (float z = -20; z < 840; z += 8f) Box("Dash", new Vector3(0, 0.03f, z), new Vector3(0.15f, 0.03f, 3f), white, root);
        // crosswalk where the pedestrian steps out is implied by the kerb; buildings and trees for optical flow / realism
        var rng = new System.Random(11);
        for (float z = -30; z < 840; z += 16f + rng.Next(0, 14))
            foreach (int side in new[] { -1, 1 })
            {
                float h = 6 + (float)rng.NextDouble() * 20f, w = 8 + (float)rng.NextDouble() * 8f, d = 10 + (float)rng.NextDouble() * 8f;
                float shade = 0.45f + (float)rng.NextDouble() * 0.3f;
                Box("Building", new Vector3(side * (13f + w * 0.5f), h * 0.5f, z), new Vector3(w, h, d), Mat(new Color(shade, shade * 0.97f, shade * 0.92f)), root);
            }
        var trunk = Mat(new Color(0.3f, 0.2f, 0.12f)); var leaf = Mat(new Color(0.18f, 0.4f, 0.18f));
        for (float z = -10; z < 840; z += 14f)
            foreach (int side in new[] { -1, 1 })
            {
                var t = GameObject.CreatePrimitive(PrimitiveType.Cylinder); Object.DestroyImmediate(t.GetComponent<Collider>()); t.transform.SetParent(root, false);
                t.transform.position = new Vector3(side * 8f, 1.5f, z); t.transform.localScale = new Vector3(0.3f, 1.5f, 0.3f); t.GetComponent<Renderer>().sharedMaterial = trunk;
                var c = GameObject.CreatePrimitive(PrimitiveType.Sphere); Object.DestroyImmediate(c.GetComponent<Collider>()); c.transform.SetParent(root, false);
                c.transform.position = new Vector3(side * 8f, 4f, z); c.transform.localScale = new Vector3(3f, 3f, 3f); c.GetComponent<Renderer>().sharedMaterial = leaf;
            }
    }

    static Camera MakeCam(string name, Transform parent, Vector3 localPos, Vector3 aimLocal, float fov)
    {
        var g = new GameObject(name); g.transform.SetParent(parent, false); g.transform.localPosition = localPos;
        g.transform.LookAt(parent.TransformPoint(aimLocal));
        var cam = g.AddComponent<Camera>(); cam.fieldOfView = fov; cam.nearClipPlane = 0.05f; cam.farClipPlane = 400f;
        cam.clearFlags = CameraClearFlags.Skybox;
        g.AddComponent<UnityEngine.Rendering.Universal.UniversalAdditionalCameraData>();
        return cam;
    }

    public static void Build()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        foreach (var go in scene.GetRootGameObjects()) if (go.GetComponent<Camera>() != null) Object.DestroyImmediate(go);
        BuildWorld();

        var carPrefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Main Car/Main Car.prefab");
        var car = (GameObject)PrefabUtility.InstantiatePrefab(carPrefab);
        car.name = "Main Car (sim)";
        car.transform.SetPositionAndRotation(new Vector3(2f, 0, 0), Quaternion.identity);
        foreach (var t in car.GetComponentsInChildren<Transform>(true)) if (t.name.StartsWith("XR Origin")) t.gameObject.SetActive(false);
        var ego = car.GetComponent<EGO_V1>(); if (ego) ego.enabled = false;
        var rb = car.GetComponent<Rigidbody>(); if (rb) { rb.isKinematic = true; rb.useGravity = false; }
        var gc = car.GetComponent<GaugeController>(); if (gc) gc.enabled = false;
        foreach (var a in car.GetComponents<AudioSource>()) a.enabled = false;
        foreach (var w in car.GetComponentsInChildren<WheelCollider>(true)) w.enabled = false;

        // Kevin
        var kevinPrefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Kevin_Driver/Kevin/Kevin.fbx");
        var kevin = (GameObject)PrefabUtility.InstantiatePrefab(kevinPrefab);
        kevin.name = "Kevin (driver)";
        kevin.transform.SetParent(car.transform, false);
        kevin.transform.localPosition = new Vector3(-0.38f, 0f, -0.28f); kevin.transform.localRotation = Quaternion.identity;
        FixKevinMaterials(kevin);
        var beh = kevin.AddComponent<KevinDriverBehaviour>();
        beh.carRoot = car.transform;
        var wheel = KevinDriverBehaviour.Find(car.transform, "RMCar26_SteeringWheel");
        beh.steeringWheel = wheel;

        // Cameras (virtual): face (driver monitoring), hands/wheel, exterior scene view
        var camFace = MakeCam("DMS_FaceCamera", car.transform, new Vector3(-0.38f, 1.20f, 0.62f), new Vector3(-0.38f, 1.13f, -0.10f), 38f);
        var camHands = MakeCam("DMS_HandCamera", car.transform, new Vector3(-0.32f, 1.36f, 0.00f), new Vector3(-0.30f, 0.95f, 0.42f), 72f);
        var camScene = MakeCam("SceneCamera", car.transform, new Vector3(4.5f, 2.6f, -7.5f), new Vector3(-1.5f, 0.9f, 8f), 50f);

        // Pedestrian (Kate with a walking loop)
        var kate = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Characters/Kate/Kate.fbx");
        GameObject ped = null; Animator pedAnim = null;
        if (kate != null)
        {
            ped = (GameObject)PrefabUtility.InstantiatePrefab(kate); ped.name = "Pedestrian (Kate)";
            ped.transform.position = new Vector3(5.5f, 0, 30f);
            AnimationClip clip = null;
            foreach (var o in AssetDatabase.LoadAllAssetsAtPath("Assets/Characters/Kate/walking.fbx")) if (o is AnimationClip c && !c.name.StartsWith("__preview")) clip = c;
            pedAnim = ped.GetComponent<Animator>(); if (pedAnim == null) pedAnim = ped.AddComponent<Animator>();
            if (clip != null)
            {
                var ctl = AnimatorController.CreateAnimatorControllerAtPath("Assets/Kevin_Driver/Materials/PedWalk.controller");
                var st = ctl.layers[0].stateMachine.AddState("walk"); st.motion = clip; ctl.layers[0].stateMachine.defaultState = st;
                pedAnim.runtimeAnimatorController = ctl; pedAnim.applyRootMotion = false;
            }
            ped.SetActive(false);
        }
        else Debug.LogWarning("[KD] Kate.fbx not found - no pedestrian");

        var sc = new GameObject("Scenario").AddComponent<DriveScenario>();
        sc.driver = beh; sc.car = car.transform; sc.pedestrian = ped ? ped.transform : null; sc.pedAnimator = pedAnim;
        var st2 = sc.gameObject.AddComponent<KevinLiveStreamer>();
        st2.scenario = sc; st2.cams = new[] { camFace, camHands, camScene };

        // cabin fill light (stand-in for ambient/IR illumination of a driver-monitoring camera; simulated)
        var fill = new GameObject("CabinFill").AddComponent<Light>();
        fill.transform.SetParent(car.transform, false); fill.transform.localPosition = new Vector3(-0.30f, 1.35f, 0.35f);
        fill.type = LightType.Point; fill.range = 4f; fill.intensity = 0.6f; fill.color = new Color(1f, 0.97f, 0.92f); fill.shadows = LightShadows.None;

        EditorSceneManager.SaveScene(scene, ScenePath);
        Debug.Log("[KD] scene built " + ScenePath);
    }

    // diffuse jpg has no alpha; the opacity lives in a separate jpg -> bake RGBA png
    static Texture2D BuildRgba(string diffusePath, string opacityPath)
    {
        string outPath = "Assets/Kevin_Driver/Materials/" + Path.GetFileNameWithoutExtension(diffusePath) + "_RGBA.png";
        var d = new Texture2D(2, 2, TextureFormat.RGBA32, false); d.LoadImage(File.ReadAllBytes(diffusePath));
        var o = new Texture2D(2, 2, TextureFormat.RGBA32, false); o.LoadImage(File.ReadAllBytes(opacityPath));
        var dp = d.GetPixels32(); var op = o.GetPixels32();
        if (o.width == d.width && o.height == d.height) for (int i = 0; i < dp.Length; i++) dp[i].a = op[i].r;
        d.SetPixels32(dp); d.Apply();
        File.WriteAllBytes(outPath, d.EncodeToPNG());
        AssetDatabase.ImportAsset(outPath);
        return AssetDatabase.LoadAssetAtPath<Texture2D>(outPath);
    }

    static void FixKevinMaterials(GameObject kevin)
    {
        const string matDir = "Assets/Kevin_Driver/Materials";
        Directory.CreateDirectory(matDir);
        var done = new System.Collections.Generic.HashSet<string>();
        foreach (var r in kevin.GetComponentsInChildren<Renderer>(true))
            foreach (var m in r.sharedMaterials)
            {
                if (m == null || !m.HasProperty("_BumpMap")) continue;
                var tex = m.GetTexture("_BumpMap"); if (tex == null) continue;
                string p = AssetDatabase.GetAssetPath(tex);
                if (!done.Add(p)) continue;
                var ti = AssetImporter.GetAtPath(p) as TextureImporter;
                if (ti != null && ti.textureType != TextureImporterType.NormalMap) { ti.textureType = TextureImporterType.NormalMap; ti.SaveAndReimport(); }
            }
        foreach (var r in kevin.GetComponentsInChildren<Renderer>(true))
        {
            var src = r.sharedMaterials; var dst = new Material[src.Length];
            for (int i = 0; i < src.Length; i++)
            {
                var m = src[i]; if (m == null) continue;
                var c = new Material(m); c.name = m.name; string n = m.name;
                if (n == "Hair_Transparency" || n == "Scalp_Transparency")
                {
                    var rgba = BuildRgba("Assets/Kevin_Driver/Kevin/Kevin.fbm/" + n + "_Diffuse.jpg", "Assets/Kevin_Driver/Kevin/Kevin.fbm/" + n + "_Opacity.jpg");
                    c.SetTexture("_BaseMap", rgba); c.SetTexture("_MainTex", rgba);
                }
                if ((n.Contains("Transparency") && n != "Scalp_Transparency") || n.Contains("Eyelash"))
                {
                    c.SetFloat("_AlphaClip", 1f); c.SetFloat("_Cutoff", 0.4f); c.EnableKeyword("_ALPHATEST_ON");
                    c.SetFloat("_Cull", 0f); c.renderQueue = 2450; c.SetFloat("_Smoothness", 0.2f);
                }
                else if (n.Contains("Cornea") || n.Contains("Tearline") || n.Contains("Occlusion") || n == "Scalp_Transparency")
                {
                    c.SetFloat("_AlphaClip", 1f); c.SetFloat("_Cutoff", 1.5f); c.EnableKeyword("_ALPHATEST_ON"); c.renderQueue = 2450;
                }
                else if (n.Contains("Std_Skin")) { c.SetFloat("_Smoothness", 0.35f); }
                else if (n == "Std_Eye_L" || n == "Std_Eye_R")
                {
                    c.SetFloat("_Metallic", 0f); c.SetFloat("_Smoothness", 0.45f);
                    c.SetColor("_EmissionColor", Color.black); c.DisableKeyword("_EMISSION");
                    c.SetColor("_BaseColor", new Color(0.85f, 0.85f, 0.85f, 1f));
                }
                AssetDatabase.CreateAsset(c, AssetDatabase.GenerateUniqueAssetPath(matDir + "/" + n + "_" + r.name + ".mat"));
                dst[i] = c;
            }
            r.sharedMaterials = dst;
        }
        // lift the T-shirt a few millimetres along its normals so the shoulder skin does not poke through when the arms move
        foreach (var smr in kevin.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (smr.name != "Basic_T_shirts" || smr.sharedMesh == null) continue;
            var m = Object.Instantiate(smr.sharedMesh); var v = m.vertices; var nrm = m.normals;
            for (int i = 0; i < v.Length; i++) v[i] += nrm[i] * 0.007f;
            m.vertices = v; m.RecalculateBounds();
            AssetDatabase.CreateAsset(m, AssetDatabase.GenerateUniqueAssetPath(matDir + "/ShirtOffset.asset"));
            smr.sharedMesh = m;
        }
        AssetDatabase.SaveAssets();
    }
}
