using System;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using KevinDriver;

/// <summary>Starts the live session: opens the scene, enters play mode; quits the editor when the scripted drive ends (when launched with -kdLive).</summary>
[InitializeOnLoad]
public static class KevinLiveLauncher
{
    static KevinLiveLauncher()
    {
        if (Array.IndexOf(Environment.GetCommandLineArgs(), "-kdLive") < 0) return;
        KevinLiveStreamer.SessionEnded -= OnEnd; KevinLiveStreamer.SessionEnded += OnEnd;
    }

    static void OnEnd() { Debug.Log("[KD] session ended, exiting editor"); EditorApplication.Exit(0); }

    public static void Start()
    {
        EditorSceneManager.OpenScene(KevinSceneBuilder.ScenePath);
        EditorApplication.EnterPlaymode();
    }
}
