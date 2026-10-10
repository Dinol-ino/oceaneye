# OceanEye prototype — run book

Everything runs on **one Windows PC** (`C:\pbl_oceaneye`). Phones on the same Wi-Fi open the lifeguard
app; with HTTPS on, they install it and get alerts while it is closed.

## What is in the prototype

| Module | Implementation |
|---|---|
| Camera / ingestion | Uploaded clips replayed as **simulated CCTV**, RTSP/HTTP cameras (phone apps, IP CCTV) with automatic reconnect, webcam via CLI |
| Detection + tracking | YOLO (Ultralytics) + ByteTrack, one **worker process per camera / job**, model warmed up before the clock starts |
| Deployment site | One **active beach** per installation; one search box (Geoapify places) with full addresses and coordinates, manual entry when the lookup is unavailable |
| Danger zone & risk | Static polygon per camera (drawn in the dashboard) → behaviour rules (prolonged stillness, vertical bobbing, erratic movement, repeated submersion) → persistence + cooldown → risk score; rough sea raises it slightly |
| Alert & escalation | Candidate events with evidence thumbnail + H.264 clip → WebSocket + Web Push → acknowledgement deadline → automatic escalation |
| Control room (PC) | `/ui/control.html` — beach picker, camera wall, zone editor, incidents, map, sea state, **video analysis**, alerting panel, history, metrics. The whole PC side in one page |
| Lifeguard app | `/ui/lifeguard.html` — alarm, vibration, OS notification while closed, evidence image, Acknowledge, Navigate, Resolved / False alarm |
| Video analysis | Control room → **Video analysis** — upload, run the full chain, watch the annotated result, convert a clip into a simulated camera. (`/ui/analysis.html` redirects there.) |
| Storage | SQLite (`data/oceaneye.db`), evidence `data/evidence`, uploads `data/uploads`, job output `data/jobs`, worker logs `data/logs` |
| External data | Open-Meteo forecast + marine (no key); Geoapify place search and map tiles (one free key, proxied so it never reaches a browser). All cached, all degrade to a stated reason offline |

```
 videos / RTSP ─▶ worker process (python -m app.worker.cli)              API process (FastAPI)
                  YOLO ─▶ ByteTrack ─▶ zone ─▶ behaviour ─▶ risk  ──HTTP──▶ events ─▶ alerts ─┬─▶ WebSocket ─▶ Control room
                  evidence (thumb + clip) · live frames · progress        ▲ escalation timer  └─▶ Web Push ──▶ Lifeguard phone
                                                                          └── uploads, jobs, metrics, weather, beaches, zones
```

---

## Setup (once)

```powershell
cd C:\pbl_oceaneye
.\venv\Scripts\Activate.ps1
pip install -e ".[dev,vision,push,tls]"
Copy-Item .env.example .env -Force
pytest                                   # expect everything to pass
```

### GPU

`pip` installs a **CPU-only** PyTorch from PyPI, so a GPU needs PyTorch's CUDA wheel first:

```powershell
nvidia-smi                                            # note the CUDA version
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -c "import torch; print(torch.cuda.is_available())"   # must print True
python scripts\check_env.py
```

**Leave the worker settings on `auto`.** OceanEye measures the GPU and picks the model, input size,
frame rate and worker count itself. On a 4 GB laptop GPU that is `yolov8s @ 768` with one worker, or
`yolov8n @ 640` when two cameras share it. Pinning `yolov8s @ 960` with two workers is what ran this
machine out of memory (`cv2.error ... Insufficient memory`) — if you pin values, pin them downwards.

No usable GPU? Everything still runs on the CPU, slower, and the Colab notebook gives you a free one.

---

## Run the demo

```powershell
python scripts\run_api.py --lan          # keep this window open
# second terminal (venv active):
python scripts\seed_demo.py --start 1    # uploads videos\*.mp4 as simulated CCTV, starts 1 worker
```

Open <http://127.0.0.1:8000> → **Control Room**. Windows may ask to allow Python through the firewall —
allow it on private networks.

### Suggested flow (about 5 minutes)

1. **Deployment site** — the beach, its address, its coordinates, its authority, lifeguards on duty,
   camera count. Press **Change beach**, type a town, pick a beach: the same software configures for
   any coastline, with nothing hardcoded.
2. **Camera wall** — live overlays: boxes, track IDs, trails, the red danger zone, risk badges, people
   count, frames per second, and which model and device are actually running.
3. **Zone** — redraw the danger zone on a camera, save, Stop then Start monitoring to apply it.
4. **Map & sea state** — camera markers, neighbouring beaches, waves / wind / tide and a 12-hour
   forecast. The beach's coordinates are printed above the map, not just implied by the view.
5. **Alert** — wait for a candidate event, or press **Demo alert** (clearly labelled DEMO). The
   lifeguard phone rings → **Acknowledge** → the control room shows the acknowledgement and the
   time-to-acknowledge metric. Leave one unacknowledged for 30 s to show automatic escalation.
6. **Close the loop** — mark Resolved or False alarm; the false-alarm rate updates. Say that these
   outcomes are the project's only labelled data.
7. **Alerting** — the three indicators (https, push configured, phones registered) and
   **Send test alert to phones**: the phone buzzes with "OceanEye test alert", and no incident is
   created. This is how you prove the PC reaches the phone before a shift.
8. **Video analysis** — further down the same page: upload a clip, run it, watch the annotated
   result, show the events it created — which arrive on the lifeguard phone exactly like live ones.

---

## Phones

### Without HTTPS (nothing to set up)

The pages work. Alerts sound and vibrate **only while the app is open and the screen is on**. The app
cannot be installed to the home screen. This is a browser rule, not a missing feature.

### With HTTPS (installable + alerts while closed)

```powershell
python scripts\make_certs.py        # certificate for localhost + this PC's Wi-Fi address
python scripts\make_push_keys.py    # VAPID key pair
```

Paste the lines each one prints into `.env`, restart `run_api.py`, then on the phone:

1. Open `https://<the IP printed by run_api.py>:8000/ui/lifeguard.html`.
2. The phone warns that the certificate is not trusted — **Advanced → Proceed**. Once per device.
   (Expected: the certificate is self-signed. It encrypts the connection but proves no identity.)
3. Tap **Turn on alerts** and allow notifications.
4. Browser menu → **Add to Home screen** / **Install app**.

Lock the phone and press **Demo alert** in the control room: the phone should ring with the screen off.
The Control Room and Video Analysis install the same way, each as its own app.

**Check what is actually on:** the lifeguard app says so under the button, and
`/api/config/public` reports `capabilities.secure_context` and `capabilities.web_push`.

---

## Performance & response (Control Room → "Performance & response")

* **Detection** — per-camera frames per second and ms/frame, job pipeline rate, frames processed,
  people in view, which model and device ran, and the machine's own GPU/CPU.
* **Response** — time to acknowledge (mean / median / p90 / max), escalated share, outcome counts,
  false-alarm rate (false alarms ÷ closed events), signals seen.

Reported rates exclude model warm-up, which is paid once before the measured loop. A 24-frame job that
appeared to run at 2 fps was really spending 12 of its 13 seconds loading CUDA kernels.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Camera stays "starting" | First run downloads the model (needs internet) — see `data\logs\worker_cam_<id>.log` |
| "worker limit reached" | This machine's slot count is in the Control Room ("this machine"). Stop a camera, or raise `OCEANEYE_MAX_WORKERS` only if you are sure |
| PC slows down or a worker dies with "Insufficient memory" | You have pinned worker settings. Set `OCEANEYE_WORKER_MODEL`, `_IMGSZ`, `_TARGET_FPS` and `OCEANEYE_MAX_WORKERS` back to `auto` / `0` |
| Phone gets no sound | Tap "Turn on alerts" once; keep the screen on if you are on plain HTTP |
| Phone gets nothing while the app is closed | Needs HTTPS **and** VAPID keys — see **Phones** above |
| "Add to home screen" missing | Needs HTTPS. Check `/api/config/public` → `capabilities.secure_context` |
| Certificate warning every time | Expected on a self-signed certificate; accept it once per device |
| Place search returns nothing | The response says why. No key → set `OCEANEYE_GEOAPIFY_API_KEY`; 401 → the key is wrong; "unreachable" → no internet. Type the beach in by hand meanwhile |
| Map blank | Tiles are proxied through `/api/map/tiles/...`; they need the Geoapify key and internet. The Leaflet library also loads from a CDN |
| "Send test alert" says not delivered | Read the detail line: no phones registered, push not configured (no VAPID keys / no https), or the push service rejected the device |
| Zone change not applied | Stop and Start monitoring — workers read the zone when they start |
| Events on every replay of the same clip | Should not happen: the cooldown survives a loop. If it does, that is a bug — see `tests/unit/test_worker_session.py::test_cooldown_survives_a_looping_source` |

---

## Notebook

`notebooks\OceanEye_Perception_Colab.ipynb` runs the same worker chain offline (no API): detection,
tracking, zone, risk, events with evidence. It uses the **same** profile policy as the live worker, so
what you measure there transfers. Rebuild after code changes:

```powershell
python scripts\build_colab_notebook.py
```
