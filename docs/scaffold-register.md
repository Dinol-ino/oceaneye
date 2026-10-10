# Scaffold register

## From the PDF (source of truth)
Endpoints `POST/GET /api/cameras`, `GET /api/zones/{camera_id}`, `POST/GET /api/events`, `GET /api/events/{id}`,
`POST /api/events/{id}/ack`, `POST /api/events/{id}/escalate`, `GET /api/weather?lat=&lon=`, `WS /ws/alerts`;
Event / Camera / AlertPayload models; statuses `pending | acknowledged | escalated | resolved | false_alarm`;
distress signals (erratic movement, vertical bobbing, prolonged stillness, repeated submersion, arms raised);
SQLite -> PostgreSQL; local disk -> object storage; FastAPI + WebSockets; Web Push / SMS fallback; roadmap order.

## PROPOSED SCAFFOLD (not in the PDF - confirm or change)
* `GET /health`, `GET /ready` (required by the task brief).
* `GET /api/alerts`, `GET /api/alerts/{id}` (lifeguard client needs active alerts).
* `POST /api/events/{id}/outcome` (the PDF names resolved/false_alarm but lists no endpoint to set them).
* `GET /api/evidence/{event_id}/{clip|thumbnail}` (protected evidence access; the PDF shows bare `/clips/...` URLs).
* Role `service` for the vision/risk process; `RiskLevel` labels; event state-transition table.
* `ack_timeout_seconds=30` (taken from the PDF sample payload; an experimental parameter).
* Zone polygon coordinate space (image coordinates, unvalidated).
* Dev-header authentication; per-call repository sessions; in-process event bus; stub stream manager.
* WS protocol (`connection.ready`, `alert.created|acknowledged|escalated|closed`, subscribe/ping messages).

## Experimental parameters intentionally left unset
`risk_persistence_window_seconds`, risk level boundaries, signal weights (`RiskScoringConfig`).

## Added in the perception stage (roadmap Stages 1-4)
Implemented: OpenCV video/webcam/RTSP source, YOLO person detector, ByteTrack tracker, overlay, runner/CLI, Colab notebook.
PROPOSED SCAFFOLD: `tracks.jsonl` v1 schema; per-camera sequential track ids (`cam_01-T7`); `video_file` and `webcam`
camera source types (not creatable through the API, whose URL validator accepts network URLs only); detector/tracker
defaults (all experimental); H.264 re-encode only inside the notebook.

## Added for the prototype (PROPOSED SCAFFOLD – not in the PDF endpoint list)
`PUT /api/zones/{camera_id}` (normalised 0..1 polygons), `GET /api/places/search` and `/api/places/beaches-near`,
`GET /api/map/tiles/{style}/{z}/{x}/{y}.png` (provider key proxied), `POST /api/push/test`, `POST|GET /api/uploads`,
`/api/analysis/jobs*`, `/api/cameras/{id}/monitoring/start|stop`, `/api/live/cameras*`, `/api/metrics`,
`/api/config/public`, `/api/demo/incident` (labelled DEMO), worker callbacks under `/api/processing/*` (role service),
web UIs under `/ui`. Rule-based risk engine with experimental parameters; operators may register cameras.

## Intentionally NOT implemented
Pose, zone-breach logic, dynamic zone, optical flow, wave/tide logic, Open-Meteo calls,
reconnect logic for dropped streams, risk scoring, persistence logic for risk, real Web Push/SMS, real authentication,
migrations, Docker/Kubernetes, dashboard UI, lifeguard app, model weights/datasets.
