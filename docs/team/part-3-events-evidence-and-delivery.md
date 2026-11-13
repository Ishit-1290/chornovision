# Part 3 — Event Domain, Evidence Persistence, Real-time Delivery & Offline Evaluation

**Presenter brief.** This part answers: *What is an "event", how are event messages written without
any AI, how are events and their evidence stored and served, how do changes reach the browser, and
how is detection quality measured offline?* This is the semantic heart of the backend: the contract
the worker, the database, the API, and the UI all agree on.

**Code covered:** `app/events/{types,lifecycle,zones}.py`, `app/event_messages/{templates,renderer}.py`,
`app/services/{event_service,evidence_service,event_broadcaster}.py`,
routes `api/routes/{events,evidence,internal,realtime}.py`, `models/{event,evidence}.py`,
`schemas/{event,evidence,internal}.py`, `repositories/{events,evidence}.py`,
the `prune-evidence` half of `app/cli.py`, `app/evaluation/`, migration
`0003_events_evidence.py`.

---

## 1. The 60-second summary

- There are **eight canonical event types** (lowercase `snake_case`, D-10) and a **five-state
  lifecycle** `candidate → active → completed` with `uncertain`/`cancelled` branches (D-37).
  `completed` and `cancelled` are terminal.
- The event contract lives in one module, `app/events/types.py`, and is imported by **both** the
  backend and the worker — there is no duplicated schema.
- Messages are **deterministic templates** rendered **once at persistence time** and never
  regenerated (FR-30–FR-34, D-09/D-40). A renderer sanitises untrusted values and redacts URLs and
  credentials.
- Persistence is **idempotent**: unique `event_id` (deterministic UUIDv5), unique
  `(event_id, state_version)`, terminal-event immutability, and `IntegrityError` race handling make
  the worker's at-least-once handoff safe (D-40).
- **Evidence** is metadata in the DB and bytes on disk under `EVIDENCE_DIR` (`camera-<id>/YYYY/MM/DD/…`);
  the directory is never served statically and paths that escape the root are rejected (D-42).
- **Retention is explicit**, oldest-first, and never removes protected evidence (D-43).
- The **WebSocket** carries lightweight notifications only; REST stays the source of truth
  (D-44–D-49).
- **Evaluation is offline and deterministic** (`app/evaluation/`): reference vs detected events
  under fixed matching rules; the shipped sample is explicitly synthetic (D-55).

---

## 2. Key concepts to explain

| Concept | Where | Why it matters |
|---|---|---|
| Single canonical contract | `events/types.py` `EventSnapshot`, `EventTransition` | Worker and backend cannot drift; validators enforce time ordering and action↔status consistency |
| Event vs transition history | `models/event.py` `Event` + `EventTransitionRecord` | Current state is one row; immutable history is another (FR-21) |
| Deterministic id | `event_id` UUIDv5 | Retries can't duplicate an event |
| Monotonic revision | `state_version` | An older version is a stale no-op |
| Template system | `event_messages/templates.py`, `renderer.py` | No LLM; wording fixed; import-time self-check validates every template's fields |
| Sanitising renderer | `renderer.sanitize_display_text` | NFKC, strip control chars, redact `scheme://…` and `user:pass@`, drop markup, bound length |
| Evidence metadata vs bytes | `models/evidence.py`, `evidence_service.py` | DB stores relative paths; bytes are authorised through one endpoint |
| Idempotent registration | `uq_evidence_event_media` | One snapshot and one clip per event |
| Explicit retention | `evidence_service.run_retention`, `cli.py prune-evidence` | Deletion is never a capture side effect |
| Lightweight fan-out | `event_broadcaster.py`, `routes/realtime.py` | Payloads carry identifiers, not media |

---

## 3. File map

### 3.1 The contract and lifecycle

| File | What it does |
|---|---|
| `events/types.py` | `EventType` (8), `EventStatus` (5), `EventAction`, `EventSeverity`, `Certainty`, `ReviewStatus`; frozen `EventSnapshot` + `EventTransition` with UTC normalisation and ordering/consistency validators |
| `events/lifecycle.py` | `EVENT_TRANSITIONS`, `TERMINAL_EVENT_STATES`, `can_transition`, `transition` (+ `InvalidEventTransition`). `uncertain` is non-terminal |
| `events/zones.py` | `ZoneKind`, `BoundarySide`, `Zone`, `BoundaryLine`, `EventThresholds`, `CameraRulesConfig`, `parse_rotation`, `parse_camera_rules`, `validate_camera_configuration`; `ALLOWED_ROTATIONS` |
| `events/__init__.py` | Re-exports the contract so the worker imports the same symbols |

### 3.2 Deterministic messages

| File | What it does |
|---|---|
| `event_messages/templates.py` | `MessageTemplate`, `TEMPLATES` (one fixed format per type), `FALLBACKS`, `ALLOWED_FIELDS` |
| `event_messages/renderer.py` | `MessageRenderError`, `EventMessageContext` (`extra="forbid"`), `_validate_templates()` (import-time self-check), `sanitize_display_text`, `format_event_time`, `render_event_message`, `render_event`, `message_context_from_event` |

### 3.3 Persistence services, models, repositories, schemas

| File | What it does |
|---|---|
| `services/event_service.py` | `record_transition` — resolves the camera, renders the message, then create/no-op/apply with the three invariants (idempotent, monotonic, terminal-immutable); `get_event_by_id` |
| `services/evidence_service.py` | `register_evidence` (verifies the file before `available`), `_refresh_evidence_refs`, `protect_evidence`/`release_evidence`, `evidence_file_path`, `run_retention` (+ `RetentionReport`) |
| `models/event.py` | `Event` (current) + `EventTransitionRecord` (immutable history) |
| `models/evidence.py` | `EvidenceMediaType`/`EvidenceStatus`/`RetentionStatus` + `Evidence` |
| `repositories/events.py` | `list_events`/`count_events` with shared filters/ordering, `add_transition`, `list_transitions` |
| `repositories/evidence.py` | `list_by_event`, `list_retained` (includes protected so retention can account/skip), `total_stored_bytes` |
| `schemas/{event,evidence,internal}.py` | Read/*response* shapes; `InternalEventSubmission`/`InternalEvidenceSubmission` use `extra="forbid"` and re-validate through the contract |

### 3.4 Delivery (API + WebSocket) and CLI

| File | What it does |
|---|---|
| `api/routes/events.py` | `GET /api/events` (filters + pagination), `GET /api/events/{id}`, `PATCH /api/events/{id}` (review only; audits; never alters stored message/timestamps/state) |
| `api/routes/evidence.py` | `GET /api/evidence/{id}` (authorised bytes; 404/409/410), `PATCH /api/evidence/{id}` (pin/release; audits) |
| `api/routes/internal.py` | Worker channel: plan, state report (409 on illegal edge), reconcile, event submit, evidence register. `include_in_schema=False` |
| `api/routes/realtime.py` | `WS /api/ws`: session-cookie auth (`resolve_session`), `ready` frame, subscribe, concurrent send/receive loops, synchronous cleanup |
| `services/event_broadcaster.py` | `EventBroadcaster` (bounded per-subscriber queues, drop-oldest), `event_notification`/`camera_notification` |
| `app/cli.py` → `prune-evidence` | Runs retention (or a `--dry-run` path) and prints a report |

### 3.5 Offline evaluation

| File | What it does |
|---|---|
| `evaluation/model.py` | `LabelledEvent`, `DetectedEvent`, `EventPair`, `MatchOutcome`, `ActivityMetrics`, `EvaluationReport` |
| `evaluation/matching.py` | `DEFAULT_TOLERANCE_SECONDS = 5.0`; overlap-or-close matching, greedy one-to-one, unmatched → FP/FN |
| `evaluation/metrics.py` | Per-activity precision/recall/F1, timing/occupancy error, micro/macro F1, false alarms/hour, missed-event rate |
| `evaluation/dataset.py` | Loads labels/detected JSON (or ORM rows), reads `occupancy_count` from attributes |
| `evaluation/cli.py` | `python -m app.evaluation` (`--labels`, `--detected`/`--from-db`, `--tolerance-seconds`, …) |

---

## 4. How it works end to end

1. The vision worker's event engine (Part 4) produces an `EventTransition`. It is enqueued on the
   handoff (Part 4) and delivered to `POST /api/internal/events` with `X-Internal-Token`.
2. `event_service.record_transition` resolves the camera, **renders the message once**, and:
   - **new event** → insert the row + a transition record; a race on the unique `event_id` returns
     the existing row with `applied=false`;
   - **existing, stale** (`state_version <=` stored) → no-op;
   - **existing, terminal** → immutable no-op;
   - **otherwise** → apply the snapshot and append the transition.
3. Evidence metadata arrives at `POST /api/internal/events/{id}/evidence`; `register_evidence`
   verifies the referenced file exists inside the evidence root and only then marks it
   `available` (the on-disk size is authoritative).
4. The route publishes a lightweight notification; `EventBroadcaster` fans it out to connected
   browsers. The dashboard (Part 5) treats it as a cache invalidation and re-reads via REST.
5. An operator can `PATCH` review status or pin/unpin evidence — both audited, neither mutating
   the stored event.
6. Retention is run explicitly (`prune-evidence`): time expiry then storage cap, oldest-first,
   skipping protected evidence and reporting `blocked_by_protection` if the cap cannot be met.
7. Offline, `python -m app.evaluation` scores reference vs detected events and prints a report.

---

## 5. Design decisions worth calling out

- **D-10:** the eight canonical `snake_case` event types are fixed across DB, templates, API, UI,
  tests; changing them is migration work.
- **D-37/D-24:** the event lifecycle, including instantaneous events (entry/exit/occupancy) that
  open and complete immediately.
- **D-34/D-39:** `confidence` is only set from a real source; `certainty` carries
  high/medium/low/unknown; rules for missing producers stay inactive rather than inventing data.
- **D-38:** `room_occupancy_change` uses distinct wording; `crowd_forming` keeps the source
  "Occupancy threshold reached …".
- **D-40:** persistence invariants (idempotent by identity, monotonic revisions, terminal
  immutability) — the reason at-least-once delivery is safe.
- **D-41/D-42/D-43:** evidence on disk with relative paths, authorisation through one endpoint,
  explicit oldest-first retention that never evicts protected evidence.
- **D-44–D-49:** review as an audited mutation that never alters the stored event; the WebSocket as
  an authenticated notification channel; settings read-only.
- **D-55:** evaluation defines matching rules *before* scoring and ships only a synthetic sample.

---

## 6. Honesty & security notes to state plainly

- **No runtime LLM.** There is no prompt, network call, or model in `event_messages/` (CON-01/D-09).
- The message is stored, not regenerated: changing a template later does not rewrite history.
- `GET /api/evidence/{id}` is the only way to fetch bytes; the directory is never static-served and
  traversal/symlink escapes are rejected.
- `prune-evidence --dry-run` currently executes the same committing/unlinking retention path as a
  real run — flagged as a **deferred behavior fix** in `docs/DECISIONS.md` (D-76); mention it as a
  known open item, don't claim it's a safe dry run.
- The evaluation sample is **synthetic**; no real-footage accuracy is claimed.
- The broadcaster is in-process/single-worker; horizontal scale-out needs a shared bus.

---

## 7. Tests that prove this part

| Test file | Proves |
|---|---|
| `tests/test_event_contract.py` | Contract + lifecycle validators |
| `tests/test_event_zones.py` | Zone/rule/threshold configuration validation |
| `tests/test_event_messages.py` | Templates, sanitisation, fallbacks |
| `tests/test_event_persistence.py` | Idempotency, staleness rejection, terminal immutability |
| `tests/test_events_api.py`, `tests/test_event_review_api.py` | Event read + review endpoints/filters |
| `tests/test_evidence_api.py`, `tests/test_evidence_service.py`, `tests/test_evidence_protection_api.py` | Authorised delivery, path confinement, retention, pin/unpin |
| `tests/test_retention_verification.py` | End-to-end retention semantics |
| `tests/test_internal_api.py`, `tests/test_internal_events_api.py` | Worker→backend channel + event/evidence submission |
| `tests/test_event_broadcaster.py`, `tests/test_ws_api.py` | WebSocket auth + fan-out |
| `tests/test_evaluation.py` | Offline matching/metrics/CLI |

---

## 8. Likely questions

- *Where is the message generated?* In `event_service.record_transition` → `render_event`, exactly
  once, using `event_messages/`.
- *What if the worker retries an event?* Unique `event_id` + monotonic `state_version` make it a
  no-op.
- *Why is review a separate mutation?* So a human decision never corrupts the deterministic record
  (D-45).
- *How does the browser get updates?* A lightweight WS notification that invalidates React Query
  caches; the data is re-read over REST.

## 9. Connects to

- **Part 1** provides auth/CSRF/internal-token/DB.
- **Part 2** owns cameras, the zone configuration these events reference, and status.
- **Part 4** produces the transitions and evidence metadata, and renders nothing itself.
- **Part 5** displays events, plays evidence, records review, and shows settings.
