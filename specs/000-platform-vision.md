# 000: HTH AI Dev Framework Vision

**Status:** active

## What This Is

A multi-model development system where five distinct roles — Programmer, Adversary, Arbitrator, Mentor, and a Deterministic Server — collaborate to build software. The human writes specs defining what to build. The server picks up those specs, creates prompts, dispatches work, runs tests, and enforces quality gates. The Programmer writes code. The Adversary challenges it. The Arbitrator resolves disputes. The Mentor helps refine specs before code is written. No single model does everything. The server — pure Python, no LLM — owns the loop.

Any model can fill any role. The constraint is separation: the Programmer, Adversary, and Arbitrator must be different providers (so they can't collude), and the Mentor must differ from the Adversary (so the voice that helps write specs isn't the same voice that attacks the implementation). In this project, the user has assigned Claude as Programmer, Gemini as Adversary, GPT as both Arbitrator and Mentor — but those are choices, not requirements.

## The Roles

### The Programmer
Builds code in an isolated git worktree with full agent capabilities — sub-agents, 1M context analysis, tool use, file creation. The server tells it WHAT to build (a spec item with context). It decides HOW — planning, architecture, implementation, tests. Currently Claude via the Claude Code CLI.

### The Adversary
Reviews the Programmer's output adversarially through structured multi-round debate. Looks for bugs, security issues, missing error handling, spec drift, and insufficient tests. The Programmer rebuts. Issues the Programmer concedes are fixed. Issues it disputes escalate to the Arbitrator. Currently Gemini via the Google API.

### The Arbitrator
Invoked only when the Programmer and Adversary can't agree after up to 3 debate rounds. Reads both sides, picks a winner per disputed issue. A tie-breaker, not a reviewer — it only sees what was contested. Currently GPT via the OpenAI API.

### The Mentor
Two jobs, both constructive: (1) Helps refine specs before code is written — asks what's missing, what could be clearer, whether the "Done When" criteria are verifiable. The Programmer incorporates feedback into a revised spec for human approval. (2) Reviews the Programmer's build plan before execution — checks whether the approach is sound, flags risks, suggests improvements. The plan and mentor feedback become first-class pipeline artifacts stored in PostgreSQL and fed into both the execution prompt and adversarial review context. Not adversarial — a different posture than the Adversary. Currently GPT via the OpenAI API.

### The Deterministic Server
Pure Python. Not an LLM. This is what makes the system deterministic:
- **Picks up work from specs** — reads the queue, claims the next task, creates a git worktree
- **Creates prompts** — assembles spec context, task description, file size constraints, test requirements into structured prompts for each role
- **Runs tests** — executes pytest, checks file sizes against soft/hard caps, verifies spec alignment
- **Orchestrates the pipeline** — dispatches to Programmer → runs tests → dispatches to Adversary → manages debate rounds → escalates to Arbitrator → applies quality gates
- **Enforces termination** — max turns, time limits, failure counts, retry budgets. No LLM decides when to stop.
- **Owns state** — PostgreSQL-backed task queue, pipeline stage tracking, result storage. Neither the human nor any LLM is trusted for long-running memory.

### The Human
Writes specs. Approves or rejects results. Selects what to build next via a dashboard. Trusted for judgment and intent — not trusted for memory or process. The human's role is to define WHAT and WHY. The system handles WHEN, HOW, and WHETHER the result is acceptable.

## Who It's For

Developers using Claude Code who want a structured, repeatable approach to AI-assisted development — not "prompt and pray." Originally built for a solo developer managing ~40 projects, but designed to be adoptable by small teams.

## What Makes This Unique

1. **Multi-model by design** — Most AI dev tools use one model for everything. This system deliberately separates concerns across providers. The model that writes code never reviews it. The model that reviews code never judges disputes about it. This isn't just using multiple APIs — it's adversarial separation of concerns.

2. **Deterministic server owns the loop** — The server is Python, not an LLM. It decides what to build, when to stop, and whether results pass. LLMs are called for intelligence (writing code, reviewing code, resolving disputes) but never for orchestration, scheduling, or state management. Process is code.

3. **Specs are the source code** — Every piece of work starts with a numbered spec. "Done When" is written first. The code is a downstream artifact. The server verifies Done When items deterministically where possible.

4. **Debate, not review** — Not a single-pass code review. A structured multi-round debate where the Adversary challenges, the Programmer rebuts, conceded issues are fixed, and disputed issues escalate to a third-party Arbitrator. Up to 3 rounds before escalation.

5. **Works on any git project** — Point it at any git repository with specs, and the pipeline runs: queue work, build in a worktree, test, review, gate. The framework is project-agnostic. As a proof of concept, the system builds itself — the dashboard queues its own spec items, and "Merge & Deploy" rebuilds the running container.

## Core Concepts

### Development Methodology
- **Numbered spec system**: Band-based numbering (000 vision, 001-009 foundation, 010-099 MVP, 100+ versions, 900+ backlog) with topical INDEX.md. "Done When" written first. Under 60 lines. Verifiable criteria only. See `specs/README.md`.
- **Session lifecycle**: `/start` (cold start + awareness), `/checkpoint` (end of session sync), `/refresh` (mid-session save). Each skill is spec-aware and maintains continuity via LAST_SESSION.md, CURRENT_TASKS.md, BACKLOG.md.
- **Shared preamble**: Common protocol injected into all skills — AskUserQuestion format, spec awareness, session context, branch detection. Change it once, every skill updates.
- **Validation tiers**: 4-tier cost model — free static checks, cheap LLM-as-judge, full agent review, multi-model adversarial evaluation.

### Agents (Programmer's Toolkit)
The Programmer (currently Claude) has access to specialized sub-agents for complex work:
- **Maestro**: Multi-agent orchestrator. 5-file system (vision, architecture, current tasks, backlog, done), milestone tracking, delegation, course-correction.
- **Analyst**: 1M context codebase analyst. 5-phase methodology (scope, map, search, read, synthesize). For deep research and architecture review.
- **Dev server**: Config-driven remote operations. SSH, Docker, deploys with safety checks and protected port blocking.

### Dashboard & Runtime
- **Runtime** (spec:014): The Deterministic Server running on MacStudio. Dispatches work, verifies results, manages the full pipeline unattended for days.
- **Dashboard** (spec:015): Web UI at spliffdonk.com/dashboard. The Human's control plane — select specs, click "Run", review results, approve/reject, Merge & Deploy. Telegram pings on completion.
- **The 2-day cycle**: Check in → review results → select next work → click Run → close laptop → Telegram ping when done.

### Deterministic Harness
- **State machine**: Session lifecycle enforced via `.harness.json` — COLD → STARTED → WORKING → CHECKPOINTING → ENDED (with REFRESHING branch). Prevents drift over long sessions.
- **Gate checks**: Three deterministic gates enforce milestone transitions — Activation (BACKLOG → CURRENT), Completion (CURRENT → DONE), Checkpoint (session end). Each gate runs automatable validations.
- **Done When automation**: Spec "Done When" items are classified as automatable (file exists, grep, command, spec status) or judgment (left for LLM). Automatable checks run deterministically via `hth-platform harness check`.
- **Termination conditions**: Agents run within defined boundaries — goal completion, time limits, safety guardrails. Agents are autonomous loops with human-defined termination.

### Infrastructure
- **Credential vault**: age-encrypted YAML with provenance annotations (source, used_by). Human-reviewed selection via `.env.platform` manifests — the LLM never picks credentials.
- **Service configs**: YAML files describing non-secret infrastructure (server IPs, database ports, auth architecture).
- **CLI tool**: `hth-platform` command for generating .env files, SSH, service status checks, and project scaffolding.
- **Shared libraries**: Python and shell utilities (notifications, network detection, DB helpers).
- **Templates**: Project skeletons (FastAPI, React) pre-wired with `.env.platform` manifests.

## System Behavior

### Spec System

**What it does**: Provides a structured contract for every piece of work before implementation begins.
**Constraints**:
- "Done When" is written first — it defines the work
- Every criterion must be verifiable (a query, a command, a check — never subjective)
- Specs stay under 150 lines; if longer, split
- `/checkpoint` verifies Done When items and marks specs as done
- Band numbering makes maturity visible at a glance

### Session Lifecycle

**What it does**: Ensures knowledge survives across conversations and sessions start with full awareness.
- `/start` reads vision spec, scans active specs, checks LAST_SESSION.md, detects branch, reports what needs attention, sets up session crons
- `/checkpoint` verifies specs, updates BACKLOG.md/CURRENT_TASKS.md, writes LAST_SESSION.md
- `/refresh` saves mid-session state without ending the session
**Constraints**:
- All skills reference the shared preamble for consistent behavior
- Session state files (LAST_SESSION.md, CURRENT_TASKS.md, BACKLOG.md) are the handoff mechanism

### Orchestration

**What it does**: Transforms complex goals into structured, trackable execution.
- Maestro breaks goals into milestones with testable success criteria
- Delegates to specialized agents (analyst, dev server)
- Tracks progress, course-corrects when milestones fail
- Termination conditions define when agents stop — goal met or boundary hit
- The harness is the referee; skills are the playbook. The harness enforces, the LLM executes.
**Constraints**:
- CURRENT_TASKS.md stays small (2-3 milestones max)
- Scope creep goes to BACKLOG.md, not CURRENT_TASKS.md
- User validates at milestone boundaries

### Autonomous Runtime (spec:014) & Dashboard (spec:015)

**What it does**: Multi-day autonomous development with zero human presence. The five roles in action:
- The **Deterministic Server** claims tasks from the queue, creates worktrees, assembles prompts, runs tests, enforces termination
- The **Programmer** receives a full spec and builds — planning, architecture, implementation, tests
- The **Adversary** challenges the output through structured multi-round debate with the Programmer
- The **Arbitrator** resolves disputes the Adversary and Programmer can't settle
- The **Human** reviews results via the Dashboard, approves or rejects, selects next work
**Core principle**: We will never match Claude Code at multi-agent orchestration, context management, or tool use. But we are far better at deterministic workflows, persistent memory, cross-model verification, and termination enforcement. Each side does what it's best at.
**Constraints**:
- The server owns state and memory — neither the human nor the LLM is trusted for long-running memory
- The Programmer gets the full spec, not atomic sub-tasks — it uses maestro to plan and delegate
- The server assembles adversarial feedback and sends refined corrections back to the Programmer
- Termination conditions enforced in code: max_turns, time limits, failure counts

### Credential Vault

**What it does**: Stores all API keys and passwords in a single YAML file, encrypted with age.
**Constraints**:
- vault.yaml is NEVER committed — only vault.enc (encrypted)
- Every credential has `source` and `used_by` annotations
- age-key.txt stays on local machines only, never in git
- Credential selection is NEVER LLM-driven — always human-reviewed via `.env.platform` manifests

### CLI

**What it does**: 15 deterministic commands covering session lifecycle, harness operations, adversarial review, and infrastructure.
- `hth-platform start/checkpoint/refresh` — session lifecycle (project detection, spec scan, gate checks, commit prep)
- `hth-platform scan/drift` — spec health reporting and alignment checks
- `hth-platform harness start/status/check/gate` — state machine and gate evaluation
- `hth-platform adversarial resolve/run/report` — multi-model adversarial pipeline
- `hth-platform env generate` — vault → .env via manifest
- `hth-platform ssh/status/init` — infrastructure operations

### Dev Server Operations

**What it does**: Config-driven remote server management with safety rails.
**Constraints**:
- All connection details read from config.json — never hardcoded
- Safety check before any destructive operation (stop, restart, remove)
- Protected ports prevent accidentally killing shared services (databases, caches)

## Invariants

### Methodology
- All "Done When" criteria must be verifiable — not subjective
- Skills must support both legacy SPEC.md and new `specs/` directory projects
- The shared preamble governs how all skills ask questions and check specs
- Session crons are advisory only — they suggest, never act

### Security
- vault.yaml and age-key.txt must NEVER appear in git history
- Every credential in the vault must have a `source` annotation
- Credential selection is NEVER LLM-driven — always human-reviewed via `.env.platform` manifests
- Template files in `docs/` are never treated as active instructions

### Operations
- The platform repo must not break any existing project — migration is gradual
- Core CLI commands work offline (scan, drift, harness check, start). Network needed for adversarial pipeline, model registry refresh, ssh, status.
- All application services on MacStudio run inside Docker containers. Only infrastructure services (Apache, cloudflared) run bare. Stopping Docker must disable all project workloads.

## Architecture

```
platform/
├── specs/              # Numbered specs (000-vision, 001+ features)
├── credentials/        # Encrypted vault + example
├── services/           # Non-secret YAML configs (gitignored)
├── cli/commands/       # Click CLI (15 subcommands)
├── lib/python/
│   ├── harness/        # 19 modules — deterministic session lifecycle
│   ├── adversarial/    # 9 modules — multi-model adversarial pipeline
│   ├── registry/       # 4 modules — task-aware model resolution
│   ├── runtime/        # 5 modules — autonomous runtime (server, DB, worktrees, MCP)
│   ├── orchestrator/   # Autonomous build loop
│   └── platform_*.py   # Shared utilities (network, telegram, db)
├── dashboard/          # FastAPI API + React SPA (spliffdonk.com/dashboard)
├── templates/          # Project scaffolds (FastAPI, React)
├── tests/              # 471 pytest tests (harness, runtime, dashboard)
└── docs/
    ├── references/           # Influence interviews, model registry sources
    ├── comparison.md         # Ecosystem comparison (25+ frameworks)
    ├── template_skills/      # Copyable skill templates
    └── template_agents/      # Copyable agent templates

~/.claude/
├── skills/          # Thin judgment-only layers (~195 lines total)
│   └── shared/      # Common preamble (credential boundary, AskUserQuestion)
└── agents/          # Maestro + Analyst (~124 lines total)
```

## What This Is NOT

- Not a "vibe coding" tool — this is structured, spec-driven development
- Not a prompt library or persona collection — skills are thin judgment layers (319 lines) backed by 9,000+ lines of deterministic Python
- Not a CI/CD system (projects handle their own deployment)
- Not a secrets manager with access control (the vault is for individual/small team use)
- Not a replacement for project-specific configs (only shared infrastructure)
- Not a running dependency for any project (projects get .env at bootstrap, not runtime)

## Trade-offs

- **Correctness over speed**: Our system optimizes for knowledge retention and constraint propagation, not LOC/day. One correct constraint today prevents ten debugging sessions next month.
- **Depth over breadth**: 3 deep, composable agents beat 16 shallow personas. Each skill is spec-aware and session-continuous.
- **Numbered specs over monolithic SPEC.md**: Smaller, focused, verifiable. Under 60 lines each. "Done When" written first. Band numbering makes maturity visible.
- **Session lifecycle as skills, not automation**: /start and /checkpoint are deliberate checkpoints, not background processes. You choose when to anchor knowledge.
- **age over GPG/Vault/1Password CLI**: Simplest encryption for individual/small team use. No daemon, no cloud dependency.
- **CLI-first over IDE lock-in**: Claude Code's native features (CronCreate, Agent tool, worktrees) are the platform. No IDE dependency.
- **Human-reviewed credentials over LLM selection**: Safety invariant, not a missing feature.
- **Gradual migration**: Existing .env files untouched. Add .env.platform per-project as touched.
- **Deterministic harness over rigid protocols**: Execution order enforced through a lightweight state machine and gate checks rather than standardized tool protocols. The harness provides rails without removing agency. Skills remain LLM-driven; the harness validates transitions.

## Open Questions

- [ ] Should the vault store the Google service account JSON file, or just reference its path?
- [ ] How to handle credential rotation — manual vault update or automate?
- [x] ~~Should EARS-style acceptance criteria replace or augment Done When prose?~~ Resolved: the deterministic harness automates verifiable Done When checks, making EARS-style criteria the default for automatable items.
- [x] ~~Should recursive adversarial evaluation be added as a validation tier?~~ Yes — added as Tier 4 with multi-model pipeline (-> spec:011).
- [x] ~~Should there be a sidecar API on MacStudio?~~ Superseded by the autonomous runtime (spec:014) + dashboard (spec:015). The runtime server + dashboard is a more complete solution than a sidecar — it includes task management, agent orchestration, adversarial review, and a web UI.
- [ ] How should Anti-Gravity's Agent Manager pattern inform our maestro orchestrator evolution?
