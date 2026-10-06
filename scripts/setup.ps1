# One-time setup: Python 3.11 virtual environment, MediaPipe model files and the JetBrains Mono font.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

$pkg = Join-Path $root 'gazegrip'
New-Item -ItemType Directory -Force (Join-Path $pkg 'models'), (Join-Path $pkg 'fonts') | Out-Null
curl.exe -sL -o (Join-Path $pkg 'models\face_landmarker.task') https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
curl.exe -sL -o (Join-Path $pkg 'models\hand_landmarker.task') https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
foreach ($w in 'Regular', 'Bold') {
    curl.exe -sL -o (Join-Path $pkg "fonts\JetBrainsMono-$w.ttf") "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-$w.ttf"
}
'Setup done.'
