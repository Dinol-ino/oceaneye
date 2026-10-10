# OceanEye — AI-assisted drowning-risk detection (prototype)

> **"See danger before it becomes a rescue."** Decision support for lifeguards — not a replacement.

OceanEye watches a beach's CCTV, looks for behaviour that *might* be distress, and puts a candidate
incident — with an evidence image and clip — in front of a human within seconds. A person decides.

```
CCTV ─▶ detection ─▶ tracking ─▶ danger zone + sea state ─▶ behaviour signals ─▶ risk
     ─▶ candidate event ─▶ alert ─▶ lifeguard phone ─▶ acknowledge ─▶ escalate / resolve
```

---

## Run it

```powershell
cd C:\pbl_oceaneye
.\venv\Scripts\Activate.ps1
pip install -e ".[dev,vision,push,tls]"
Copy-Item .env.example .env -Force

python scripts\run_api.py --lan          # keep this window open
# second terminal, venv active:
python scripts\seed_demo.py --start 1    # videos\*.mp4 become simulated CCTV cameras
```

Then open **<http://127.0.0.1:8000>**. Full run book, including phones and GPU:
**[docs/prototype.md](docs/prototype.md)**.

### Phones (installable app + alerts while closed)

Browsers only allow installable apps and background notifications on a **secure** origin, and
`http://192.168.x.x` is not one. Two one-time commands fix that:

```powershell
python scripts\make_certs.py        # self-signed certificate covering this PC's Wi-Fi address
python scripts\make_push_keys.py    # VAPID key pair for background alerts
# paste the lines each prints into .env, then restart run_api.py
```

Now open `https://<your-pc-ip>:8000/ui/lifeguard.html` on the phone, accept the certificate warning
once, tap **Turn on alerts**, then install it from the browser menu. The phone appears in the control
room under **Alerting**; press *Send test alert to phones* there to confirm the PC actually reaches
it before you rely on it. See [docs/prototype.md](docs/prototype.md#phones).

---

## Two interfaces, two people

| | For | What it does |
|---|---|---|
| `/ui/control.html` | Control room, on a PC | Set the beach this installation watches, add cameras and draw their danger zones, camera wall with live risk overlays, active incidents with evidence, map, sea and weather, **video analysis** of recorded footage, the alerting panel that proves phones are reachable, event history and response metrics |
| `/ui/lifeguard.html` | Lifeguard, on a phone | One screen per alert: evidence image, where it is, one big Acknowledge button; alarm, vibration and background alerts each switchable; navigation; resolved / false-alarm feedback |

Both install to a home screen as apps. There is no third page: video analysis used to be one and is
now a section of the control room (`/ui/analysis.html` redirects there), because it is the same
operator testing the same beach's cameras against a recording instead of a live stream.

---

## One beach per installation

In the field OceanEye runs for **one** beach: that beach's authority owns the cameras and its
lifeguards answer the alerts. That is a `Beach` record with `is_active` set — cameras, incidents, the
map and the weather all follow it.

The picker (Control Room → **Change beach**) exists so the system can be *set up*, and demonstrated,
for any coastline without editing code: **one search box**. Type a beach, a town or a district, read
the full address and coordinates on each result, and press *Watch this beach* — it becomes this
installation's site immediately. "Beaches near the map centre" does the same for wherever the map is
pointed. Nothing is hardcoded: the list comes from Geoapify at request time, and the chosen beach's
coordinates are shown in the header, the site panel and the map.

When the lookup is unavailable the response says *why* (no key, wrong key, no internet) instead of
showing an empty list, and the manual entry — name plus coordinates, which you can read off the map
by clicking it — is opened for you. Changing the deployment beach is administrator-only.

Place search and the map need one free key in `.env`:

```ini
OCEANEYE_PLACES_PROVIDER=geoapify
OCEANEYE_GEOAPIFY_API_KEY=<your key from myprojects.geoapify.com>
OCEANEYE_MAP_STYLE=osm-bright-smooth
```

Map tiles are fetched **through the API** (`/api/map/tiles/{style}/{z}/{x}/{y}.png`), so the key
never reaches a browser. Without a key the app still runs: the map goes blank and the picker asks
you to type the beach in.

---

## It sizes itself to the machine

Model, input size, frame rate, worker count and the evidence-clip resolution all default to `auto`
and are chosen from the GPU and memory actually present ([`app/vision/profiles.py`](app/vision/profiles.py),
[`app/shared/hardware.py`](app/shared/hardware.py)). A 4 GB laptop GPU running two cameras gets a
smaller profile than the same GPU running one.

This is not a convenience feature: two workers at `yolov8s @ 960` is what exhausted this machine's
memory mid-run (`cv2.error ... Insufficient memory`). Anything you set explicitly in `.env` overrides
the policy for that field only.

```powershell
python scripts\check_env.py --source "videos\clip.mp4"   # what this machine can do
```

No usable GPU? Use the Colab notebook — same code, Google's GPU:
`notebooks\OceanEye_Perception_Colab.ipynb` (rebuild after code changes with
`python scripts\build_colab_notebook.py`).

---

## Layout

```
app/
  main/         factory, lifespan, container (composition root), middleware, error handlers, health
  core/         entities, enums, value objects, domain events, exceptions, ports (framework-free)
  config/       Settings (OCEANEYE_* env)
  security/     authentication / authorization / deps / headers / validators
  camera/       camera registry; CameraSource / FrameSource contracts; OpenCV source with reconnect
  vision/       Detector, Tracker, PoseEstimator, VisionPipeline contracts; YOLO + ByteTrack; profiles
  environment/  beaches (deployment site), place search, map tile proxy, zones, water motion; /zones, /weather
  risk/         distress signals, rule-based risk engine, scoring parameters
  events/       event lifecycle service + /events API
  alerts/       alert service, notifications (websocket / web push / mock), escalation, /alerts, /push
  websocket/    connection manager + /ws/alerts
  evidence/     EvidenceStorage port, local adapter, protected /evidence
  persistence/  ORM models, Database, SQLite + in-memory repositories
  processing/   uploads, analysis jobs, worker supervisor (subprocesses), live frames, metrics
  worker/       separate process: frames -> detection -> tracking -> zone -> behaviour -> risk -> events
  web/          the two interfaces, service worker, manifests, icons (plain HTML/JS, no build step)
  shared/       clock, event bus, logging, hardware probe, error schema, FastAPI accessors
tests/  unit | integration | api        docs/  architecture.md, prototype.md, perception.md
scripts/ run_api · seed_demo · check_env · run_perception · make_certs · make_push_keys · build_colab_notebook
```

Architecture, module boundaries and extension points: **[docs/architecture.md](docs/architecture.md)**.
Detection and tracking in detail: **[docs/perception.md](docs/perception.md)**.

---

## Endpoints

`GET /health` `/ready` · `POST|GET /api/cameras` · `GET|PUT /api/zones/{camera_id}` ·
`GET /api/places/search?q=` `/api/places/beaches-near?lat&lon` · `GET /api/map/tiles/{style}/{z}/{x}/{y}.png` ·
`GET|POST /api/beaches` `/api/beaches/active` `POST /api/beaches/{id}/activate` ·
`POST|GET /api/events` `/api/events/{id}/ack|escalate|outcome` · `GET /api/alerts` · `GET /api/weather` ·
`POST /api/push/subscribe` `/api/push/test` `GET /api/push/devices` ·
`POST /api/uploads` `/api/analysis/jobs` · `GET /api/metrics` `/api/config/public` · `WS /ws/alerts`

Every endpoint, with assertions, in the Postman collection: **[docs/testing.md](docs/testing.md)**.

Interactive docs at `/docs` while `OCEANEYE_ENVIRONMENT=development`.

---

## Rules this codebase enforces

* `app/core` imports no framework; domain modules import no FastAPI, SQLAlchemy or ML library;
  `events`, `risk` and `vision` never import `alerts` or `websocket`. `tests/unit/test_architecture_boundaries.py`
  fails the build otherwise — treat a failure there as an architecture problem, not a test problem.
* Heavy libraries (OpenCV, Ultralytics, PyTorch) are imported lazily and only in allow-listed files,
  so the API, the test suite and the docs tooling run without them.
* The API process never loads a model. Each camera and each analysis job is a separate worker process
  that talks back over HTTP.
* No secrets in source. `.env` and `data/` are git-ignored. Production refuses dev auth, a missing
  secret key, wildcard CORS and plain HTTP.
* Camera `stream_url` is accepted but never returned. Push endpoint URLs are stored but never returned.
  Evidence is served only to authenticated roles.

```powershell
pytest          # no external services needed; vision tests skip without the extras
```

---

## Honest limits — say these out loud in any demo

* The detector is a general-purpose COCO "person" model. It has never seen a swimmer. It misses
  heads-only and partly submerged people, misses tiny distant ones, and fragments identities in crowds.
* The behaviour signals (stillness, bobbing, erratic movement, repeated submersion) are **heuristics**.
  Each one also fits ordinary behaviour. Every threshold in `app/risk/scoring/config.py` is a starting
  point, not a validated value. Nothing here has been measured against labelled drowning footage.
* Alerts are **candidate events** for a human to confirm. OceanEye cannot say that someone is drowning,
  and cannot say that someone is safe.
* Zones are static polygons; dynamic zones from water motion, and `arms_raised` from a pose model, are
  not built.
* Development authentication (role chosen in the page) is not security. The LAN certificate is
  self-signed: it gives encryption, not proof of identity.
* One PC, SQLite, local files, single-process WebSocket fan-out. Fine for a pilot, not for a coastline.

Mark every incident **Resolved** or **False alarm**. Those outcomes are the only labelled data the
project has, and they are what any future tuning or training will be built on.
