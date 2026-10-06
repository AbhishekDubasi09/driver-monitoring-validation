# Runs a static C# editor method of the Unity project in Unity batch mode and waits for it to finish.
# Usage:  .\run_unity.ps1 -Method KevinSceneBuilder.Build
#         .\run_unity.ps1 -Method KevinRecorder.Shots -Extra @('-kdT','8','-kdHi','1','-kdOut','C:\temp\shots')
param(
    [Parameter(Mandatory = $true)][string]$UnityProject,
    [Parameter(Mandatory = $true)][string]$Method,
    [string]$Unity = 'C:\Program Files\Unity\Hub\Editor\6000.0.60f1\Editor\Unity.exe',
    [int]$TimeoutSec = 1500,
    [string[]]$Extra = @(),
    [switch]$NoQuit
)
$proj = (Resolve-Path $UnityProject).Path
$log = Join-Path $env:TEMP ("unity_" + ($Method -replace '\W', '_') + ".log")
$a = @('-batchmode', '-projectPath', $proj, '-logFile', $log, '-executeMethod', $Method)
if (-not $NoQuit) { $a += '-quit' }
$a += $Extra
$pr = Start-Process $Unity -ArgumentList ($a | ForEach-Object { "`"$_`"" }) -PassThru
if (-not $pr.WaitForExit($TimeoutSec * 1000)) { $pr.Kill(); 'TIMEOUT' }
"exit $($pr.ExitCode)  log $log"
Select-String -Path $log -Pattern 'error CS|Exception|\[KD\]' | Select-Object -First 25 | ForEach-Object Line
