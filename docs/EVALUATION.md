# ChronoVision — Event Evaluation

**Phase:** 9 (G §16.2, W §15; FR-44/AC-14)
**Status:** Infrastructure complete and verified. **No real-footage accuracy has been
measured** — the host has no labelled recordings or camera; see "Honest scope" below.

This document defines how ChronoVision events are compared against human-annotated reference
events, the fixed matching rules used before any score is calculated, the metrics computed, the
on-disk label format, and the limitations of the current dataset.

## Honest scope (read first)

- The tooling computes **detection-quality metrics** (precision, recall, F1, false
  positives/negatives, timing error, occupancy error) from two event collections.
- The repository ships a **clearly-synthetic** sample dataset (`evaluation/sample/`) purely to
  demonstrate the format and the tooling. It is **not real footage** and its numbers are **not
  a detection-accuracy result**. Do not quote them as system accuracy.
- Scoring real accuracy requires labelled footage (annotated reference events) and real
  detected events from the running pipeline; neither is available in this environment. The
  instructions define exactly how to supply them.

## Annotation conventions

An annotator watches a recording and records **reference events**: one row per activity
occurrence they can defend. Conventions:

1. **One event per occurrence.** Two people entering close together are two
   `person_entering` events (not one), each with its own start time.
2. **Start time = the moment the activity becomes clearly true** (e.g. the instant a track
   crosses the entrance boundary), recorded in **UTC** with an explicit offset
   (`...+00:00`).
3. **End time = the moment the activity clearly ends**, when the activity has a duration
   (`person_motionless`, `crowd_forming`, `fall_from_bed`, `door_open_too_long`, ...). Omit
   `end_time` for instantaneous events (`room_occupancy_change`, and package/entry events the
   annotator treats as instantaneous).
4. **Occupancy activities** (`room_occupancy_change`, `crowd_forming`) also record the
   integer `occupancy` count observed at that moment so counting error can be computed.
5. **Mark ambiguous cases** with `"uncertain": true` rather than guessing; they are still
   scored but the flag is preserved in the report so the sensitivity of results to ambiguous
   labels can be reviewed.
6. **Camera scope matters.** Every reference event names the `camera_id` it was observed on;
   events are only ever matched within the same camera.
7. **No event is "close enough".** If the annotator did not see it, it is a miss (false
   negative for the system); do not add convenience rows.

## Label file format

Both the reference labels and the detected-event export use the same JSON shape: an object with
an `events` list (a bare top-level list is also accepted). The optional `dataset` block is
informational metadata (it records the `synthetic` flag for the sample).

```json
{
  "dataset": { "name": "my-recording", "synthetic": false,
               "notes": "camera 1, 2026-01-02, 09:00-09:30 UTC" },
  "events": [
    { "camera_id": 1, "event_type": "person_entering",
      "start_time": "2026-01-02T09:00:03+00:00",
      "end_time":   "2026-01-02T09:00:05+00:00", "zone_id": "front_door" },
    { "camera_id": 1, "event_type": "room_occupancy_change",
      "start_time": "2026-01-02T09:01:10+00:00", "occupancy": 2 },
    { "camera_id": 1, "event_type": "fall_from_bed",
      "start_time": "2026-01-02T09:30:00+00:00",
      "end_time":   "2026-01-02T09:30:05+00:00", "uncertain": true }
  ]
}
```

Reference-event fields: `camera_id`, `event_type`, `start_time`, `end_time` (optional),
`zone_id` (optional), `occupancy` (optional int), `uncertain` (optional bool).
Detected-event export adds `event_id` (optional).

Detected events can instead be read directly from the database (`--from-db`), in which case the
occupancy count is taken from the event `attributes["occupancy_count"]` produced by the
occupancy rule.

## Matching rules (fixed before scoring)

Defined in `backend/app/evaluation/matching.py`; they are fixed and documented rather than
tuned per dataset.

1. **Scope.** Events are compared only within the same `(camera_id, event_type)`. A detection
   can never match a reference event of a different activity or camera.
2. **Correspondence.** Within a scope, a reference and detected event correspond when **either**
   their `[start, end]` intervals overlap (both ends present), **or** the absolute difference of
   their start times is within the tolerance (`DEFAULT_TOLERANCE_SECONDS = 5.0`, overridable
   with `--tolerance-seconds`).
3. **One-to-one, best-first.** Candidate pairs are matched greedily by smallest absolute
   start-time difference, so each reference matches at most one detection and vice versa.
4. **Accounting.** Unmatched reference events are **false negatives** (missed events); unmatched
   detections are **false positives** (false alarms). A matched pair is a **true positive**.
5. **Errors.** For each matched pair the signed start error is `detected.start −
   reference.start` (positive = late); end-time error and occupancy error are reported where
   both sides carry a value.

The tolerance is a knob of *matching*, not of the detector, and is reported with every run so
results stay interpretable.

## Metrics

Per activity (`ActivityMetrics`):

- true positives, false positives, false negatives;
- precision, recall, F1 (each `null` when its denominator is zero — never fabricated);
- start-time error: signed mean, median absolute, 95th-percentile absolute (seconds);
- end-time error: signed mean (seconds), where both ends exist;
- occupancy error: mean and max absolute error, where both sides carry a count.

Aggregate (`EvaluationReport`):

- **micro** precision/recall/F1 (pooled over all activities) and **macro** F1 (mean of the
  per-activity F1 values that are defined);
- **false alarms per hour** (`false_positives / window_hours`, when `--window-hours` is given);
- **missed-event rate** (`false_negatives / total reference events`).

## Running an evaluation

```bash
cd backend

# Score a detected-event JSON export against reference labels:
./.venv/bin/python -m app.evaluation \
  --labels /path/to/labels.json \
  --detected /path/to/detected.json \
  --window-hours 0.5 \
  --output /tmp/eval-report.json

# Or score persisted events directly from the configured database (read-only):
./.venv/bin/python -m app.evaluation --labels /path/to/labels.json --from-db
```

The command prints a per-activity table (all eight canonical activities, with an `*` marking the
occupancy activities) and writes a machine-readable JSON report with `--output`.

## Sample dataset

`evaluation/sample/synthetic_labels.json` (8 reference events) and
`synthetic_detected.json` (9 detected events, including 2 false positives and 1 missed
`package_left_at_entrance`) are **hand-authored synthetic data**, clearly marked
`"synthetic": true`. They demonstrate the format and produce a deterministic tool result
(micro precision 0.7778, recall 0.875, F1 0.8235) used to regression-test the tooling. The
`package_left_at_entrance`, `door_open_too_long`, `crowd_forming`, etc. rows exist to exercise
every activity's reporting path, not to claim the pipeline detects them (the detector is
person-only; see `docs/KNOWN_LIMITATIONS.md`).

## How to measure real accuracy (procedure)

1. Record footage from the target camera and export it where the annotator can step frame by
   frame.
2. Annotate reference events into the JSON format above; note the observation window
   (`--window-hours` = window length in hours) for false-alarm rate.
3. Run the pipeline over that footage and collect the detected events (JSON export or
   `--from-db`).
4. Run `python -m app.evaluation` and archive the JSON report with the footage's date, camera,
   pipeline commit, and detector weights used.
5. Report per-activity precision/recall/F1 with the tolerance and window stated, and always
   alongside the dataset description — never a bare headline number.
