# OceanEye — audit findings + full test plan

Scope: upload a video on the PC → detect distress → alert reaches a lifeguard's phone.
Basis: I read the code in `app.zip`, ran your existing suite (all green), and built a new pack
(`tests/hardening/`, 30 tests) that runs the **real** analyzer and risk engine on synthetic people.
Numbers marked *synthetic* come from that harness (20 seeded runs per cell, ~1% box jitter). They
are reproducible, but they are not a substitute for real footage.

---

## 0. Bottom line

1. **You cannot currently claim the detection is strong, because nothing has ever tested it on a
   drowning.** `labels.json` has 13 clips and every one is a negative. `outputs/evaluation.json`
   says `distress_windows: 0, recall: null`. Your own file says recall "cannot be measured".
   Zero false alarms on 27 min of empty-ish water proves the system is quiet, not that it works.
2. **The strongest signals never run in the product.** Pose (vertical torso, arms raised —
   weights 0.55 and 0.45) is not wired into the worker, for jobs or cameras (D6).
3. **The verdict changes with the frame rate the machine happens to run at** (D1–D3). Same
   motionless person: 0 % false alarms at 2–3 fps, 100 % at 12 fps. Same quiet drowner: 0 %
   detected at 2–3 fps, 100 % at 6+ fps.
4. Phone path is plausible on paper but **has never been exercised on this database**
   (`push_subscriptions` = 0 rows).
5. Everything else (API, auth, uploads, escalation, evidence) is in good shape — 21 guard tests pass.

---

## 1. Findings, ranked by impact

| # | Finding | Evidence | Test |
|---|---|---|---|
| F1 | No positive footage → recall unmeasurable, "very strong" is unprovable | `labels.json` (13/13 negative), `evaluation.json` | Suite B |
| F2 | Pose not wired into live worker; `PoseConfig.enabled=False`; `SessionConfig` has no pose option; only `evaluate_detection.py --pose` can use it | `app/worker/session.py::default_pipeline`, `app/worker/factory.py` | **D6** |
| F3 | Verdict depends on analysed fps. Erratic/bobbing use frame-to-frame deltas, so jitter → "speed" grows with fps | *synthetic*: standing 0/0/15/**100 %** alarms at 2/3/6/12 fps; thrash 100/100/5/**0 %** detected | **D1, D3** |
| F4 | Without pose, stillness alone caps at 0.35 × conf < threshold 0.5. A quiet victim needs a second signal, which is mostly created by jitter | *synthetic*: quiet drowner 0 % at 2–3 fps (45 s), slow sink 15 % at 2 fps | **D2, D4, D5** |
| F5 | Tracking fragmentation starves the 2.5 s / 6 s behaviour windows | `summary.json`: `29982…` 7 ids for 1 person; CCTV clip 882 ids, max 17 concurrent over 24.5 min; crowded clips 49–131 ids for ≤24 people | A-04, B-05 |
| F6 | Evaluation ≠ live: script uses stride 2 (15 fps on 30 fps clips) and the box **centre** for the zone; live uses 2–8 fps and the box **bottom** | `evaluate_detection.py` vs `PolygonZoneGate` | **D8** |
| F7 | Job events are dated in the future (frame time = start + video time); 5 min clip → last event ~minutes ahead | measured 5.3 s skew on a 15 s clip | **D7** |
| F8 | No server-side alert cap; worker's 3/min lives only in the worker | 8 identical POSTs → 8 alerts | **D9** |
| F9 | Speed: all saved runs are CPU `yolov8n`; 105–215 ms/frame at 6–15 analysed fps = 0.6–1.6× real time (one outlier at 768 ms) | `outputs/perception/*/summary.json` | C-01..C-03 |
| F10 | Resolution gate: a person < 40 px tall gets **no verdict** (correct), but on 480×360 CCTV that is most of the water | `RiskScoringConfig.min_body_pixels`, your own note in config | B-06 |
| F11 | Zone: no zone ⇒ whole frame counts ⇒ a sunbather/stander can score. A job uses the *camera's* zone, so the wrong camera = wrong zone for that video | `RuleBasedRiskEngine`, `ProcessingService.job_worker_config` | B-07 |
| F12 | Pose does not separate wading from drowning: an upright, motionless person in the zone alerts at ~8 s *with* pose on (*synthetic*). Zone must exclude the shallows | `_vertical_in_water` docstring admits it | B-08 |
| F13 | **Secrets are in the zip**: live Geoapify key, VAPID private key, TLS key, your email in `.env`. Rotate before sharing the project anywhere | `.env`, `data/vapid_private.pem`, `data/certs/key.pem` | H-01 |
| F14 | Dev auth = whoever sends `X-Dev-Role: administrator` is admin. Fine on your LAN for the demo; not on any shared Wi-Fi | `authentication.py` | H-02 |

---

## 2. Footage you need (this is the real blocker)

You need **labelled positives and hard negatives**. Label times in `labels.json` (`"distress": [[start, end]]`).

**Positives (aim for ≥ 30 distinct events before quoting a recall number):**
- Lifeguard-training / drowning-simulation footage, and stock footage of rescues.
- Staged clips with consenting adults **in a pool with a certified lifeguard watching and a
  safety swimmer in the water**. Never stage anything in open surf. Mimic: vertical and nearly
  still with head dipping; flailing in place; slow sinking; arms pressing down.
- Cover: distance (near, mid, far), camera height, sun glare, overcast, foam, backlit sunset.

**Hard negatives (these decide whether lifeguards keep the app on):**
standing in shallows, wave play, body-surfing, treading water chatting, floating on back,
snorkelling (head down, still), kids splashing, swimmers in lanes, fishermen/boats, dogs,
surfers waiting for a set, sunbathers at the waterline, crowd walking in front of swimmers.

Rule: every clip ≥ 60 s. Behaviour needs 2.5 s track age + 6 s stillness window + 3 s persistence;
your 7–27 s clips barely exercise it.

---

## 3. How to run everything

**Install the pack** (copy, don't overwrite anything): `tests\hardening\` → your `tests\`, `scripts\run_clip_matrix.py` → your `scripts\`.

```powershell
cd C:\pbl_oceaneye ; .\venv\Scripts\Activate.ps1
pytest                                   # your existing suite  (must stay green)
pytest tests\hardening -q                # new pack; red = open defect
pytest tests\hardening -q -m "not defect"   # 21 guards: must be green
pytest tests\hardening -q -m defect         # the 9 open faults
```

Expected right now: 21 pass, 9 fail (D1–D9). As you fix each, the matching test turns green.
`defect` tests assert the behaviour you want; edit a threshold in the test only if *you* decide the
product target is different (D5's 15 s budget is a placeholder for your decision).

### Prompt to paste into Antigravity
> Open the project root. Run `pytest` and then `pytest tests/hardening -q`. Report pass/fail counts and,
> for each failing `D*` test, the assertion message verbatim. Do not modify `app/` or the tests.
> Then run `python scripts/check_env.py --source "beach_videos/<clip>.mp4"` and paste the output.
> For Suites B–D execute the commands in OCEANEYE_TEST_PLAN.md and fill the result tables.

---

## 4. Test suites

Record every result in a table. A test without a number is a vibe.

### Suite A — Sanity and regression (10 min)

| ID | Test | Command / steps | Pass |
|---|---|---|---|
| A-01 | Existing suite | `pytest` | all green (2 skips ok) |
| A-02 | Hardening guards | `pytest tests\hardening -m "not defect"` | 21 pass |
| A-03 | Environment doctor | `python scripts\check_env.py --source "beach_videos\<clip>.mp4"` | cuda yes/no stated, profile printed, no traceback |
| A-04 | Track continuity per clip | open each `outputs\perception\<run>\summary.json`; compute `unique_track_ids / max_concurrent_tracks` | ≤ 3 on clips with ≤ 5 people. Today: 7 for one person (`29982…`) |
| A-05 | Overlay sanity | play `overlay.mp4` for 3 clips with people | boxes on people, IDs stable ≥ 3 s, zone drawn where you set it |

### Suite B — Detection quality (the one that matters)

Runs `evaluate_detection.py` on `labels.json`. Add your positives first.

```powershell
python scripts\evaluate_detection.py --labels labels.json --stride 4 -v          # ≈7.5 fps from 30 fps
python scripts\evaluate_detection.py --labels labels.json --stride 4 --pose -v
python scripts\evaluate_detection.py --labels labels.json --stride 4 --sweep 0.3,0.4,0.5,0.6,0.7
```
Use `--stride` = `round(source_fps / target_fps)` so it matches the live profile. The default stride 2
analyses 15 fps on a 30 fps clip, so it says little about the 2–8 fps live path.

| ID | Test | Pass criterion (set your own; these are starting targets) |
|---|---|---|
| B-01 | Recall per labelled window (pose off) | ≥ 80 % on ≥ 30 windows. Report the count next to the %. |
| B-02 | Recall (pose on) | ≥ B-01; note cost in fps |
| B-03 | False alarms per hour on hard negatives | ≤ 1 per camera-hour; 0 on the 5 hardest negatives |
| B-04 | Time to alert from onset (per hit) | median ≤ 15 s, worst ≤ 30 s |
| B-05 | Crowd + tracking | on the Getty crowd clips: ids ≤ 2× max concurrent |
| B-06 | Distance ladder | same actor at 10 / 20 / 40 / 60 m; record body px at each, first distance where recall < 50 % |
| B-07 | Zone correctness | draw the zone on the *job's camera* for each clip; verify `inside danger zone` appears in the event `reason`; run once with **no zone** and compare false alarms |
| B-08 | Shallows trap | person standing still ankle-to-waist deep, zone covering the shallows vs not. Expect an alert when covered. Decide the zone policy |
| B-09 | Glare / low light / rain | one clip each; record misses and false alarms |
| B-10 | Threshold sweep | pick the knee of the recall vs FA/hour curve; write the value and the footage count |
| B-11 | Sensitivity presets | rerun B-01/B-03 at `low` and `high` |

### Suite C — Timing and latency

| ID | Test | Method | Pass |
|---|---|---|---|
| C-01 | Real-time factor | `avg_pipeline_ms × analysed_fps / 1000` from `summary.json` | < 0.8 for live use; > 1 means a live camera lags |
| C-02 | Warm-up cost | job summary `warmup_s` | reported and < 15 s |
| C-03 | Throughput on a long clip | the 24 min clip; wall time vs duration; watch RAM in Task Manager | RAM flat (no growth > 10 %) |
| C-04 | Event → phone latency | click start on a stopwatch at `POST /api/events` (or job event), stop when the phone buzzes; 10 trials, screen off, app closed | median ≤ 5 s, max ≤ 15 s |
| C-05 | Upload → job done | 100 MB / 500 MB clip | no timeout; progress moves every ≤ 2 s |
| C-06 | Ack deadline | create an event, do nothing | escalates at `ack_timeout_seconds` (30 s) ± escalation interval (5 s) |
| C-07 | Push TTL | phone in airplane mode 3 min, then reconnect | expired alert (> 120 s) is not delivered as new; WebSocket/list still shows it |

### Suite D — Model switching and profiles

| ID | Test | Steps | Pass |
|---|---|---|---|
| D-01 | Matrix | `python scripts\run_clip_matrix.py --labels labels.json` (n/s × 640/960 × stride 4/10 × pose off/on) | table printed; fill best config per hardware |
| D-02 | Auto profile | start with `OCEANEYE_WORKER_MODEL=auto`; read `summary.profile` | matches the table in `docs/perception.md` for your GPU/CPU |
| D-03 | Per-job override | `POST /api/analysis/jobs` with `"model":"yolov8s.pt","imgsz":960` | summary shows s/960 |
| D-04 | Invalid values | `"model":"x.pt"`, `"imgsz":700`, `"device":"tpu"`, `"sensitivity":"max"` | 4× HTTP 422/400, no worker started |
| D-05 | Missing weights offline | rename `models\yolov8s.pt`, disconnect internet, run job with s | job FAILED with a readable reason (`job.error`), not "exit code 1" |
| D-06 | Two jobs, one GPU | start 2 jobs together on a 4 GB GPU | second is refused with "worker limit" or runs; no `Insufficient memory` crash |
| D-07 | Model vs miss rate | repeat B-01 for n and s; tabulate | s recall ≥ n on distant swimmers, cost recorded |
| D-08 | Pose model present | `yolov8n-pose.pt` loads; `--pose` run | no crash; pose signals appear in `reason` |

### Suite E — Behaviour, risk and environment

| ID | Test | Method | Pass |
|---|---|---|---|
| E-01 | Synthetic rules | `pytest tests\hardening\test_behaviour_rules.py` | G1–G5 green; D1–D5 tracked |
| E-02 | Rough sea boost | set `OCEANEYE_WEATHER_PROVIDER=mock` with waves ≥ 1.5 m, rerun a borderline clip | score × 1.15, `rough conditions` in reason |
| E-03 | Weather outage | block internet during a job | job still completes; warning logged; no crash |
| E-04 | Cooldown | one thrash clip | 1 event per track per 60 s (G4) |
| E-05 | Per-camera cap | crowd of simultaneous distress | ≤ 3 events/min/camera |
| E-06 | ID-switch duplicate | a clip where the victim's track id changes mid-event | count alerts; > 1 for one person = tune tracker or add API-side merge (D9) |

### Suite F — Alert path and the lifeguard phone

Prereqs: `python scripts\make_certs.py`, `python scripts\make_push_keys.py`, paste into `.env`,
`python scripts\run_api.py --lan`, phone on the same Wi-Fi, open
`https://<PC-IP>:8000/ui/lifeguard.html`, accept the cert warning once.

| ID | Test | Steps | Pass |
|---|---|---|---|
| F-01 | Subscribe | tap **Turn on alerts** | `GET /api/push/devices` shows ≥ 1 device |
| F-02 | Test push | Control Room → *Send test alert to phones* (or `POST /api/push/test`) | `sent == devices` |
| F-03 | Screen off | lock phone 2 min, send test | buzz + notification |
| F-04 | App closed | swipe the PWA away, send test | notification still arrives |
| F-05 | Install as app | add to home screen, reopen | opens standalone, offline page when Wi-Fi off |
| F-06 | Alert content | trigger a real job event | thumbnail loads, location shown, ack button works, clip plays |
| F-07 | Acknowledge | tap Acknowledge | control room shows acknowledged within 2 s; escalation stops |
| F-08 | Outcome | mark *False alarm* / *Resolved* | `GET /api/metrics` moves |
| F-09 | Two phones | register 2 phones | both buzz; ack on one updates both |
| F-10 | Dead endpoint | uninstall the PWA on a phone, send test | server drops it (404/410) and others still receive |
| F-11 | Sound + vibration toggles | switch each off/on | respected |
| F-12 | Wi-Fi roam / PC IP change | change network | document: cert covers the *old* IP, regenerate with `make_certs.py` |
| F-13 | Platform | Android Chrome and iPhone | iPhone needs iOS 16.4+ **and** the app added to the Home Screen for background push |
| F-14 | Battery saver | Android battery optimisation ON for the browser, screen off 30 min, send test | note whether it arrives; whitelist the browser if not |
| F-15 | Flood | `tests\hardening` D9, then 10 rapid demo incidents | phones stay usable; define the cap you want |

### Suite G — The "manually send to lifeguard" flow (design gap)

What exists: job events are posted to `/api/events` **automatically**, which pushes to phones.
`POST /api/demo/incident` injects a generic DEMO alert (uses the latest live frame, not the detected
event). There is **no** "review the detection, then press Send" step.

| ID | Test | Pass |
|---|---|---|
| G-01 | Run a job that yields a candidate | event appears in Control Room *and* on the phone immediately (auto) |
| G-02 | Demo incident | `POST /api/demo/incident {"camera_id": ...}` → phone buzzes, reason says DEMO |
| G-03 | (after you decide the design) Review-then-send | event created as `pending`, only notifies on operator click |

### Suite H — Robustness, failure injection, security

| ID | Test | Method | Pass |
|---|---|---|---|
| H-01 | Secrets hygiene | rotate Geoapify key and VAPID pair, regenerate TLS, delete `.env` from any shared copy | old key rejected |
| H-02 | Auth spoof | `curl -H "X-Dev-Role: administrator" https://<PC>:8000/api/cameras -k` from another device | works today → keep the LAN private, or set `auth_mode=token` before real use |
| H-03 | Bad files | 0-byte, `.exe` renamed `.mp4`, truncated mp4, 600 MB file, rotated/portrait 4K, VFR phone video | clear error or graceful job failure, never a hung job |
| H-04 | Kill worker mid-job | end the python worker process | job → FAILED with reason in ≤ 10 s |
| H-05 | API restart mid-job | restart `run_api.py` | job state recovers or fails cleanly; no orphan worker |
| H-06 | API down for worker | stop API for 20 s while a job runs | worker retries (`retries=3`), event not silently lost; check log |
| H-07 | Delete in use | delete an upload that a job/camera uses | 409 with message |
| H-08 | Path traversal | upload `../../x.mp4` | stored under `data/uploads/vid_*.mp4` (G11) |
| H-09 | Stream URL abuse | camera `stream_url=http://127.0.0.1:8000/...` or an internal address | decide policy; today `http/https` are allowed |
| H-10 | Disk fill | evidence dir on a nearly full disk | event still created without clip |
| H-11 | Clean slate | delete `data\oceaneye.db`, restart | beach seeded, UI loads, no 500 |
| H-12 | Data hygiene | remove the 17 stale cameras / old jobs before a demo | list is readable during the demo |

---

## 5. Order of work I'd follow

1. Rotate secrets (H-01).
2. Record/collect positives and hard negatives (§2). Without this, stop — everything below is guesswork.
3. Wire pose into `SessionConfig`/`default_pipeline` (turns D6 green), then re-run Suite B.
4. Make the rules fps-invariant: compute speeds over a fixed time lag (e.g. ≥ 0.5 s) instead of
   consecutive frames; make bobbing amplitude scale with detector noise (D1–D3).
5. Fix timestamps for jobs (D7) and add the review-then-send step if you want it (G-03).
6. Phone suite F on the real devices.
7. Lock the thresholds from the B-10 sweep and write down the clip count behind every number.

## 6. What I could not run

Real YOLO inference, real phones, real push. I had no GPU/torch in my sandbox, so Suites B, C, D and F
need your machine. The behaviour-layer results are synthetic and show *structure* (fps dependence,
threshold caps), not field accuracy.
