# 030: Spec Inference — Propose Specs from Existing Codebases

**Status:** done

## Goal

The platform is spec-driven: specs are the source of truth and code is a derivative. But most real-world projects weren't born that way. When the dashboard auto-discovers a GitHub repo that has code but no specs, there's a dead end — the user can see the project but can't use any spec-driven workflows (queue, build, review, adversarial).

This spec adds the ability to *infer* specs from an existing codebase. A deterministic scanner reads the project's structure, documentation, and package metadata. An LLM then proposes a vision spec and feature specs based on what it finds. The human reviews and approves before anything is written. This bridges the gap between "regular project" and "spec-driven project."

For projects that already have specs, the same scanning capability enables spec-reality sync: comparing what specs claim the project does versus what the code actually does.

## Architecture

```
┌─────────────────────────────────────────────┐
│  Dashboard: project selected, no specs      │
│  → "Infer from Code" button                 │
└──────��───────┬──────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │  Deterministic Scan │  (spec_infer.py)
    │  - README, docs     │
    │  - Directory tree   │
    │  - Package metadata │
    │  - Entry points     │
    │  - Language stats   │
    └──────────┬──────────┘
               │ ProjectSummary
    ┌──────────▼──────────┐
    │  LLM Inference      │  (Claude Sonnet)
    │  - Structured prompt│
    │  - Returns JSON     │
    │  - Vision + features│
    └──────────┬──────────┘
               │ [{number, title, filename, content}]
    ┌──────────▼──────────┐
    │  Human Review       │  (Dashboard preview)
    │  - Show each spec   │
    │  - Edit before save │
    │  - Save All commits │
    └─────────────────────┘
```

## Spec-Reality Sync (for projects with specs)

```
┌───────────────────────────────────┐
│  Existing specs + codebase scan   │
│  → LLM compares both             │
│  → Returns gap analysis:         │
│    - Features in code, no spec   │
│    - Specs with no matching code │
│    - Spec claims vs actual state │
└───────────────────────────────────┘
```

This is the LLM-powered complement to the existing deterministic drift detection (`lib/python/harness/drift.py`) which checks structural properties (stale specs, regressions, uncovered dirs) but cannot understand what the code *does*.

## Prerequisites
- spec:022 (Multi-Repo Dashboard) — project selector, clone flow
- spec:015 (Dashboard) — the UI being extended

## Done When
- [x] Deterministic codebase scanner reads README, docs, tree, packages, entry points without LLM
- [x] `POST /projects/{id}/infer-specs` sends scan to LLM and returns proposed specs as JSON
- [x] `POST /projects/{id}/save-specs` writes approved specs to project's `specs/` directory and commits
- [x] Dashboard shows "Infer from Code" button when a local project has no specs
- [x] Proposed specs are shown in a preview before saving — user can review content
- [x] Inferred specs follow the platform format: number, title, Status, Goal, Done When
- [x] Done When items in inferred specs are concrete and verifiable, not subjective
- [x] Spec-reality sync: `POST /projects/{id}/sync-specs` compares existing specs against codebase
- [x] Sync returns gap analysis: uncovered features, stale specs, spec-vs-code mismatches
- [x] Dashboard shows sync results with actionable suggestions (propose new spec, update existing)
