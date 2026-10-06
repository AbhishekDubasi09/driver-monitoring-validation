using System.Text;
using UnityEditor;
using UnityEngine;

public static class KevinInspect
{
    public static void Run()
    {
        var sb = new StringBuilder();
        var kevin = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Kevin_Driver/Kevin/Kevin.fbx");
        var seen = new System.Collections.Generic.HashSet<Material>();
        foreach (var r in kevin.GetComponentsInChildren<Renderer>(true))
            foreach (var m in r.sharedMaterials)
            {
                if (m == null || !seen.Add(m)) continue;
                sb.AppendLine("MAT " + m.name + "  path=" + AssetDatabase.GetAssetPath(m) + "  shader=" + m.shader.name + " color=" + (m.HasProperty("_BaseColor") ? m.GetColor("_BaseColor").ToString() : "n/a"));
                var sh = m.shader;
                for (int i = 0; i < sh.GetPropertyCount(); i++)
                    if (sh.GetPropertyType(i) == UnityEngine.Rendering.ShaderPropertyType.Texture)
                    {
                        var t = m.GetTexture(sh.GetPropertyName(i));
                        if (t != null) sb.AppendLine("   " + sh.GetPropertyName(i) + " = " + AssetDatabase.GetAssetPath(t));
                    }
            }
        sb.AppendLine("--- shaders in project containing RL/Reallusion:");
        foreach (var g in AssetDatabase.FindAssets("t:Shader RL_"))
            sb.AppendLine(AssetDatabase.GUIDToAssetPath(g));
        System.IO.File.WriteAllText(System.IO.Path.Combine(System.IO.Path.GetTempPath(), "kevin_mats.txt"), sb.ToString());
    }
}
