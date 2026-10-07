# Contributing

Issues and pull requests are welcome.

The tests recompute every headline number from the saved session in `results/`, so they run without Unity, a camera or the
MediaPipe model files:

```bash
pip install -r requirements-analysis.txt -r requirements-dev.txt
python -m pyflakes driver_monitoring tests
python -m pytest tests
```

If you change the metric code, the regression tests will tell you which numbers moved. If a change is meant to move them,
update `results/` and say why in the pull request.

The most useful additions would be a second recorded session, a webcam input for the receiver, and a way to estimate vertical
gaze.
