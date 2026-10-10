# OceanEye — testing guide

How to prove, by hand, that every part of OceanEye works: the API, all three interfaces, the
detection pipeline, the alert path, and a real phone.

**Nothing in here is hardcoded.** Every id you need (beach, camera, upload, job, event, alert) is
read out of an earlier response. The Postman collection does this automatically; the curl examples
show you how to do it yourself.

| | |
|---|---|
| Postman collection | `docs/postman/OceanEye.postman_collection.json` |
| Postman environment | `docs/postman/OceanEye.postman_environment.json` |
| 83 requests, 306 assertions | all passing against a clean server |

---

## Contents

1. [Before you start](#1-before-you-start)
2. [How authentication works (read this first)](#2-how-authentication-works-read-this-first)
3. [Postman setup](#3-postman-setup)
4. [Health and configuration](#4-health-and-configuration)
5. [Module 1 — Control Room](#5-module-1--control-room)
6. [Module 2 — Video Analysis](#6-module-2--video-analysis)
7. [Module 3 — Lifeguard app](#7-module-3--lifeguard-app)
8. [The beach (deployment site)](#8-the-beach-deployment-site)
9. [The alert path, end to end](#9-the-alert-path-end-to-end)
10. [Simulating a worker without a GPU](#10-simulating-a-worker-without-a-gpu)
11. [WebSocket (live alerts)](#11-websocket-live-alerts)
12. [Phone testing](#12-phone-testing)
13. [Security tests](#13-security-tests)
14. [Running it all from the command line](#14-running-it-all-from-the-command-line)
15. [Endpoint reference](#15-endpoint-reference)
16. [When something fails](#16-when-something-fails)

---

## 1. Before you start

```powershell
cd C:\pbl_oceaneye
.\venv\Scripts\Activate.ps1
pip install -e ".[dev,vision,push,tls]"
pytest                                   # 197 tests should pass (195 if vision extras omitted)
python scripts\run_api.py --lan
```

Leave that window open. It prints the URLs you need:

```
  OceanEye 0.3.0
  Machine        8 cpu, 5.9 GB RAM, NVIDIA GeForce RTX 2050 (4.0 GB VRAM)  ->  2 worker slot(s)
  Control Room   https://127.0.0.1:8000/
  Lifeguard app  https://172.17.1.13:8000/ui/lifeguard.html   (same Wi-Fi)
  Video analysis https://172.17.1.13:8000/ui/analysis.html
```

Write down that LAN address. You need it for phone testing.

> **Check your `.env` first.** If it says `OCEANEYE_MAX_WORKERS=5` on a 4 GB laptop GPU, the server
> now warns you at startup. Set it to `0` (auto) or `2`. An explicit value overrides the safety
> policy, and more workers than the memory supports is what crashes a run mid-demo.

### A clean slate

Many of these tests create data. To start fresh at any point:

```powershell
# stop the server first (Ctrl+C)
Remove-Item data\oceaneye.db
python scripts\run_api.py --lan
```

The beach from `.env` is recreated automatically on the next start.

---

## 2. How authentication works (read this first)

Every protected endpoint needs a role. In development that is a plain header:

```
X-Dev-Role: operator | lifeguard | administrator | service
X-Dev-User: your name        (optional; it is who gets recorded as acknowledging an event)
```

**This is not security.** It exists so the role boundaries can be built and tested before a real
identity provider is wired in. The server refuses to start with `auth_mode=dev` when
`OCEANEYE_ENVIRONMENT=production`.

Who may do what:

| Role | Can |
|---|---|
| `lifeguard` | See cameras, alerts, evidence; acknowledge; record an outcome |
| `operator` | Everything a lifeguard can, plus manage cameras, zones, uploads, jobs, beaches |
| `administrator` | Everything, plus change which beach the installation watches, and list push devices |
| `service` | Only the worker's own endpoints: raise events, push frames, fetch worker config |

Two boundaries worth knowing, because they look surprising until you see why:

- A **human role cannot raise an event**. Only `service` (and `administrator`) can. A dashboard user
  must not be able to fabricate an incident.
- A **human role cannot read `worker-config`**. That response contains the camera's stream URL.

---

## 3. Postman setup

1. Open Postman → **Import** → drag in both files from `docs/postman/`.
2. Top right, select the environment **OceanEye — local**.
3. Check `base_url`. Default is `http://127.0.0.1:8000`. Use `https://` if you set up certificates.
4. If you are on HTTPS with a self-signed certificate: **Settings → General → SSL certificate
   verification → OFF**. (The certificate is self-signed on purpose; see
   [docs/prototype.md](prototype.md#phones).)

### Run it in order the first time

Open the collection → **Run** → Run OceanEye API. Folders run top to bottom, and each one captures
what the next one needs:

```
00 · Health              -> captures beach_id, beach_lat, beach_lon
01 · Beach               -> captures region_label, second_beach_id
02 · Cameras & zones     -> captures camera_id
03 · Video analysis      -> captures upload_id, job_id
04 · Worker simulation   -> pushes a live frame
05 · Events & alerts     -> captures event_id, alert_id
06 · Evidence & demo
07 · Phone push
08 · Metrics & sea state
09 · Clean up
```

After the first full run, any folder works on its own as long as `00 · Health` has run in that
session.

### One thing Postman cannot automate

**The video upload.** Postman cannot attach a file from a variable, so open
`03 · Video analysis → Upload a video → Body` and pick a clip from `videos\` yourself. Without it,
the analysis requests report as *skipped* rather than failing, and the rest of the collection is
unaffected.

### Reading the results

Every request asserts something real. The collection also applies two checks to **every** response:

- it answers in under 5 seconds
- it never contains a Python traceback

Open the **Console** (bottom left) during a run. The tests print the things you actually want to
know: which profile the worker chose, how fast it ran, whether push is on, what the delivery
channels reported.

---

## 4. Health and configuration

### Is it alive?

```powershell
curl http://127.0.0.1:8000/health      # {"status":"ok"} - process is up, nothing else checked
curl http://127.0.0.1:8000/ready       # 200 + per-dependency checks, or 503
```

`/ready` is the one that matters. It returns 503 if the database or evidence storage is unreachable:

```json
{"status": "ready", "checks": {"database": true, "evidence_storage": true}}
```

### The single most useful request

`GET /api/config/public` tells you the state of the whole installation in one response.

```powershell
curl -H "X-Dev-Role: operator" http://127.0.0.1:8000/api/config/public
```

What to look at:

| Field | What it tells you |
|---|---|
| `beach` | Which beach this installation watches. `null` means none configured yet. |
| `hardware` | GPU name, VRAM, CPU cores, RAM — what was actually measured |
| `max_workers` | How many cameras can be monitored at once |
| `worker` | The configured model/imgsz/device. `auto` and `0` mean "decide from the hardware" |
| `capabilities.secure_context` | HTTPS on? If false, phones cannot install the app or get background alerts |
| `capabilities.web_push` | VAPID keys configured? |
| `capabilities.weather` / `beach_search` | External feeds live, or running on mocks |
| `map.tile_url` | Where map tiles come from |

**Every later test in this guide reads `beach.id`, `beach.lat` and `beach.lon` from here.** That is
why nothing downstream is hardcoded.

---

## 5. Module 1 — Control Room

Open <http://127.0.0.1:8000/ui/control.html>.

### What to check on screen

| Area | Working looks like |
|---|---|
| **Deployment site** | The beach name, region, authority, lifeguard and camera counts |
| **KPI row** | Six tiles with numbers (dashes when there is no data yet) |
| **Camera wall** | One tile per camera; grey "offline" until a worker runs |
| **Active incidents** | "No active incidents" or incident cards with evidence thumbnails |
| **Map** | Tiles render, a dark blue dot marks the beach, camera pins appear |
| **Sea & weather** | Nine values and a 12-hour forecast table |
| **Event history** | Rows appear as you create events |
| **Performance & response** | Timing table, plus "this machine" showing your GPU |
| **Header** | Green dot + "live alerts" means the WebSocket is connected |

### The map

If you see **"Access blocked — App is not following the tile usage policy"**, you are on an old
build. OpenStreetMap's own tile servers refuse direct use by applications and return that picture
instead of an HTTP error, so no code can catch it. The fix is a provider that permits it, which is
now the default. Verify:

```powershell
curl -H "X-Dev-Role: operator" http://127.0.0.1:8000/api/config/public
# "map": { "tile_url": "https://{s}.basemaps.cartocdn.com/light_all/..." }
```

If it still says `tile.openstreetmap.org`, your `.env` is overriding it — remove
`OCEANEYE_MAP_TILE_URL` or point it at a provider that allows application use.

Use the **Map / Satellite** control in the map's top-right corner. Satellite shows the actual
shoreline, which is how you check a camera pin is in a sensible place.

### Add a camera and draw a zone

1. **Add camera** → name, position (or click the map to fill lat/lon), RTSP URL or an uploaded clip.
2. The camera appears on the wall and a pin appears on the map.
3. **Zone** → click points around the water → **Save zone**.
4. Stop and start monitoring so the worker picks the zone up.

Confirm via the API that the camera joined the right beach and the URL never leaks:

```powershell
curl -H "X-Dev-Role: operator" "http://127.0.0.1:8000/api/cameras"
```

The response must contain `beach_id` and must **not** contain `stream_url` or `rtsp://`.

---

## 6. Module 2 — Video Analysis

Open <http://127.0.0.1:8000/ui/analysis.html>. This is the testing path: a recorded clip exercises
detection, tracking, zones, risk, events and alerts exactly as a live camera would.

1. **Upload** a clip from `videos\`. It appears in the table with its size.
2. **Analyse** — leave Model and Image size on **auto**. Pick a camera, set sensitivity to **high**
   (more alerts, good for testing), press **Run analysis**.
3. The job appears in the Jobs table and progresses. The first run downloads the model, so be
   patient.
4. When it completes, the **Model** column shows what auto actually chose — `yolov8s.pt @768 ·
   cuda:0` on a 4 GB laptop GPU. The **Speed** column shows frames per second and the warm-up time
   that was excluded from it.
5. **Watch** plays the annotated video: boxes, track IDs, trails, the red zone, risk badges.
6. Any events it created appear in the Control Room and on lifeguard phones.

### Checking the auto profile is sane

```powershell
curl -H "X-Dev-Role: operator" "http://127.0.0.1:8000/api/analysis/jobs?limit=1"
```

In `summary`:

| Field | Meaning |
|---|---|
| `model`, `imgsz`, `device` | What was actually used (never the word "auto") |
| `profile` | Why — e.g. `cuda, 4.0 GB VRAM per worker` |
| `pipeline_fps` | Steady-state rate, warm-up excluded |
| `warmup_s` | The one-off cost. On CUDA this is seconds; that is normal |
| `throughput_fps` | Including I/O and encoding |

If `pipeline_fps` looks absurdly low, check `warmup_s` — on a very short clip the warm-up dominates
the wall-clock time even though it is excluded from the rate.

### Turn a clip into a fake CCTV camera

In the uploads table press **Use as simulated CCTV**. The clip replays on a loop as a live camera.
This is the best way to demo without a real camera, and it exercises reconnect, zone gating and the
per-track cooldown.

---

## 7. Module 3 — Lifeguard app

Open <http://127.0.0.1:8000/ui/lifeguard.html> (on the PC first, phone later).

1. Type a name, press **Turn on alerts**. Read the line underneath — it tells you honestly what is
   on. Over plain HTTP you get: *"Background alerts need a secure (https) connection."*
2. Trigger an alert (Control Room → **Demo alert**, or `POST /api/events` as `service`).
3. The phone should: ring, vibrate, and show a red **POSSIBLE DISTRESS** card with the risk
   percentage, camera, zone, behaviour signals, evidence image, and a countdown to escalation.
4. **ACKNOWLEDGE** → the card turns blue, "RESPONDING", and the alarm stops.
5. **Rescued / resolved** or **False alarm** closes it.
6. The Control Room shows the acknowledgement and the time-to-acknowledge metric.

### Automatic escalation

Raise an alert and **do not touch it**. After `OCEANEYE_ACK_TIMEOUT_SECONDS` (30 by default) it
escalates on its own — purple banner, "ESCALATED", escalation tier 1.

To test this quickly, restart the server with a shorter deadline:

```powershell
$env:OCEANEYE_ACK_TIMEOUT_SECONDS=5; python scripts\run_api.py --lan
```

---

## 8. The beach (deployment site)

The rule: **exactly one beach is active**, and everything follows it.

```powershell
# What regions can be searched (built in, works offline)
curl -H "X-Dev-Role: operator" http://127.0.0.1:8000/api/beaches/regions

# Beaches inside a region, from OpenStreetMap
curl -H "X-Dev-Role: operator" "http://127.0.0.1:8000/api/beaches/search?region=Karnataka,%20India"

# Which one is this installation watching
curl -H "X-Dev-Role: operator" http://127.0.0.1:8000/api/beaches/active
```

In the Control Room press **Change beach**: pick a region → **Search beaches** → **Use this beach**.
The page reloads scoped to the new site.

### Things worth proving

| Test | Expected |
|---|---|
| Add a second beach | `is_active: false` — adding never steals the deployment |
| Operator presses activate | **403**. Changing the deployment is administrator-only |
| Administrator activates | 200, and exactly one site is active afterwards |
| Add the same OSM beach twice | Same id back, updated — no duplicate |
| `PATCH` with `lat` | **422** — position is not editable. A beach that moved is a different site |
| Search an unknown region | **422**, and the message names what was wrong |

### If the beach search returns nothing

That is a valid answer, not a crash. The OpenStreetMap Overpass mirrors rate-limit hard. OceanEye
now tries three mirrors in order; when all three fail the picker falls back to manual entry (the
**Add a beach manually** section in the dialog). The rest of the dashboard is unaffected.

To work entirely offline, set `OCEANEYE_BEACHES_PROVIDER=mock`.

---

## 9. The alert path, end to end

This is the test that matters most: **a signal becomes an acknowledged human response**.

Each step reads the id from the previous response. No pasted ids.

```powershell
$H = @{ "X-Dev-Role" = "service"; "X-Dev-User" = "manual-test" }
$HL = @{ "X-Dev-Role" = "lifeguard"; "X-Dev-User" = "Lifeguard Ravi" }
$B = "http://127.0.0.1:8000/api"

# 1. find the camera to use (no hardcoded id)
$cam = (Invoke-RestMethod "$B/cameras" -Headers @{ "X-Dev-Role" = "operator" })[0]

# 2. the worker raises a candidate event
$body = @{
  camera_id = $cam.id; track_id = "cam-T7"; risk_score = 0.72; risk_level = "high"
  distress_signals = @("vertical_bobbing", "repeated_submersion")
  reason = "inside danger zone; elevated for 3.2s"
} | ConvertTo-Json
$ev = Invoke-RestMethod "$B/events" -Method Post -Headers $H -ContentType "application/json" -Body $body
$ev.status          # pending

# 3. it reached the lifeguard
(Invoke-RestMethod "$B/alerts?active_only=true" -Headers $HL) |
  Where-Object { $_.event_id -eq $ev.id }

# 4. acknowledge
$ack = Invoke-RestMethod "$B/events/$($ev.id)/ack" -Method Post -Headers $HL `
       -ContentType "application/json" -Body '{"note":"responding"}'
$ack.acknowledgement.by     # Lifeguard Ravi - taken from the auth identity, not the body

# 5. close the loop
Invoke-RestMethod "$B/events/$($ev.id)/outcome" -Method Post -Headers $HL `
  -ContentType "application/json" -Body '{"outcome":"resolved"}'

# 6. the metric moved
(Invoke-RestMethod "$B/metrics" -Headers @{ "X-Dev-Role" = "operator" }).response.time_to_ack
```

While you do this, watch the Control Room and a lifeguard page side by side. Both should react
within a second, without a refresh.

### The state machine

| From | May go to |
|---|---|
| `pending` | acknowledged, escalated, resolved, false_alarm |
| `acknowledged` | escalated, resolved, false_alarm |
| `escalated` | acknowledged, resolved, false_alarm |
| `resolved` / `false_alarm` | nothing — terminal |

Acknowledging twice returns **409** with code `invalid_state_transition`. That is deliberate: it
protects the record of who actually responded.

---

## 10. Simulating a worker without a GPU

You can drive the whole dashboard without running a model. These are the endpoints a real worker
process calls back on (role `service`).

```powershell
$S = @{ "X-Dev-Role" = "service" }
$B = "http://127.0.0.1:8000/api"
$cam = (Invoke-RestMethod "$B/cameras" -Headers @{ "X-Dev-Role" = "operator" })[0]

# What a worker fetches when it starts
Invoke-RestMethod "$B/processing/cameras/$($cam.id)/worker-config" -Headers $S

# Push an annotated frame + live stats (base64 of any small JPEG)
$jpeg = [Convert]::ToBase64String([IO.File]::ReadAllBytes("some.jpg"))
$frame = @{ jpeg_b64 = $jpeg; stats = @{
    fps = 7.4; pipeline_ms = 135; people = 9; events = 0
    model = "yolov8s.pt"; device = "cuda:0"; imgsz = 768
    risks = @(@{ track_id = "T7"; level = "high"; score = 0.71 })
}} | ConvertTo-Json -Depth 5
Invoke-RestMethod "$B/processing/cameras/$($cam.id)/frame" -Method Post -Headers $S `
  -ContentType "application/json" -Body $frame
```

The camera now shows as **online** in the Control Room for about 10 seconds, with those stats and
the risk badge. That is enough to demo the wall, the zone editor background, and demo alerts with a
real evidence image.

The Postman folder `04 · Worker simulation` does all of this with a built-in test image.

---

## 11. WebSocket (live alerts)

Postman supports WebSockets, but not inside a collection — create it by hand:

1. **New → WebSocket Request**
2. URL: `ws://127.0.0.1:8000/ws/alerts?dev_role=lifeguard&dev_user=postman`
   (use `wss://` on HTTPS)
3. **Connect.** You should immediately receive:
   ```json
   {"type": "connection.ready", "subscribed_cameras": []}
   ```
4. Send `{"action":"ping"}` → `{"type":"pong"}`
5. Subscribe to specific cameras: `{"action":"subscribe","camera_ids":["cam_..."]}`
6. Now raise an event (section 9). The socket receives `alert.created` with the full payload.
   Acknowledge it → `alert.acknowledged`. Let one time out → `alert.escalated`.

Authentication is on the handshake. Try connecting with `?dev_role=banana` — the server closes the
socket with code **1008** (policy violation) instead of accepting it.

---

## 12. Phone testing

### Step 1 — reach it at all

Phone on the same Wi-Fi, open the LAN URL `run_api.py` printed:

```
http://192.168.1.7:8000/ui/lifeguard.html
```

If it does not load: Windows Firewall. Allow Python on **private** networks.

### Step 2 — foreground alerts (works on plain HTTP)

Tap **Turn on alerts**, then trigger a demo alert from the Control Room.

Expected: alarm sound, vibration, red card. **Only while the app is open with the screen on.** The
app says so under the button. This is a browser rule, not a missing feature.

### Step 3 — installable app and background alerts (needs HTTPS)

```powershell
python scripts\make_certs.py        # certificate covering localhost + your Wi-Fi address
python scripts\make_push_keys.py    # VAPID key pair
```

Paste the printed lines into `.env`, restart the server, then on the phone:

1. Open `https://192.168.1.7:8000/ui/lifeguard.html`
2. Certificate warning → **Advanced → Proceed**. Once per device. (Expected: self-signed.)
3. **Turn on alerts** → allow notifications. The message should now read *"Background alerts on —
   this phone will ring even with the app closed."*
4. Browser menu → **Install app** / **Add to Home screen**.

### Step 4 — the test that actually matters

1. Open the installed app, confirm it is connected.
2. **Lock the phone. Put it in your pocket.**
3. On the PC: Control Room → **Demo alert**.
4. The phone should ring and vibrate with the screen off, showing a notification that stays until
   you act on it.
5. Tap it → the app opens straight to the alert → **ACKNOWLEDGE**.

### Install the other two modules

Same procedure on `https://<ip>:8000/ui/control.html` and `/ui/analysis.html`. Each has its own
manifest, its own icon and its own id, so all three install as **separate apps**.

### Verifying from the API

```powershell
# Is background push actually on?
curl -H "X-Dev-Role: lifeguard" https://127.0.0.1:8000/api/push/public-key -k
#   404 = not configured; 200 + a key = on

# Which devices would be woken (administrator only)
curl -H "X-Dev-Role: administrator" https://127.0.0.1:8000/api/push/devices -k
```

That listing shows a hash and the label the lifeguard typed. The endpoint URL — which identifies a
specific device and browser — is stored but **never** returned.

### Phone checklist

| | Plain HTTP | HTTPS + VAPID |
|---|---|---|
| Pages load | yes | yes |
| Alarm + vibration while open | yes | yes |
| Install to home screen | no | yes |
| Alert while app is closed | no | yes |
| Offline banner when Wi-Fi drops | yes | yes |

### Offline behaviour

With the app installed, turn Wi-Fi off. You should get a red banner: *"Offline — you are NOT
receiving alerts. Fall back to normal watch."* Turn Wi-Fi back on; it reconnects by itself.

That wording is deliberate. A lifeguard must never think they are covered when they are not.

---

## 13. Security tests

The Postman collection runs all of these. By hand:

| Test | Request | Expected |
|---|---|---|
| No role | `GET /api/config/public` with no header | **401**, structured error, no traceback |
| Wrong role | `POST /api/beaches/{id}/activate` as operator | **403** |
| Lifeguard writes | `PUT /api/zones/{id}` as lifeguard | **403** |
| Human reads worker config | `GET /processing/cameras/{id}/worker-config` as operator | **403** |
| Human raises an event | `POST /api/events` as operator | **403** |
| Stream URL leak | `GET /api/cameras` | no `stream_url`, no `rtsp://` anywhere |
| Local file as a source | `POST /api/cameras` with `file:///etc/passwd` | **422**, and the value is not echoed back |
| Evidence without auth | `GET /api/evidence/{id}/thumbnail` | **401** |
| Path traversal | `GET /api/evidence/..%2F..%2Fetc%2Fpasswd/thumbnail` | 404 or 422, never file contents |
| Push endpoint leak | `GET /api/push/devices` | hashes and labels only, no URLs |
| Bad risk score | `POST /api/events` with `risk_score: 1.8` | **422** |
| Un-normalised zone | `PUT /api/zones/{id}` with pixel coordinates | **422** |

Two things to confirm in every error response:

- the body is `{"error": {"code": ..., "message": ..., "request_id": ...}}`
- it never contains `Traceback`, a file path, or the value you submitted

### Production refuses to start unsafely

```powershell
$env:OCEANEYE_ENVIRONMENT="production"; python scripts\run_api.py
```

Expected: it refuses, naming the problem — dev auth is on, no secret key, wildcard CORS, or no TLS.
Unset the variable afterwards.

---

## 14. Running it all from the command line

### The test suite

```powershell
pytest                          # 195 tests
pytest -k beach -v              # one area
pytest tests/unit/test_profiles_and_hardware.py -v   # the auto-tune policy
pytest tests/unit/test_architecture_boundaries.py    # module boundaries
```

A failure in `test_architecture_boundaries.py` is an architecture problem, not a test problem.
Do not suppress it — find the import that broke the layering.

### The Postman collection, headless

```powershell
npm install -g newman
newman run docs\postman\OceanEye.postman_collection.json `
  -e docs\postman\OceanEye.postman_environment.json `
  --env-var base_url=http://127.0.0.1:8000
```

Expected: **83 requests, 306 assertions, 0 failures.** The video-upload requests report as *skipped*
because a headless run cannot attach a file — upload once through the UI or Postman and they pass
too.

### Perception on its own

```powershell
python scripts\check_env.py --source "videos\clip.mp4"      # what this machine can do
python scripts\run_perception.py --source "videos\clip.mp4" # detection + tracking only
```

`run_perception.py` writes `outputs\perception\<name>_<time>\` with the annotated video,
`tracks.jsonl` and `summary.json`. No API, no risk engine — use it when you want to measure the
detector by itself.

---

## 15. Endpoint reference

Role is the **minimum** needed. Interactive docs: <http://127.0.0.1:8000/docs>.

### System

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/health` | – | Liveness |
| GET | `/ready` | – | Readiness (503 when a dependency is down) |
| GET | `/api/config/public` | lifeguard | Beach, hardware, capabilities, worker defaults, map config |
| GET | `/api/metrics` | lifeguard | Response timing, outcomes, detection performance |

### Beaches (deployment site)

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/api/beaches/regions` | lifeguard | Searchable regions (built in, offline-safe) |
| GET | `/api/beaches/search?region=` or `?lat=&lon=` | lifeguard | Beaches from OpenStreetMap |
| GET | `/api/beaches` | lifeguard | Configured sites, active first |
| GET | `/api/beaches/active` | lifeguard | The one beach being watched |
| POST | `/api/beaches` | operator | Configure a site |
| PATCH | `/api/beaches/{id}` | operator | Authority details only |
| POST | `/api/beaches/{id}/activate` | **administrator** | Change the deployment |
| GET | `/api/beaches/nearby?lat=&lon=&radius_km=` | lifeguard | Beaches near a point |

### Cameras and zones

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/cameras` | operator | Register (joins the active beach) |
| GET | `/api/cameras[?beach_id=]` | lifeguard | List; `stream_url` never returned |
| GET | `/api/zones/{camera_id}` | lifeguard | Danger-zone polygon |
| PUT | `/api/zones/{camera_id}` | operator | Set it (normalised 0–1) |
| POST | `/api/cameras/{id}/monitoring/start` | operator | Spawn a worker |
| POST | `/api/cameras/{id}/monitoring/stop` | operator | Stop it |
| GET | `/api/live/cameras` | lifeguard | Per-camera state and stats |
| GET | `/api/live/cameras/{id}/frame` | lifeguard | Latest annotated JPEG |

### Video analysis

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/uploads` | operator | Upload a video (multipart) |
| GET | `/api/uploads` | operator | List uploads |
| POST | `/api/analysis/jobs` | operator | Run the chain on one |
| GET | `/api/analysis/jobs[?limit=]` | operator | List jobs |
| GET | `/api/analysis/jobs/{id}` | operator | Progress and summary |
| POST | `/api/analysis/jobs/{id}/cancel` | operator | Cancel |
| GET | `/api/analysis/jobs/{id}/video` | lifeguard | Annotated result |

### Events and alerts

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/events` | **service** | Raise a candidate event |
| GET | `/api/events` | lifeguard | List (filter by camera, status, time) |
| GET | `/api/events/{id}` | lifeguard | One event |
| POST | `/api/events/{id}/ack` | lifeguard | "I am responding" |
| POST | `/api/events/{id}/escalate` | lifeguard | Escalate manually |
| POST | `/api/events/{id}/outcome` | lifeguard | resolved / false_alarm |
| GET | `/api/alerts[?active_only=]` | lifeguard | Alerts with full payloads |
| GET | `/api/alerts/{id}` | lifeguard | One alert |
| GET | `/api/evidence/{event_id}/{clip\|thumbnail}` | lifeguard | Protected evidence |
| POST | `/api/demo/incident` | operator | Labelled rehearsal alert |
| WS | `/ws/alerts?dev_role=` | lifeguard | Live feed |

### Worker callbacks and push

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/api/processing/cameras/{id}/worker-config` | **service** | Source, zone, options |
| GET | `/api/processing/jobs/{id}/worker-config` | **service** | Same, for a job |
| POST | `/api/processing/cameras/{id}/frame` | **service** | Annotated frame + stats |
| POST | `/api/processing/cameras/{id}/state` | **service** | Worker state |
| POST | `/api/processing/jobs/{id}/report` | **service** | Job progress |
| GET | `/api/push/public-key` | lifeguard | VAPID key (404 = push off) |
| POST | `/api/push/subscribe` | lifeguard | Register a device |
| POST | `/api/push/unsubscribe` | lifeguard | Remove it |
| GET | `/api/push/devices` | **administrator** | Registered devices (hashes only) |

---

## 16. When something fails

| Symptom | Cause and fix |
|---|---|
| Map shows "Access blocked" | Old build or `OCEANEYE_MAP_TILE_URL` points at `tile.openstreetmap.org`. OSM refuses direct application use. Use the default CARTO URL |
| Map blank | The Leaflet library or tiles need internet. The rest of the page is unaffected |
| "Nearby beaches unavailable" | All three Overpass mirrors are rate-limited or unreachable. Add a beach manually, or set `OCEANEYE_BEACHES_PROVIDER=mock` |
| Camera stuck "starting" | The first run downloads the model. Read `data\logs\worker_cam_<id>.log` |
| "worker limit reached" | You hit `max_workers`. Stop a camera, or check whether `.env` has it set too high |
| Startup warns about `MAX_WORKERS` | Exactly what it says: you asked for more workers than the memory supports. Set it to `0` |
| Worker dies, "Insufficient memory" | Too many workers or a pinned model too large. Set the worker settings back to `auto`/`0` |
| Job reports a very low fps | Check `warmup_s`. On a short clip the one-off model load dominates the wall clock |
| Phone cannot install | Needs HTTPS. Check `capabilities.secure_context` |
| No alert with the app closed | Needs HTTPS **and** VAPID keys. Check `capabilities.web_push` |
| 401 on everything | Missing `X-Dev-Role` header |
| 403 on something you expect to work | Check the role table in section 2 — most likely operator vs administrator |
| 409 on acknowledge | The event is already in a state that cannot be acknowledged again. Working as intended |
| Postman: SSL error | Self-signed certificate. Turn off SSL verification in Postman settings |
| Postman: variable is empty | Run `00 · Health` first — it captures the beach id everything else uses |

---

## What a passing run looks like

```
pytest                     195 passed, 2 skipped
newman run                 83 requests, 306 assertions, 0 failures
Control Room               camera wall live, map tiles render, incidents arrive
Video Analysis             a clip runs, the auto profile is reported, events are created
Lifeguard (phone, HTTPS)   installed as an app, rings with the screen off, acknowledge works
Automatic escalation       an untouched alert escalates on its own after the deadline
```

Two skipped tests are the real-ByteTrack ones; they run only with the `vision` extras installed.
