# ChronoVision — Open Questions

**Status:** Planning. See the status summary below for which questions are resolved
(`docs/DECISIONS.md` records the resolutions).
**Date:** 2026-10-30

## How to read this

For each question: **why it matters**, **options** (with a recommended default where
practical), and **whether a decision is required before implementation** (blocking) or
whether a reasonable assumption can be documented and progress can continue
(non-blocking). This follows `AGENTS.md`: ask when the answer materially affects
requirements, architecture, security, performance, cost, or an irreversible operation;
otherwise document an assumption and continue.

## Status summary

| ID | Question | Status | Where resolved |
|---|---|---|---|
| OQ-01 | Runtime LLM vs. deterministic-only | **Resolved** — no runtime LLM | Decision D-09 |
| OQ-02 | Canonical event-type identifiers | **Resolved** — lowercase snake_case | Decision D-10 |
| OQ-03 | Occupancy/crowd threshold + persistence | **Resolved** — configurable defaults (3 people / 15 s) | Decision D-35/D-36 |
| OQ-04 | Door-state determination method | Partially resolved — consumer contract fixed; producer deferred | Decision D-36/D-39 |
| OQ-05 | Bed/floor region + fall criteria | **Resolved** — predefined zones + configurable transition window | Decision D-35/D-36 |
| OQ-06 | Evidence buffer size + retention limits | **Resolved** — configurable; defaults confirmed (30 d / 25 GB, explicit deletion) | Decision D-11/D-43 |
| OQ-07 | Latency/throughput numeric targets | **Resolved** — measured via the extended Phase 9 harness; targets set empirically (D-58) | Decision D-58 |
| OQ-08 | Missing named docs (`PROJECT_GUIDELINES`, `API_SPEC`, `DATABASE_SCHEMA`, `TESTING`) | **Resolved** — parent docs referenced; `TESTING`/`EVALUATION`/`OPERATIONS`/`KNOWN_LIMITATIONS` created | Decision D-59 |
| OQ-09 | Vision worker ↔ backend handoff mechanism | **Resolved** — authenticated internal HTTP | Decision D-12 |
| OQ-10 | Human-review scope in initial version | **Resolved** — audited `review_status` mutation implemented (Phase 7) | Decision D-45 |
| OQ-11 | "Summaries" meaning under no-LLM constraint | **Resolved** (folded into D-09) | Decision D-09 |
| OQ-12 | Multi-camera timing in acceptance criteria | **Resolved** — multi-camera in initial acceptance; Phase 8 isolation + one-camera benchmark first | Decision D-50 |
| OQ-13 | Live-view inclusion timing | **Resolved** — originally deferred (D-48); **superseded for live view** by Phase 10 opt-in MediaMTX + WebRTC playback | Decisions D-48, D-62–D-65 |
| OQ-14 | Authoritative connection-time SSRF enforcement (DNS rebinding / redirect pinning) | **Resolved** — IP-literal pinning at connect time | Decision D-28 |

---

# Resolved decisions

## OQ-01 — Runtime LLM vs. deterministic-only  →  RESOLVED (no runtime LLM)

**Resolution.** The runtime contains **no LLM and no generative AI or text-generation
service**. Every event description is produced by deterministic templates rendered from
structured metadata (see `docs/ARCHITECTURE.md` §3.12 and Decision **D-09**).

**Preserved source-document conflict (must remain documented).** `../guidelines.md`
describes an LLM that converts event records into human-readable descriptions and
summaries (§1, §2, §4.4, §5.9, §12) and its acceptance criteria AC-11/AC-12 and §16.4
assume LLM-generated summaries. `AGENTS.md`, `../workflow_requirements.md`
(§1, §8, §17), and the task instructions forbid a runtime LLM and require deterministic
templates. The conflict is real and is **not** silently erased: this project deliberately
follows the no-runtime-LLM constraint, and `guidelines.md`'s LLM requirements are marked
as superseded. If LLM prose is ever required, it must be introduced as an explicit,
separate, non-critical offline/opt-in scope change — never as a runtime dependency of the
detection or event pipeline.

**Consequences for the guidelines' wording.**
- AC-11 ("camera-level and overall summaries are generated from structured events")
  becomes **deterministic aggregation** of structured events (counts/lists per camera and
  overall), not LLM prose.
- AC-12 ("LLM failure does not stop the core pipeline") becomes satisfied vacuously by
  the stronger property: **there is no runtime LLM dependency at all**.
- OQ-11 is resolved by the same decision.

---

## OQ-02 — Canonical event-type identifiers  →  RESOLVED (lowercase `snake_case`)

**Resolution.** Adopt **lowercase `snake_case`** canonical `event_type` identifiers, used
consistently across the API, database (`events.event_type`), message-template keys,
frontend labels/filters, and tests (Decision **D-10**).

**Canonical identifier set** (from `../guidelines.md` §8, which is already lowercase
snake_case and is declared the baseline requirements specification in §20):

| Activity | Canonical `event_type` | Message template |
|---|---|---|
| Person entering | `person_entering` | Person detected entering `{zone_name}` … |
| Person leaving | `person_leaving` | Person detected leaving `{zone_name}` … |
| Room occupancy change | `room_occupancy_change` | Occupancy update in `{zone_name}` … |
| Crowd forming | `crowd_forming` | Occupancy threshold reached in `{zone_name}` … |
| Door open too long | `door_open_too_long` | Door at `{zone_name}` has remained open … |
| Package left at entrance | `package_left_at_entrance` | A package appears to have been left … |
| Person motionless | `person_motionless` | A person has shown limited detectable movement … |
| Potential fall from bed | `fall_from_bed` | Potential fall detected near `{bed_zone_name}` … |

**Occupancy types — the explicit-source exception applied.** The instruction was to use
one occupancy-threshold event type "unless the source requirements explicitly require
distinct event types." `../guidelines.md` §8.3 explicitly requires this: *"These must be
represented as related but distinct event categories"* and lists two event types
(`room_occupancy_change`, `crowd_forming`). Because the source requirement is explicit,
the exception applies and **two distinct event types are retained**. (`../workflow_requirements.md`
§8 labels its single `OCCUPANCY_THRESHOLD_REACHED` as an *example* event type and is
therefore treated as illustrative, not as the canonical requirement.) This can be
consolidated to a single type later by a documented scope change if the user prefers.

**Naming superseded:** the UPPER_SNAKE_CASE names in `../workflow_requirements.md` §8
(`PERSON_ENTERED`, `PERSON_LEFT`, `OCCUPANCY_THRESHOLD_REACHED`, `DOOR_OPEN_TOO_LONG`,
`PACKAGE_UNATTENDED`, `PERSON_MOTIONLESS`, `POTENTIAL_FALL`) are treated as display
examples only and are **not** used as canonical identifiers.

---

## OQ-06 — Evidence buffer size and retention limits  →  RESOLVED (configurable; defaults proposed)

**Resolution.** `../guidelines.md` §11 and `../workflow_requirements.md` §9 require a
**bounded, configurable** rolling buffer and evidence window but establish **no exact
values**. Therefore every limit below is **configurable and versioned**, and the numbers
are recorded as **proposals, not confirmed requirements** (Decision **D-11**).

| Setting | Proposed default | Source basis |
|---|---|---|
| Rolling pre-event buffer window | 15 s per camera (decimated) | G §11 bounded buffer; no value given |
| Pre-event capture | 5 s | G §11 |
| Post-event capture | 5 s | G §11 (configurable post-event interval) |
| Clip duration | ≈ 15 s (pre + trigger + post) | G §11 short clip |
| Snapshot on trigger | Always | W §9 step 3 |
| Retention period | 30 days | G §15.5 retention policy; no value given |
| Evidence storage cap | 25 GB total (per deployment) | G §14 resource bounds; no value given |
| Evidence eviction order | Oldest first once time or size limit is reached | G §15.5 |

All values are proposals to be tuned in Phase 6/9 after benchmarking on the target
hardware. Deletion is user-visible and semi-irreversible, so the retention/storage-cap
defaults should be explicitly confirmed before Phase 6 ships.

**Confirmed before Phase 6 (2026-10-29; D-43).** The defaults above stand (30-day
retention, 25 GB storage cap, 5 s pre / 5 s post, 15 s rolling buffer, oldest-first
eviction, snapshot on every trigger), with one change for safety: **automatic
retention-on-registration is disabled** (`EVIDENCE_RETENTION_ON_REGISTER=false`), so
deletion is never a side effect of capture and runs only through the explicit
`chronovision-admin prune-evidence [--dry-run]` command (or an operator-scheduled job).
Protected (pinned) evidence is never deleted. See D-42/D-43.

---

## OQ-09 — Vision worker ↔ backend handoff  →  RESOLVED (authenticated internal HTTP)

**Resolution.** The initial prototype uses **authenticated internal HTTP** from the vision
worker to the FastAPI backend. No message broker, queue service, or direct DB write by
the worker (Decision **D-12**; consistent with `../workflow_requirements.md` §17, which
discourages Kafka/Redis without demonstrated need).

**Specification (applies when the endpoints are implemented in Phases 4 and 6):**

1. **Endpoints.**
   - `POST /api/internal/events` — normalized event create-or-update (worker → backend).
   - `POST /api/internal/events/{event_id}/evidence` — evidence metadata registration, or
     an equivalent evidence sub-resource (finalized in Phase 6).
2. **Authentication.** A shared secret token sent in a dedicated header
   (`X-Internal-Token`), sourced from configuration (`INTERNAL_API_TOKEN`). Compared in
   **constant time**; never logged; never returned in responses; required even on
   localhost. The internal endpoints are separate from the cookie-authenticated user API
   and are not exposed to browsers.
3. **Payload validation.** Pydantic request schemas with strict validation (reject
   unknown fields). `event_type` must match the canonical identifier set (OQ-02/D-10);
   `camera_id` must reference a configured camera; timestamps must be well-formed; status
   must be one of the lifecycle states. Invalid payloads are rejected with `422` and the
   error is surfaced, never converted into an empty success.
4. **Duplicate-event protection (idempotency).** The worker generates a stable
   `event_id` (UUID) that does not change across update submissions. The backend **upserts
   by `event_id`** (unique constraint), so a retried submission updates the existing
   record instead of creating a duplicate. A per-event monotonic `state_version` /
   `last_updated_at` lets the backend reject stale out-of-order updates. The worker also
   applies local suppression (one in-flight submission per event state).
5. **Retry behavior.** Bounded exponential backoff with jitter, **only** on transient
   failures (connection error, timeout, HTTP `408`, `429`, `5xx`). Validation/permanent
   failures (`4xx` other than 408/429) are **not** retried. Attempt count and backoff are
   configurable. After the attempt budget is exhausted, the payload is written to a
   **bounded local spool** and an error/health state is raised — never silently dropped.
6. **Error handling and observability.** Non-2xx responses return a structured error body.
   The worker distinguishes transient from permanent errors, records per-endpoint
   counters/metrics, and keeps event detection independent of handoff success (event
   state is authoritative locally; the backend is the persistence/notification layer).
7. **Out of scope for this mechanism.** No broker, no pub/sub, no cross-camera
   coordination. The interface is versioned; candidates are re-handled idempotently.

---

# Remaining open questions

## OQ-03 — Occupancy / crowd threshold and persistence  →  RESOLVED (configurable defaults)

**Resolution.** All occupancy/crowd values are explicit per-camera configuration in
`event_rules.thresholds` (Decision **D-35**), with documented proposal defaults:
`occupancy_retention_seconds=3`, `occupancy_persistence_seconds=2`,
`crowd_occupancy_threshold=3`, `crowd_persistence_seconds=15`,
`crowd_release_seconds=5`, `crowd_release_hysteresis=1`. The rule semantics are fixed by
**D-36**: retained-track counting (not raw frame counts), debounced instantaneous
`room_occupancy_change`, and persistent `crowd_forming` with hysteresis. These are starting
values to tune in Phase 9, not confirmed requirements.

---

## OQ-04 — Door-state determination method  →  PARTIALLY RESOLVED (contract fixed)

**Resolution so far.** Phase 5 fixes the **consumer** contract: `DoorOpenRule` takes an
explicit `DoorStateObservation(state, zone_id, confidence)`, measures open duration
monotonically, tolerates `UNKNOWN` for `door_unknown_tolerance_seconds` by holding the last
known state, and marks the event `uncertain` on prolonged unknown/stream end (D-36, D-39).
The rule never infers door state from person tracks.

**Still open.** The **producer** method — a lightweight per-camera classifier versus a
geometric/visual heuristic — is not implemented because the Phase 4 YOLO detector is
person-only. Recommended: configurable per-camera geometric heuristic first, classifier only
if evaluation demands it. This is a Phase 6/8 input-integration task and does not block the
Phase 5 rule engine.

---

## OQ-05 — Bed/floor region and fall criteria  →  RESOLVED (zones + configurable thresholds)

**Resolution.** Bed and floor regions are predefined camera-specific polygons in the
camera `configuration.zones`, referenced by `bed_zone_id`/`floor_zone_id`, consistent with
CON-03 (D-35). A potential fall requires a recent observed bed posture followed by a
low/lying posture outside the bed within `fall_transition_window_seconds=5`; a low posture
in a configured floor zone without the transition opens an `uncertain` event; upright for
`fall_confirmation_seconds=5` completes it; track/stream end marks it `uncertain` (D-36).
The event is labelled potential-fall only, never a medical conclusion. Numeric values remain
tunable proposals. Pose input is not produced by the Phase 4 detector (D-39), so the rule
stays inactive until a pose source is integrated.

---

## OQ-07 — Latency / throughput numeric targets  →  RESOLVED (measured, D-58)

**Issue.** `G` §14.1/§17 and `W` §15 require measured latency but state no targets.

**Resolution (2026-10-30, D-58).** The Phase 8 benchmark harness was extended (not replaced)
to measure per-camera processed/ingest FPS, latency p50/p95/p99, queue depth, dropped frames,
process RSS/CPU, **GPU availability** (reported honestly as unavailable when there is no CUDA
device), event-handoff delivery latency **and duplication rate**, and **recovery time** after a
simulated stream outage. Targets are therefore set **empirically** from measured runs and always
reported with the machine/environment and the configured (simulated) detector cost — never as a
real-time guarantee. Measured Phase 9 figures are in `docs/IMPLEMENTATION_PROGRESS.md`; the
synthetic-vs-real-footage distinction is preserved.

---

## OQ-08 — Missing named documents  →  RESOLVED (created, D-59)

**Issue.** `W` §12 names `docs/PROJECT_GUIDELINES.md`, `API_SPEC.md`, `DATABASE_SCHEMA.md`,
`TESTING.md`; only `DECISIONS.md` and `IMPLEMENTATION_PROGRESS.md` existed before Phase 0.

**Resolution (2026-10-30, D-59).** The parent requirement documents are **referenced, not
duplicated** (per `AGENTS.md`). The deliverables were created in the phases that needed them:
`docs/TESTING.md` (reproducible commands), `docs/EVALUATION.md` (labels + metrics),
`docs/OPERATIONS.md` (deployment/backup/restore), and `docs/KNOWN_LIMITATIONS.md` (AC-15). The
API surface lives in the README endpoint table plus the running FastAPI OpenAPI schema, and the
database schema lives in `docs/ARCHITECTURE.md` plus the Alembic migrations; a repo-local
`PROJECT_GUIDELINES.md` was **not** created (it would duplicate the parent docs). Whether a
repo-local `PROJECT_GUIDELINES.md` is still wanted can be raised by the user; the current
recommendation is to keep referencing the parents.

---

## OQ-10 — Human-review scope in initial version  →  RESOLVED (audited review mutation)

**Issue.** `G` §3.1 lists "optional human review"; `W` §11 exposes review status in
event details; `W` §19 (initial scope) does not mention review.

**Resolution (2026-10-30, D-45).** Review is implemented in Phase 7 as an **explicit,
audited** mutation: `PATCH /api/events/{id}` sets only `review_status`
(`unreviewed`/`confirmed`/`dismissed`/`corrected`) with an optional note, writes an
`audit_logs` row, and never alters the stored deterministic message, timestamps, lifecycle
state, severity, or confidence. Evidence protection is a separate audited mutation (D-46),
so review does not silently pin evidence. The dashboard exposes these on the event detail
page.

---

## OQ-12 — Multi-camera timing in acceptance criteria  →  RESOLVED (D-50)

**Issue.** `G` §17 AC-01 requires configuring and starting **multiple** streams, while
CON-08/NFR-13 require starting with one camera and benchmarking first.

**Why it mattered.** These are compatible in sequence but the acceptance wording could be
read as requiring multi-camera in the first release.

**Resolution (2026-10-30, D-50).** Multi-camera **is** in initial acceptance; the first
milestone proved one camera end to end and Phase 8 added per-camera isolation (independent
per-camera worker threads in one vision process) plus a reproducible benchmark
(`vision/benchmarks/`) that establishes the one-camera baseline before scaling. Both AC-01
and NFR-13/CON-08 are therefore satisfied in sequence. Process-per-camera isolation remains a
documented future option, not a blocker.

---

## OQ-13 — Live-view inclusion timing  →  RESOLVED (deferred by D-48; superseded for live view by D-62…D-65)

**Issue.** `G` §13.2 requires live camera view; `W` §4 says to validate the analysis
pipeline with prerecorded clips first and add browser live playback after continuous
processing is stable.

**Resolution (2026-10-30, D-48; revisited 2026-11-01, D-62…D-65).** Live playback was
**originally deferred** (D-48): no MediaMTX/WebRTC gateway was deployed, so the dashboard did
not fabricate a feed — it explicitly stated live view was unavailable and supported stored
snapshot/clip evidence only. **Phase 10** implements live view as an **opt-in** MediaMTX +
WebRTC (WHEP) path (D-62): `LIVE_PLAYBACK_ENABLED=true` **and** both `MEDIAMTX_API_URL`/
`MEDIAMTX_WEBRTC_URL` must be set, so the D-48 truthful fallback still applies whenever playback
is not enabled. Internal camera URLs/credentials stay on the backend (FR-54): credentials are
encrypted at rest and write-only (D-64), and the gateway source is SSRF-validated and IP-pinned
(D-65). This is documented in `docs/LIVE_PLAYBACK.md`.

---

## OQ-14 — Authoritative connection-time SSRF enforcement  *(RESOLVED in Phase 4 by D-28)*

**Issue.** Phase 3 validated camera stream references at **configuration time**
(`app/services/stream_validation.py`): scheme allow-list, no embedded credentials, and an
address policy that always rejects loopback/link-local/metadata/multicast/reserved/
unspecified destinations (see D-22). It deliberately did **not** open a connection, and
hostname resolution at configuration time was disabled by default.

**Why it mattered.** A configuration-time hostname check cannot defeat DNS rebinding (the
name can resolve differently — or be rebound — between validation and the actual
connection) or a redirect to a different, unvalidated address. Claiming comprehensive
runtime SSRF protection from a static URL check would have been inaccurate.

**Resolution (Phase 4, D-28).** The vision worker performs the authoritative check
immediately before opening a stream (`vision/net.py: resolve_and_validate`): it applies
the *same* policy to **every** address the host returns (fail closed if any candidate is
disallowed), then hands the decoder a URL whose host is the validated **IP literal**, so
OpenCV/FFmpeg cannot re-resolve and DNS rebinding cannot redirect the socket. Redirects and
alternate protocol handlers are not followed, and no generic URL-fetch/proxy endpoint
exists. This is covered by tests for IPv4/IPv6 literals, IPv4-mapped IPv6, metadata and
`localhost` hostnames, DNS-change/rebinding, and rejected schemes/credentials/addresses.

**Residual (documented, opt-in only).** `VISION_STREAM_HOST_MODE=hostname` keeps the
hostname in the URL, which is required for TLS certificate/SNI or virtual-host routing but
re-introduces re-resolution between validation and connection. It is not the default; the
`pin` mode is recommended and used unless explicitly overridden. The IP-literal pin also
means TLS certificate verification is against the IP in `pin` mode. This is recorded in
D-28 and `docs/ARCHITECTURE.md` §8.

---

## Assumptions adopted pending answers

Recorded here and in `docs/DECISIONS.md` so work can proceed safely:

1. Deterministic-only runtime (no LLM) — **now a confirmed decision (D-09)**, not merely
   an assumption.
2. One camera first; multi-camera is a later phase (CON-08).
3. Canonical event-type identifiers fixed per D-10.
4. Backend renders messages from normalized events (single enforcement point for D-09).
5. Predefined camera-specific polygon zones for entrance/room/bed/floor regions.
6. Evidence limits use the configurable proposed defaults in D-11 until confirmed.
