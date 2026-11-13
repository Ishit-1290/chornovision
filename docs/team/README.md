# ChronoVision — Codebase Walkthrough for Five Presenters

This folder splits the **entire** ChronoVision codebase into **five parts**, one document per
presenter. Each document is a self-contained explainer: scope, the ideas to convey, a file map,
the end-to-end flow inside that part, the design decisions behind it, the honesty/security notes,
the tests that prove it, likely questions, and where it connects to the other parts.

Together the five parts cover every tracked source file; there are no gaps and no overlaps other
than the explicit cross-references between neighbouring parts.

## The division of labour

| Part | Document | Audience-facing theme | Backing code |
|---|---|---|---|
| 1 | [`part-1-foundation-and-security.md`](part-1-foundation-and-security.md) | How the backend boots, validates configuration, and protects every request | `backend/app` core + `auth/` + `migrations/` |
| 2 | [`part-2-cameras-monitoring-and-live.md`](part-2-cameras-monitoring-and-live.md) | Cameras, their lifecycle, the monitoring control plane, and opt-in live view | `backend/app` camera/monitoring/live code |
| 3 | [`part-3-events-evidence-and-delivery.md`](part-3-events-evidence-and-delivery.md) | The event contract, deterministic messages, evidence persistence/retention, real-time delivery, and offline evaluation | `backend/app/events`, `event_messages`, evidence + internal/realtime, `evaluation/` |
| 4 | [`part-4-vision-worker.md`](part-4-vision-worker.md) | The independent video-analysis process: ingest → detect → track → temporal rules → evidence → handoff | `vision/` |
| 5 | [`part-5-frontend-and-operations.md`](part-5-frontend-and-operations.md) | The operator's browser dashboard, the zone-setup wizard, and how the whole system is deployed, run, and verified | `frontend/`, `deploy/`, `scripts/`, `docker-compose.yml`, docs, `evaluation/sample/` |

## The one thing everyone must agree on

ChronoVision is a **three-process system** with two independent video paths:

```
                     ┌──────────────────────────────┐
   browser ──REST/WS─▶│  FastAPI backend (part 1–3)  │──SQLAlchemy──▶ PostgreSQL
      │              └──────────────┬───────────────┘
      │                             │ authenticated internal HTTP (X-Internal-Token)
      │                             ▼
      │              ┌──────────────────────────────┐      ┌───────────────────┐
      │              │  Vision worker (part 4)      │─────▶│ data/evidence/…   │
      │              └──────────────────────────────┘      └───────────────────┘
      │
      └──WebRTC/WHEP──▶ MediaMTX gateway (opt-in, part 2/5)  ──RTSP──▶ camera
```

- **Analysis path** (camera → decoder → detector → tracker → event rules → evidence → backend):
  runs without a browser; lives in the vision worker.
- **Viewing path** (camera → MediaMTX → WebRTC → browser): opt-in, separate, never shares the
  analysis connection.
- **No runtime LLM / no generative text.** Every event message is a deterministic template. This
  is a hard constraint (CON-01 / D-09), repeated in parts 3 and 5.

Two behavioural rules that recur in every part and are worth stating up front:

1. **Monitoring never starts by itself.** Opening the dashboard, the WebSocket, or a camera row
   never starts analysis; only an explicit Start action does (FR-48).
2. **Nothing is fabricated.** If an input (door state, pose, package classes) or a result (GPU,
   real-camera accuracy, browser WebRTC) does not exist, the system says so rather than guessing.

## Suggested presentation order

1 → 2 → 3 (backend story, bottom-up), then 4 (the engine), then 5 (the surface + how it's proven).
Or run 4 early if the audience is ML-oriented. Read the part doc **and** skim the files it names —
the doc is a map, not a replacement for the code.
