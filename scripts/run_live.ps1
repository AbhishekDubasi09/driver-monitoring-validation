# Runs one live session: starts the Python receiver/analyser, then Unity in play mode, and records the dashboard window.
# Usage:  .\run_live.ps1                (visible dashboard window, also recorded to output\window_capture.mp4)
#         .\run_live.ps1 -NoWindow      (headless)
param(
    [Parameter(Mandatory = $true)][string]$UnityProject,   # path to the Unity project that contains unity/*.cs (see README)
    [string]$Out = (Join-Path (Split-Path $PSScriptRoot -Parent) 'output'),
    [string]$Unity = 'C:\Program Files\Unity\Hub\Editor\6000.0.60f1\Editor\Unity.exe',
    [switch]$NoWindow,
    [int]$TimeoutSec = 600
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$proj = (Resolve-Path $UnityProject).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$ff = & $py -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
New-Item -ItemType Directory -Force $Out | Out-Null
Remove-Item (Join-Path $Out 'window_capture.mp4') -ErrorAction SilentlyContinue

$pyArgs = @((Join-Path $root 'gazegrip\live_dms.py'), '--out', $Out)
if ($NoWindow) { $pyArgs += '--no-window' }
$pp = Start-Process $py -ArgumentList ($pyArgs | ForEach-Object { "`"$_`"" }) -PassThru `
      -RedirectStandardOutput (Join-Path $Out 'live_stdout.txt') -RedirectStandardError (Join-Path $Out 'live_stderr.txt')
Start-Sleep 3

$ua = @('-projectPath', $proj, '-logFile', (Join-Path $Out 'unity_live.log'), '-executeMethod', 'KevinLiveLauncher.Start', '-kdLive')
$up = Start-Process $Unity -ArgumentList ($ua | ForEach-Object { "`"$_`"" }) -PassThru

$rec = $null
if (-not $NoWindow) {
    # start recording the dashboard window once the first frames arrive
    for ($i = 0; $i -lt 240 -and -not $pp.HasExited; $i++) {
        $log = Join-Path $Out 'live_stdout.txt'
        if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'calibration done' -Quiet)) { break }
        Start-Sleep 1
    }
    $ra = @('-y', '-loglevel', 'error', '-f', 'gdigrab', '-framerate', '30', '-i', 'title=Driver Monitoring - Live',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', 'frag_keyframe+empty_moov',
            (Join-Path $Out 'window_capture.mp4'))
    $rec = Start-Process $ff -ArgumentList ($ra | ForEach-Object { "`"$_`"" }) -PassThru -WindowStyle Hidden
}
if (-not $pp.WaitForExit($TimeoutSec * 1000)) { 'TIMEOUT: stopping'; $pp.Kill() }
Start-Sleep 2
if ($rec -and -not $rec.HasExited) { $rec.Kill() }
Start-Sleep 3
if (-not $up.HasExited) { $up.Kill() }
Get-Content (Join-Path $Out 'live_stdout.txt') -Tail 30
