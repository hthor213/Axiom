# 023: Idea Fab — Freeform Spec Drafting from the Dashboard

**Status:** merged → spec:025

## Note

This spec has been absorbed into spec:025 (Dashboard Queue Redesign). The Idea Fab feature is now the "Idea Fab" section of 025, sharing the spec viewer/editor component with the "Review Spec" flow. All Done When items have been carried over.

## Original Goal

Add a freeform text input at the top of the dashboard where the developer can dump raw ideas, half-formed thoughts, feature requests, or bug descriptions. The system uses an LLM to transform this into a structured spec draft (numbered, with Done When criteria, architecture section, prerequisites) that the developer can review, edit, and promote to an actual spec file in the repo.

This is the "napkin sketch to blueprint" pipeline. The developer thinks in prose; the system outputs in spec format.

## User Flow

```
1. Developer types in the Idea Fab text area:
   "need a way to share this platform with arnar so he
    can try it on his project. should export the harness
    and adversarial stuff but obviously not my keys"

2. Clicks "Draft Spec" (or Cmd+Enter)

3. LLM generates a structured spec:
   - Suggests a number (next available in the band)
   - Title
   - Goal section (expanded from the raw idea)
   - Architecture (if applicable)
   - Constraints (inferred + standard ones)
   - Prerequisites (cross-referenced against existing specs)
   - Done When criteria (concrete, testable)

4. Developer sees the draft in an inline editor
   - Can edit any section
   - Can change the spec number
   - "Save as Draft" → writes to specs/<number>-<title>.md with Status: draft
   - "Discard" → gone

5. Spec appears in Queue view for future execution
```

## Architecture

```
┌──────────────────────────────────────┐
│  Idea Fab (top of dashboard)         │
│  ┌──────────────────────────────────┐│
│  │  textarea: freeform input        ││
│  │  [Draft Spec]  [Examples v]      ││
│  └──────────────────────────────────┘│
│                                      │
│  ┌──────────────────────────────────┐│
│  │  Spec Preview (collapsible)      ││
│  │  Rendered markdown + edit mode   ││
│  │  [Save as Draft] [Discard]       ││
│  └──────────────────────────────────┘│
└──────────────────────────────────────┘
         │
         ▼  POST /specs/draft
┌──────────────────────────────────────┐
│  API: calls LLM with:               │
│  - User's raw text                   │
│  - Existing spec index (for context) │
│  - Spec template (format to follow)  │
│  - Next available number in band     │
│                                      │
│  Returns: structured spec markdown   │
└──────────────────────────────────────┘
```

## API Endpoint

```
POST /specs/draft
Body: { "idea": "freeform text", "band": "mvp" }
Response: {
    "number": "021",
    "title": "platform-sharing",
    "markdown": "# 021: Platform Sharing...\n\n**Status:** draft\n\n...",
    "suggested_prerequisites": ["010", "011"]
}

POST /specs/save
Body: { "number": "021", "filename": "021-platform-sharing.md", "content": "..." }
Response: { "status": "saved", "path": "specs/021-platform-sharing.md" }
```

## LLM Prompt Context

When generating a spec draft, the LLM receives:
- The raw idea text
- The spec template format (from an existing spec as example)
- INDEX.md (to understand existing specs and avoid overlap)
- The vision spec (000) for project context
- Available spec numbers in the requested band
- Standard constraints from CLAUDE.md

The LLM is used for intelligence (structuring the idea) — the server handles file I/O, numbering, and git.

## Constraints

- The LLM drafts; the human approves. No spec is written to disk without explicit "Save" action.
- Generated specs must follow the exact format of existing specs (Status, Goal, Architecture, Done When, etc.)
- Done When items must be concrete and testable — the prompt enforces this
- Idea Fab uses the same auth as the rest of the dashboard
- Raw ideas are not persisted unless saved as specs (no idea backlog in DB — that's what the spec draft status is for)

## Prerequisites
- spec:015 (Dashboard) — UI home for Idea Fab
- spec:012 (Model Registry) — to route the drafting call to an appropriate model

## Done When
- [ ] Dashboard has a freeform text input area at the top of the Queue view
- [ ] "Draft Spec" button sends text to API and returns structured spec markdown
- [ ] Generated spec follows existing format (Status, Goal, Architecture, Constraints, Prerequisites, Done When)
- [ ] Inline preview shows the generated spec with edit capability
- [ ] "Save as Draft" writes the spec file to the repo's specs/ directory
- [ ] Generated Done When items are concrete and verifiable (no subjective criteria)
- [ ] Spec numbering auto-detects next available number in the appropriate band
- [ ] Prerequisites are cross-referenced against existing specs in INDEX.md
