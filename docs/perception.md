# Perception — detection and tracking

**Video in → YOLO person detection → ByteTrack tracking → overlay with track IDs and trajectories.**

```
OpenCvFrameSource ──▶ YoloDetector ──▶ ByteTrackTracker ──▶ draw_tracks ──▶ overlay.mp4
 (file/webcam/RTSP)   (Detector)       (Tracker)            (visualisation)   tracks.jsonl / summary.json
         └──────────── DefaultVisionPipeline (vision/pipeline) ────────────┘      driven by PerceptionRunner
```

| Piece | File |
|---|---|
| Source parsing (Windows paths, URLs, webcam) | `app/camera/infrastructure/source_spec.py` |
| Video / webcam / RTSP frames, strided reads, reconnect | `app/camera/infrastructure/opencv_source.py` |
| Person detector (+ warm-up, fp16 keyword resolution) | `app/vision/detection/yolo.py` |
| Tracker (per-camera ids `cam_01-T7`, bounded history) | `app/vision/tracking/bytetrack.py` |
| Hardware → model / input size / frame rate | `app/vision/profiles.py`, `app/shared/hardware.py` |
| Overlay (boxes, trails, zone, risk, HUD) | `app/vision/visualization/overlay.py` |
| Encoding and downscaling | `app/vision/media.py` |
| Runner (CLI / notebook entry) | `app/vision/runner.py`, `scripts/run_perception.py` |
| Environment doctor / notebook builder | `scripts/check_env.py`, `scripts/build_colab_notebook.py` |

Heavy libraries (OpenCV, Ultralytics, PyTorch) are imported **lazily** and only in allow-listed files
(enforced by `tests/unit/test_architecture_boundaries.py`), so the API, worker skeleton and test suite
run without them.

---

## Setup (Windows PowerShell, project at `C:\pbl_oceaneye`)

```powershell
cd C:\pbl_oceaneye
.\venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned
```

**CPU only (works everywhere, slow):**
```powershell
pip install -e ".[dev,vision]"
```

**NVIDIA GPU — do this *before* the line above.** `pip` on Windows installs a CPU-only PyTorch, so a
GPU needs PyTorch's CUDA wheel first. Check `nvidia-smi`, copy the command from
<https://pytorch.org/get-started/locally/> (Stable → Windows → Pip → your CUDA version), then:

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[dev,vision]"
python scripts\check_env.py --source "videos\clip.mp4"
```

No local GPU? Use the Colab notebook — same code on Google's GPU.

---

## Running it

```powershell
python scripts\run_perception.py --source "C:\Users\me\Videos\beach 01.mp4"
python scripts\run_perception.py --source clips\beach.mp4 --model yolov8s.pt --device cuda:0 --imgsz 1280 --show
python scripts\run_perception.py --source 0                                 # webcam
python scripts\run_perception.py --source rtsp://192.168.1.20:8080/live     # phone / CCTV
python scripts\run_perception.py --help
```

Paths with spaces, quotes pasted from Explorer, forward slashes, UNC paths and `%USERPROFILE%` all
work. The first run downloads the model into `models\` (needs internet). Output goes to
`outputs\perception\<video-name>_<timestamp>\`.

### Outputs

| File | Content |
|---|---|
| `overlay.mp4` | boxes, track ID + confidence, fading trajectories, HUD (frame, time, people, fps) |
| `tracks.jsonl` | one JSON object per processed frame — the dataset later stages consume |
| `summary.json` | source fps/size, frames, ms/frame and fps, unique IDs, max concurrent people, device, model, full config |

```json
{"v":1,"camera_id":"cam_01","frame_index":42,"video_time_s":2.8,"timestamp":"2026-10-02T07:27:31.5+00:00",
 "tracks":[{"track_id":"cam_01-T3","bbox":[x1,y1,x2,y2],"conf":0.87}]}
```

`bbox` is in pixels of the source frame. For recorded video `timestamp` is start-time + frame_index/fps
(reproducible); `video_time_s` is the time inside the video. With `--stride N`, `frame_index` still
refers to the original frame.

---

## How it sizes itself

Model, input size and frame rate default to **auto**: `app/shared/hardware.py` measures the machine and
`app/vision/profiles.py` turns those numbers into a profile. The policy is a pure function, so
`tests/unit/test_profiles_and_hardware.py` covers it on any machine.

| Device budget | Model | Input size | Analysed fps |
|---|---|---|---|
| CUDA, ≥ 6 GB per worker | `yolov8s.pt` | 960 | 8 |
| CUDA, ≥ 3 GB per worker (4 GB laptop GPU, one camera) | `yolov8s.pt` | 768 | 6 |
| CUDA, ≥ 1.5 GB per worker (two cameras sharing 4 GB) | `yolov8n.pt` | 640 | 6 |
| Apple GPU (mps) | `yolov8n.pt` | 640 | 5 |
| CPU, ≥ 8 cores | `yolov8n.pt` | 640 | 4 |
| CPU, ≥ 4 cores | `yolov8n.pt` | 512 | 3 |
| CPU, fewer | `yolov8n.pt` | 416 | 2 |

"Per worker" matters: VRAM is divided by how many workers the API expects to run. Two cameras on a 4 GB
GPU get a smaller profile than one — which is the difference between a demo that finishes and the
`cv2.error ... Insufficient memory` that ended an earlier one.

Any value set explicitly in `.env` or on the CLI wins for that field only.

---

## Two details that change what the numbers mean

**Warm-up.** The first CUDA inference costs seconds (weights load, cuDNN autotunes, kernels compile).
`YoloDetector.warmup()` pays that before the measured loop, so the first analysed frame is not a stall
and the reported frame rate describes steady state. A 24-frame job once reported 498 ms/frame; almost
all of it was the first frame.

**Evidence clips are downscaled.** The ring buffer holding the last seconds of annotated frames is
stored at `clip_max_width` (640–854 px), not full resolution. Six seconds of annotated 1080p at 6 fps
is about 220 MB *per worker*; the thumbnail still comes from the full-resolution frame.

---

## Experimental parameters (not requirements)

| Parameter | Default | Why |
|---|---|---|
| `model` | auto | n = fast, s/m = better on small swimmers |
| `imgsz` | auto | distant swimmers are tiny; larger helps, costs speed |
| `conf` | 0.10 | deliberately low so ByteTrack can use weak boxes to hold a track through a brief miss |
| `track_high/new_track_thresh` | 0.25 | ByteTrack defaults |
| `track_buffer` | 30 frames @ 30 fps (scaled to source fps) | how long a lost track survives |
| `history_len` | 150 | detections kept per track (trajectories now, behaviour features later) |

Tune these on real beach footage across calm and rough water, and write down what you chose and why.

---

## What this stage does **not** do

No danger zone, no breach logic, no distress signals, no risk score, no events — those are the worker
(`app/worker/session.py`). A COCO "person" model has never seen a swimmer: expect missed detections for
heads-only or partly submerged people, missed tiny distant people, glare and foam false positives, and
ID switches in crowds or when swimmers overlap. **These are the failure modes to measure on your own
footage before trusting anything built on top.** Camera placement — height, angle, resolution — limits
what any model can do.

---

## Colab GPU from Antigravity / VS Code

With a Colab runtime as the kernel, the code runs on Google's machine: it cannot see
`C:\pbl_oceaneye`, `files.upload()` never returns, and the `#@param` form UI does not exist. The
notebook needs none of them.

1. After any change in `app/`: `python scripts\build_colab_notebook.py` — rewrites
   `notebooks\OceanEye_Perception_Colab.ipynb` with the current code **embedded** (~210 KB).
2. Open it → select the **Colab** kernel (GPU) → *Run All*.
3. Step 4 prints the profile it chose, from the same policy the live worker uses.
4. Step 5 shows an **Upload** widget → pick clips from `videos\` → run the next cell.
   (Keep clips small, or use `VIDEO_URLS`.)
5. Step 10 gives a download link for `summary.json` and `tracks.jsonl` — the runtime is wiped on
   disconnect.

The same notebook with your local `venv` kernel detects `C:\pbl_oceaneye`, uses `videos\` directly and
writes to `outputs\` — no uploads.

---

## Troubleshooting (Windows)

| Symptom | Fix |
|---|---|
| `cuda: NOT available` in `check_env.py` | CPU-only torch is installed → reinstall the CUDA wheel, then `pip install -e ".[vision]"` |
| `could not open video source` | Check the path; try an ASCII-only path (OpenCV on Windows can fail on non-ASCII); try another file or codec |
| `cv2.error ... imshow ... not implemented` | You have `opencv-python-headless`; uninstall it and install `opencv-python`, or drop `--show` |
| `ModuleNotFoundError: ultralytics / cv2` | `pip install -e ".[vision]"` in the active venv |
| `AttributeError: VideoWriter_fourcc` | OpenCV 5 removed that name — use `app.vision.media._fourcc`, which handles both |
| Hundreds of `'half' is deprecated` lines | Fixed: the fp16 keyword is resolved once from the installed Ultralytics (`half_precision_keyword`) |
| Model download fails | The first run needs internet; or download the `.pt` manually and pass `--model C:\path\yolov8n.pt` |
| Very slow | Leave settings on auto; on CPU use `--stride 2`, or use the Colab GPU |
| Worker dies with "Insufficient memory" | Pinned settings are too large for the machine — set them back to `auto` / `0` |
