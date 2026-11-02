# ChronoVision — OpenCode Agent Instructions

## Project source of truth

The project is developed using OpenCode CLI with DeepSeek V4.1 Flash.

Read these existing documents before making implementation decisions:

- `../guidelines.md` — project guidelines and constraints.
- `../workflow_requirements.md` — implementation workflow, requirements, and milestones.

These documents are maintained outside this repository. Do not overwrite, rename, move, or duplicate them without the user's approval.

If a referenced document is missing or unreadable, ask the user to provide it. Do not invent its contents.

Use `docs/IMPLEMENTATION_PROGRESS.md` to track implementation status and `docs/DECISIONS.md` to record important architectural decisions and unresolved questions.

## Core constraints

- Follow the existing project guidelines and workflow.
- No runtime LLM, generative summaries, or text-generation service. Event messages must use deterministic templates.
- Process camera streams in independent background workers, not ordinary HTTP handlers.
- Keep video analysis independent of browser sessions.
- Start with one camera; scale after testing and benchmarking.
- Protect authentication, camera credentials, events, and evidence.
- Keep secrets, recordings, evidence, runtime logs, virtual environments, and database files out of Git.
- Preserve user changes and inspect Git status before editing.
- Do not silently change agreed requirements, architecture, or event semantics.

## Working across sessions

The user deliberately uses separate OpenCode sessions to control context usage.

At the beginning of each task:

1. Read this file.
2. Read `docs/IMPLEMENTATION_PROGRESS.md` if it exists.
3. Read the relevant sections of `../guidelines.md` and `../workflow_requirements.md`.
4. Inspect only the source files, interfaces, and tests relevant to the assigned task.
5. Check `git status` and existing changes.
6. Identify the current milestone and define a bounded task.

Do not load the entire project or repeat the full architecture unnecessarily. Prefer targeted inspection and documentation references.

At the end of each task:

1. Run relevant tests and report actual results.
2. Inspect `git diff` and `git status`.
3. Update `docs/IMPLEMENTATION_PROGRESS.md`.
4. Record consequential decisions in `docs/DECISIONS.md`.
5. Document unresolved questions, assumptions, blockers, and the next task.
6. Provide a concise handoff prompt suitable for a new OpenCode session.

Do not claim tests passed unless they were actually run successfully.

## Ask the user when necessary

Ask concise questions when a missing answer materially affects requirements, architecture, security, performance, cost, or an irreversible operation.

When practical, provide two or three options and recommend a default with a brief reason.

Do not ask the user to decide ordinary implementation details that are reversible and consistent with the documented architecture.

If an answer is not required for safe progress, document a reasonable assumption and continue. Do not repeatedly ask questions already answered in project documents.

Never silently resolve conflicts between project requirements and existing implementation. Explain the conflict and ask the user when their decision is necessary.

## Implementation discipline

- Work on one feature or tightly related group of changes at a time.
- Inspect the existing implementation before modifying it.
- Keep modules cohesive and interfaces explicit.
- Add or update tests with each feature.
- Handle errors, security, and relevant edge cases.
- Avoid unnecessary dependencies and unrelated refactoring.
- Never perform destructive Git operations or discard user work without explicit approval.
- Update relevant technical documentation.
- Review the final diff before reporting completion.

## Definition of done

A task is complete only when its acceptance criteria are addressed, relevant tests and checks are reported honestly, unintended changes are ruled out, documentation is updated, and remaining limitations and the next task are identified.