# Part 5 — Frontend Dashboard & System Operations

**Presenter brief.** This part answers two operator-facing questions: *What does the human use?*
and *How is the whole thing deployed, run, and proven?* It covers the React/TypeScript dashboard
(including the zone-setup wizard and the live player) **and** the operational glue — Compose,
MediaMTX config, the verification scripts, the documentation set, and the end-to-end story that
ties parts 1–4 together.

**Code covered:** all of `frontend/` (`src/`, `vite.config.ts`, `package.json`,
`eslint.config.js`); `docker-compose.yml`; `deploy/mediamtx.yml`; `scripts/`; `.env.example`;
`README.md`; `AGENTS.md`; `docs/`; `evaluation/sample/`.

---

## 1. The 60-second summary

- The dashboard is a **same-origin SPA** (React 19 + TypeScript + Vite + MUI 9). In development,
  Vite proxies `/api` **including the WebSocket upgrade** to the backend, so the HttpOnly session
  cookie and CSRF header behave identically in dev and production with no CORS.
- It never talks to PostgreSQL, never holds camera credentials, and never runs CV (FR-50). It talks
  only to FastAPI (REST + WebSocket) and, for live view, directly to the MediaMTX gateway.
- **REST is the source of truth.** The WebSocket carries lightweight notifications that simply
  invalidate React Query caches; a reconnect invalidates *everything* to recover missed updates.
- Server state lives in **TanStack Query hooks** (`hooks/queries.ts`); auth and realtime have their
  own providers; pages are thin.
- The **zone-setup wizard** is the most interesting UI: it draws zones over the camera preview,
  stores geometry normalised to the original camera frame (`[0,1]`), supports rotation, and emits
  exactly the `{ zones, event_rules }` JSON the backend validates — preserving keys it does not own.
- **Operations:** Compose runs PostgreSQL (core) and an optional `playback` profile for MediaMTX;
  `scripts/verify.sh` is the one-command gate; `verify_migrations.sh` / `verify_backup_restore.sh`
  use disposable clusters; `scripts/{start,stop}_local.sh` run the stack without Docker.

---

## 2. Key concepts to explain

| Concept | Where | Why it matters |
|---|---|---|
| Same-origin + Vite proxy | `vite.config.ts` | Cookies/CSRF work identically in dev and prod; no CORS |
| Fetch wrapper + CSRF echo | `api/client.ts` | Same-origin credentials on every request; `X-CSRF-Token` on writes; `ApiError`; 401 → global unauthorized event |
| Provider order | `main.tsx` | Router → Auth → Realtime → App; realtime needs the session |
| Protected routes | `auth/ProtectedRoute.tsx`, `App.tsx` | Renders `null` while probing the session to avoid a login flash; preserves intended destination |
| Cache-invalidation realtime | `realtime/RealtimeProvider.tsx`, `api/ws.ts` | Notifications, not state; bounded reconnect backoff |
| Query hooks | `hooks/queries.ts` | Polling for status (which is backend-projected), mutations with targeted invalidation; monitoring never auto-starts |
| Honest UI | `components/states.tsx`, `lib/errors.ts`, pages | Errors show status/detail; unavailable features are labelled, not faked |
| Normalised geometry | `wizard/coordinates.ts`, `convert.ts` | A pointer maps to the visible content rectangle, never screen pixels; geometry never depends on preview rotation |
| WHEP player | `lib/whep.ts`, `components/LivePlayer.tsx` | Native `RTCPeerConnection`, non-trickle ICE, `credentials: 'omit'` (no cookies to the gateway) |
| One-command verification | `scripts/verify.sh` | Tests + lint/format/typecheck + offline migration render |

---

## 3. File map

### 3.1 Bootstrap, routing, theme, API layer

| File | What it does |
|---|---|
| `main.tsx` | `QueryClient` (staleTime 5 s, 4xx no-retry) + provider tree inside `StrictMode` |
| `App.tsx` | Routes: `/login`; protected `ProtectedRoute` → `AppLayout` → Overview/Cameras/Events/EventDetail/Settings; `*` → NotFound |
| `theme.ts` | Dark MUI theme, compact typography, status-friendly colours |
| `api/client.ts` | `ApiError`, `request<T>`, `readCookie`, `apiUrl`, `CSRF_COOKIE_NAME`, `UNAUTHORIZED_EVENT` |
| `api/{auth,cameras,events,evidence,health,live,monitoring,settings}.ts` | Thin typed calls; `evidenceUrl()`, `buildQuery()` |
| `api/ws.ts` | `DashboardSocket` — URL derivation, JSON guard, bounded exponential reconnect |
| `api/types.ts` | TS mirrors of the backend schemas and the realtime message union |

### 3.2 Auth, realtime, hooks, layout, components

| File | What it does |
|---|---|
| `auth/AuthContext.tsx`, `auth-context.ts`, `useAuth.ts` | Session probe via `/api/auth/me`; global 401 → drop session; login/logout |
| `auth/ProtectedRoute.tsx` | Redirect unauthenticated users, preserving `from` |
| `realtime/RealtimeProvider.tsx`, `realtime-context.ts`, `useRealtime.ts` | Socket lifecycle; message → cache invalidation; `onOpen` invalidates everything; `connected` flag |
| `hooks/queries.ts` | Query keys + `useHealth`/`useCameras`/`useMonitoringStatus`/`useEvents`/`useEventDetail`/`useSettings`/`useLivePlayback`; mutations for monitoring, cameras, review, evidence retention, live start |
| `layout/AppLayout.tsx` | App bar, nav, live/offline chip, account menu + sign-out |
| `components/chips.tsx` | Status/severity/certainty/review/retention chips; humanised labels |
| `components/states.tsx` | `LoadingState`/`ErrorState` (with Retry)/`EmptyState` |
| `components/LivePlayer.tsx`, `LivePlaybackDialog.tsx` | WHEP `<video>` with rotation controls; dialog that starts/polls playback and persists rotation |

### 3.3 Pages

| Page | What it does |
|---|---|
| `LoginPage` | Sign-in form; 401 → "Invalid username or password." |
| `OverviewPage` | Stat cards, monitoring controls, recent events, cameras, live-availability notice |
| `CamerasPage` | Camera table + add/edit dialog (write-only credentials, advanced JSON) and mounts the Live dialog and the wizard |
| `EventsPage` | Filterable, paginated event timeline |
| `EventDetailPage` | Event metadata, review actions, evidence playback (snapshot/clip), transition history |
| `SettingsPage` | Read-only effective policy + storage usage |
| `NotFoundPage` | 404 |

### 3.4 Zone-setup wizard (`src/wizard/`)

| File | What it does |
|---|---|
| `wizardTypes.ts` | UI-only typed state (`WizardState`, `WizardZone`, `EventKey`, `ThresholdKey`, …) |
| `eventCatalog.ts` | 8 event definitions with honest availability + `requiredRoles()` |
| `thresholdCatalog.ts` | 12 threshold definitions with backend-grounded bounds/defaults |
| `convert.ts` | `configToWizard` / `wizardToConfig` / `validateWizard` / `newZoneId` — preserves unowned config keys and emits the exact `{ zones, event_rules }` shape, including `rotation` only when meaningful |
| `coordinates.ts` | `getContentRect`, `pointerToNormalized`, `toDisplayPoint`/`fromDisplayPoint`, `roundCoord` — normalised geometry, rotation-safe |
| `CameraPreview.tsx` | Live preview (or clearly-labelled placeholder) with a rotated, exactly-positioned overlay for drawing |
| `ZoneCanvas.tsx` | SVG drawing surface: polygons, boundaries with interior arrows, draggable vertices, pointer/touch input, inverse rotation |
| `ZoneEditor.tsx` | Toolbar + role picker + rotate/reset + selected-zone inspector + zone list |
| `StepChooseEvents.tsx`, `StepThresholds.tsx`, `StepReview.tsx` | The four wizard steps' bodies (choose / thresholds / review + advanced JSON) |
| `ZoneSetupWizard.tsx` | Orchestrator; saves via the camera PATCH and offers "Start monitoring" |

### 3.5 Operations (`deploy/`, `scripts/`, docs, Compose)

| File | What it does |
|---|---|
| `docker-compose.yml` | `db` (PostgreSQL 16, loopback-bound, named volume) + opt-in `mediamtx` (`--profile playback`) |
| `deploy/mediamtx.yml` | Gateway config: loopback Control API, WebRTC/WHEP, `sourceOnDemand`, anonymous loopback API, no camera sources (backend owns paths) |
| `scripts/verify.sh` | Backend + vision + frontend tests, all linters/formatters/typecheck, offline Alembic render |
| `scripts/verify_migrations.sh` | Disposable PostgreSQL cluster → `alembic upgrade head` + `alembic check` (drift) |
| `scripts/verify_backup_restore.sh` | Disposable cluster → `pg_dump`/`pg_restore` + evidence-tree check |
| `scripts/start_local.sh` / `stop_local.sh` | Start/stop backend + vision + frontend (+ optional MediaMTX) without Docker; logs to `logs/` |
| `evaluation/sample/` | Clearly-synthetic labels + detections for the offline evaluator |
| `docs/*.md` | Requirements traceability, architecture, plan, decisions, progress, testing, evaluation, operations, running locally, live playback, known limitations |
| `.env.example` | The complete, placeholders-only configuration template |

---

## 4. How it works end to end (operator view)

1. **Start:** `docker compose up -d db` (or the local system PostgreSQL), then
   `scripts/start_local.sh` starts backend + vision + dashboard (+ MediaMTX if enabled).
2. **Sign in:** the SPA probes `/api/auth/me`, sets cookies, and the realtime socket opens
   (`ready` frame).
3. **Configure a camera:** the Cameras page posts a redacted-safe payload; the backend validates the
   stream (SSRF) and zones (Part 2/3).
4. **Draw zones:** the wizard previews the feed (or a labelled placeholder), the operator draws
   over the content rectangle, and the wizard saves normalised `{ zones, event_rules, rotation }`.
5. **Start monitoring:** an explicit click flips the control plane; the worker (Part 4) connects and
   reports `active`; the dashboard updates via REST polling **and** WS invalidation.
6. **Watch events:** new events appear in the timeline; the detail page plays stored evidence and
   records review decisions.
7. **Live view (opt-in):** the dialog registers a gateway path and plays WHEP; rotating the view
   persists `configuration.rotation`, which also drives detection and evidence.
8. **Verify:** `scripts/verify.sh` (and the migration/backup scripts) prove the system without
   touching the real database or evidence tree, using disposable clusters.

---

## 5. Design decisions worth calling out

- **D-44–D-49** (Phase 7): the dashboard, real-time notifications as invalidations, the human
  review workflow, read-only settings.
- **D-47:** opening a page or socket never starts monitoring (repeated in the hooks, pages, and
  wizard tests).
- **D-48:** truthful live-view fallback — when playback is unavailable, stored evidence is the only
  media, and the UI says so.
- **D-62–D-65/D-68:** live view is opt-in, localhost-first, browser talks only to the gateway (no
  cookies, no camera source), and the backend is authoritative for the path.
- **D-69/D-72/D-73:** the wizard is dependency-free (inline SVG), and one per-camera rotation drives
  the preview, detection, and evidence while stored geometry stays in the original frame.
- **D-59/D-61/D-70:** one-command verification and a documented, scripted local runbook, including
  starting MediaMTX only when live playback is enabled.

---

## 6. Honesty & limitations to state plainly

- The dashboard **never** starts monitoring automatically or changes retention policy; deletion is
  an explicit CLI action.
- Camera credentials are write-only; a blank stream reference on edit means "leave unchanged".
- When there is no gateway, the live dialog shows an honest "unavailable" message — it never fakes a
  feed. The wizard shows a labelled placeholder for drawing.
- Live playback off by default; a real-browser WebRTC session and real IP cameras are not claimed in
  the docs.
- The evidence affordance for protection exists, but the **retention itself is backend/CLI-driven**.
- Known open items surfaced by the submission review (see `docs/DECISIONS.md` D-76) include the
  destructive `prune-evidence --dry-run` and an unguarded `new Date(since).toISOString()` on the
  Events page that can throw `RangeError` for an invalid date — mention them as deferred fixes.

---

## 7. Tests & verification that prove this part

- Frontend: 17 Vitest files — `api/client`, `api/ws`, `auth/ProtectedRoute`,
  `realtime/RealtimeProvider`, `lib/videoRotation`, `components/LivePlayer`,
  `components/LivePlaybackDialog`, `pages/{Login,Overview,Cameras,Events,EventDetail}`, and
  `wizard/{convert,coordinates,ZoneCanvas,ZoneEditor,ZoneSetupWizard}`. Test infra in `src/test/`
  (`setup.ts`, `render.tsx`, `fixtures.ts`).
- Scripts: `verify.sh` (all gates), `verify_migrations.sh` (drift), `verify_backup_restore.sh`
  (round-trip). Reproducible commands and prerequisites are in `docs/TESTING.md`.

---

## 8. Likely questions

- *How do cookies work in development?* Vite proxies `/api` (incl. WS) to the backend, so it's
  same-origin and the HttpOnly cookie + CSRF flow is identical to production.
- *What happens if the socket drops?* Bounded backoff reconnects, and `onOpen` invalidates all
  queries so nothing is stale.
- *How are zone coordinates stored?* Normalised `[0,1]` in the **original** camera frame; the
  preview can rotate without changing stored geometry.
- *Why not fake the live feed?* The project constraint is honesty: unavailable features are labelled,
  never simulated.

## 9. Connects to

- **Part 1** defines the cookies/CSRF/auth endpoints the SPA uses.
- **Part 2** owns the camera/status/live endpoints the pages call.
- **Part 3** owns the event/evidence/settings endpoints and the WebSocket the realtime provider
  consumes.
- **Part 4** produces the events, evidence, and the `configuration.rotation` the wizard and live
  player read/write.
