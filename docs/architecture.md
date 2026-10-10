# OceanEye — architecture

A **modular monolith**: one deployable API process with strictly separated modules, plus a separate
analysis-worker process per camera or job (the vision/risk pipeline and the alert API must not share a
process). Unbuilt capabilities are an interface plus a clearly labelled mock.

## Pipeline → modules

```
CAMERA -> INGESTION -> DETECTION -> TRACKING -> ZONE/ENV -> BEHAVIOUR -> RISK -> EVENT -> ALERT -> RESPONDER -> ACK -> ESCALATION -> OUTCOME
 camera/    camera/     vision/     vision/    environment/  risk/       risk/  events/  alerts/  websocket/   events/  alerts/      events/
                                                                                                  push/
```

Two processes:

```
[ worker process ]                                   [ API process ]
 FrameSource -> VisionPipeline -> ZoneGate ->         POST /api/events -> EventService -> repo
 BehaviorAnalyzer -> RiskEngine -> HTTP      ---->    (bus) EventCreated -> AlertService -> NotificationProvider
      (app/worker, app/vision, app/risk)              ├─> ConnectionManager -> WS /ws/alerts -> control room
                                                      └─> WebPushProvider  -> push service -> lifeguard phone
```

The API process never imports `app.vision`, `app.risk` or `app.worker`, and never loads a model.
Enforced by `tests/unit/test_architecture_boundaries.py`.

## Layers and dependency direction

```
api (routers, schemas)  ->  services  ->  core (entities, enums, exceptions, ports)
                                  ^
infrastructure (SQLAlchemy repos, local storage, providers, ws manager) implements ports
```

* `app/core` imports nothing outside `app/core` and no frameworks.
* Ports: repositories, clock and event bus in `core/interfaces`; domain-specific ports live in their
  module (`vision.*.base`, `environment.*.base`, `risk.engine.base`, `alerts.notifications.base`,
  `evidence.storage`).
* Only `app/main/container.py` chooses concrete implementations.
* API schemas (pydantic) ↔ domain dataclasses ↔ ORM models are three separate representations;
  mapping lives in each `api/schemas.py` and in `persistence/repositories/mappers.py`.

## Module responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `main` | factory, lifespan, container, middleware, error handlers, `/health`, `/ready`, static mounts | everything (composition) |
| `core` | entities (Beach, Camera, Zone, Event, Alert, PushSubscription), enums, value objects, domain events, exceptions, ports | – |
| `config` | `Settings` from `OCEANEYE_*`; production safety validation; `auto` resolution for worker slots | shared.hardware |
| `security` | Principal, Authenticator, role authorization, FastAPI deps, headers, validators | core |
| `camera` | camera registry; `CameraSource` / `FrameSource` contracts; OpenCV source with strided reads and reconnect | core |
| `vision` | `Detector`, `Tracker`, `PoseEstimator`, `VisionPipeline` contracts; YOLO + ByteTrack; overlay; media; **profiles** (hardware → model/imgsz/fps) | core, shared.hardware |
| `environment` | **beaches** (deployment site), place search + map tile proxy behind `PlaceDirectory`, zones, water motion, external data; `/zones`, `/weather`, `/beaches`, `/places`, `/map/tiles` | core, vision (Track) |
| `risk` | `DistressSignal`, `BehaviorAssessment`, `RiskInput`, `RiskAssessment`, `RiskEngine`; rule-based implementations; scoring parameters | core, vision, environment |
| `events` | event lifecycle service, commands, `/events` | core, risk (mapping only) |
| `alerts` | alert creation, notification boundary (websocket / web push / mock / composite), escalation + timeout monitor, `/alerts`, `/push` | core, events |
| `websocket` | `ConnectionManager` (implements `AlertBroadcaster`), subscription filter, `/ws/alerts` | core, alerts (schemas/ports) |
| `evidence` | `EvidenceStorage` port, local adapter, protected `/evidence/{event_id}/{kind}` | core, events |
| `persistence` | ORM models, Database (+ additive column sync), SQLAlchemy and in-memory repositories | core |
| `processing` | uploads, analysis jobs, worker supervisor (subprocesses), live frames, metrics, `/config/public` | core, environment.zones, shared.hardware |
| `worker` | separate process: frames → detection → tracking → zone → behaviour → risk → events + evidence over HTTP | vision, risk, environment, evidence |
| `web` | the two interfaces (control room on a PC, lifeguard app on a phone), service worker, manifests, icons | API over HTTP + WebSocket |
| `shared` | clock, in-process event bus, logging, **hardware probe**, error schema, FastAPI accessors | core |

`events`, `risk` and `vision` never import `alerts` or `websocket`. `alerts` never imports `websocket`.

## Inter-module communication

1. **Producer → API:** the worker POSTs `/api/events` as role `service`.
2. **Domain events:** `EventService` publishes `EventCreated / EventAcknowledged / EventEscalated /
   EventOutcomeRecorded` on the in-process bus; `alerts.handlers` subscribes. Handler failures are
   logged and isolated.
3. **Notifications:** `AlertService` → `NotificationProvider` (composite of websocket + web push + mock).
   One failing channel never blocks the others, and no channel can fail the alert itself.
4. **Acknowledgement:** client → `POST /events/{id}/ack` → `EventService` → repo → `EventAcknowledged`
   → alert updated → `alert.acknowledged`.
5. **Escalation:** manual, or `EscalationMonitor` → `EscalationService.process_timeouts()` →
   `EventService.escalate(automatic=True)`.

## Where self-sizing lives

Three pure pieces, so the policy is testable without a GPU:

* `app/shared/hardware.py` — measures CPU count, RAM and (via `nvidia-smi`) VRAM. Standard library
  only, so the API process can use it without ever importing torch.
* `app/vision/profiles.py` — `choose_profile(device, …)` → model, input size, frame rate, fp16, clip
  width. Used by the worker and by the Colab notebook, so both agree.
* `recommend_worker_slots()` — how many worker processes the machine can host.

`auto` / `0` in configuration means "ask the policy"; any explicit value overrides it for that field.

## Startup / shutdown

`create_app` → settings → logging → `build_container` → middleware, error handlers, routers, static
mounts → lifespan start: `create_schema()` (+ additive column sync), seed the deployment beach if none
exists, start the escalation monitor. Nothing heavy: no models, no network, no camera connections.
Shutdown stops the monitor, kills worker processes, closes sockets, disposes the engine.

## Security boundary

Central `Authenticator` → `Principal(role)` → `require_roles(...)` on every protected route and on the
WebSocket handshake. Roles: `operator`, `lifeguard`, `administrator`, `service`. `auth_mode=dev`
(header `X-Dev-Role`) is development-only and refused in production; `token` mode is a placeholder (501).

* Camera `stream_url` is accepted but never returned.
* Push endpoint URLs are stored (they are needed to deliver) but never returned; the API exposes only a
  hash and the label the lifeguard typed.
* Push payloads carry identifiers and a short summary — never evidence images or free text.
* Evidence is served only through an authenticated route; storage keys are validated and confined.
* Errors never include stack traces or echo submitted input.
* Production additionally refuses dev auth, a missing secret key, wildcard CORS and plain HTTP.

## Extension points (replace one implementation, change nothing else)

| Future work | Replace | Wired in |
|---|---|---|
| Fine-tuned swimmer detector | `YoloDetector` (any `Detector`) | `app/worker/session.py` |
| Another tracker (BoxMOT, …) | `ByteTrackTracker` | same |
| Pose (`arms_raised`) | `MockPoseEstimator` | same |
| Dynamic danger zones | `PolygonZoneGate`, `RepositoryZoneService` | container |
| Optical-flow water motion | `MockWaterMotionAnalyzer` | worker factory |
| Learned risk model | `RuleBasedRiskEngine` (implement `RiskEngine`) | worker factory |
| SMS / voice call alerts | new `NotificationProvider` | `_build_notifier` |
| PostgreSQL | change `OCEANEYE_DATABASE_URL`, add a driver + Alembic | persistence only |
| Object storage for evidence | new `EvidenceStorage` | container |
| Real authentication | `TokenAuthenticator` | container |
| Many cameras | already per-camera ids, zones, filters; one worker per camera | worker |
| Many beaches | `Beach` already exists; scope repositories by `beach_id` and bind principals to a beach | persistence + security |

## Known limitations (deliberate at this stage)

* Repositories are synchronous and called from async services (brief blocking on SQLite). WAL and a
  busy timeout are on; move to an async driver or a threadpool under real load.
* No cross-repository transaction. Schema changes are `create_all` plus an **additive-column** sync in
  `Database._add_missing_columns` — a stopgap that only ever adds nullable columns. Anything else needs
  a real migration tool; Alembic is the intended replacement.
* WebSocket fan-out is single-process. Web Push is not, which is why a phone is reachable and a second
  dashboard process would not be.
* One automatic escalation tier.
* Track ids are camera-scoped strings; there is no tracks table and no cross-camera re-identification.
* Beaches are a deployment-site record, not a tenancy boundary: every operator sees every beach.
