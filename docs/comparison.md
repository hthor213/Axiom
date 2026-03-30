# Ecosystem Comparison — Axiom vs. the Field

Last updated: 2026-03-29

---

## 1. What Axiom Does

Axiom is a spec-driven AI development framework built for Claude Code. It provides:

- **Spec system** — 30 numbered specs (bands 000-999) with "Done When" criteria written first. Verified via `/checkpoint`. Band numbering makes maturity visible at a glance.
- **Multi-model adversarial pipeline** — Claude writes code, Gemini challenges it, GPT arbitrates disputes. No single model does everything. Separation of concerns across providers prevents collusion.
- **Autonomous runtime** — PostgreSQL-backed task queue with 7-step pipeline (enqueue, claim, worktree, agent, diff, adversarial, gate). Runs unattended for days on a dedicated server.
- **Dashboard** — Web control plane for the human. Select specs, click "Run," review results, approve/reject, merge & deploy. Telegram notifications when builds complete.
- **Session lifecycle** — Cold start (`/start`), mid-session save (`/refresh`), end-of-session sync (`/checkpoint`). Continuity via `LAST_SESSION.md` and `CURRENT_TASKS.md`.
- **Spec inference** — Scan any existing codebase and propose specs from code. Bridges the gap between "regular project" and "spec-driven project."
- **CLI** — `hth-platform` with 15 commands: session lifecycle, harness operations, adversarial review, and infrastructure.
- **Credential vault** — age-encrypted YAML store with human-reviewed selection and provenance annotations.
- **22,000+ lines of Python.** 400+ tests. Scheduling, workflow, and validation are deterministic code. LLMs are called only for intelligence.

---

## 2. Competitor Profiles

### Everything Claude Code (ECC)

- **URL:** github.com/affaan-m/everything-claude-code
- **Stars:** 110k
- **What it does well:** 28 specialist agents, 119 skills, 60 commands. AgentShield with 102 security rules (OWASP Top 10). 1,282 tests at 98% coverage. Cross-tool support (Claude Code, Cursor, Codex, OpenCode). Born at the Feb 2026 Anthropic/Cerebral Valley hackathon.
- **What it doesn't do:** No spec system with numbered bands, no credential vault, no session lifecycle, no autonomous runtime pipeline, no multi-model adversarial review.

### SuperClaude Framework

- **URL:** github.com/SuperClaude-Org/SuperClaude_Framework
- **Stars:** 22.0k
- **What it does well:** 30 slash commands, 16 agent personas, 7 behavioral modes, 8 MCP integrations. Session state via `PLANNING.md` / `TASK.md` / `KNOWLEDGE.md`. SuperGemini sister project.
- **What it doesn't do:** No spec system, no credential vault, no deployment automation, no autonomous runtime.

### ccpm (Claude Code Project Manager)

- **URL:** github.com/automazeio/ccpm
- **Stars:** 7.8k
- **What it does well:** GitHub Issues-based project management with worktree-parallel agent execution. Deterministic bash scripts (no LLM cost). PRD-to-production traceability. Works across Claude Code, Cursor, Codex, OpenCode.
- **What it doesn't do:** No spec system, no credential vault, no adversarial review, no session lifecycle.

### claude-code-spec-workflow

- **URL:** github.com/Pimzino/claude-code-spec-workflow
- **Stars:** 3.6k
- **What it does well:** 4-phase workflow with steering docs (`product.md`, `tech.md`, `structure.md`). MCP server variant with web dashboard. Session-based caching.
- **What it doesn't do:** No session lifecycle, no orchestration, no autonomous runtime.

### cc-sdd

- **URL:** github.com/gotalab/cc-sdd
- **Stars:** 3.0k
- **What it does well:** Kiro-style Requirements/Design/Tasks workflow with EARS notation for acceptance criteria. Portable across 8 AI tools and 13 languages.
- **What it doesn't do:** No session lifecycle, no credential management, no autonomous runtime.

### Trail of Bits config

- **URL:** github.com/trailofbits/claude-code-config
- **Stars:** 1.7k
- **What it does well:** Security-first `CLAUDE.md`, seatbelt sandboxing, deny rules. Anti-rationalization stop hooks. Devcontainer for sandboxed bypass-mode execution.
- **What it doesn't do:** No session management, no spec system, no autonomous runtime.

### claudekit

- **URL:** github.com/carlrannaberg/claudekit
- **Stars:** 637
- **What it does well:** Git checkpointing, 6-agent parallel review, hook profiling, thinking-level injection. 20+ domain subagents.
- **What it doesn't do:** No formal spec system, no credential vault, no autonomous runtime.

### Claude Code Harness

- **URL:** github.com/Chachamaru127/claude-code-harness
- **Stars:** 327
- **What it does well:** v3 unifies 42 skills into 5 verb skills. TypeScript guardrail engine with 13 declarative rules, compiled and type-checked.
- **What it doesn't do:** No spec system with bands, no credential vault, no autonomous runtime.

### Kiro (Amazon)

- **URL:** kiro.dev
- **What it does well:** Most rigorous external spec system. EARS notation. Agent Hooks and Agent Steering. AWS observability (alarms, distributed tracing, SLO monitoring). Free tier and $19/month Pro.
- **What it doesn't do:** IDE-locked, no CLI support, AWS-native only.

### agent-secrets

- **URL:** github.com/joelhooks/agent-secrets
- **Stars:** 67
- **What it does well:** age-encrypted credential store (same encryption primitive as Axiom). Lease TTLs, killswitch, heartbeat monitoring.
- **What it doesn't do:** No development workflow — credential management only.

---

## 3. Feature Matrix

### Spec System

| Feature | Axiom | ECC | SuperClaude | ccpm | Spec Workflow | cc-sdd | Harness | claudekit | Trail of Bits | agent-secrets | Kiro |
|---------|-------|-----|-------------|------|---------------|--------|---------|-----------|---------------|---------------|------|
| Numbered/organized specs | Bands (000-999) | No | No | PRD/Epic/Task | Flat (4 phases) | Flat (req/design/tasks) | Plans.md | Spec workflow | No | No | Flat (3 docs) |
| "Done When" first | Yes | Success criteria | No | No | No | EARS criteria | Success criteria | No | No | No | EARS criteria |
| Spec size constraint | 60 lines | No | No | No | No | No | No | No | No | No | No |
| Spec verification | /checkpoint | 1,282 tests | No | No | No | No | Evidence pipeline | No | No | No | Auto test gen |
| Spec inference from code | Yes | No | No | No | No | No | No | No | No | No | No |

### Multi-Model Adversarial Review

| Feature | Axiom | ECC | SuperClaude | ccpm | Others |
|---------|-------|-----|-------------|------|--------|
| Multi-model review | 3 providers (Claude/Gemini/GPT) | AgentShield (1 model) | No | No | No |
| Structured debate | Up to 3 rounds | No | No | No | No |
| Dispute arbitration | Third-party model | No | No | No | No |
| Provider separation | Enforced (writer ≠ reviewer ≠ judge) | No | No | No | No |

### Session Management

| Feature | Axiom | ECC | SuperClaude | ccpm | Spec Workflow | cc-sdd | Harness | claudekit | Trail of Bits | Kiro |
|---------|-------|-----|-------------|------|---------------|--------|---------|-----------|---------------|------|
| Cold start awareness | /start | No | Auto-load 3 files | No | No | No | Setup verb | No | No | IDE startup |
| End-of-session sync | /checkpoint | No | No | No | No | No | Release verb | No | No | No |
| Mid-session save | /refresh | No | No | No | No | No | No | Git stash | No | No |
| Session continuity files | LAST_SESSION + CURRENT_TASKS | No | PLANNING + TASK | No | No | No | No | No | No | No |
| Session hygiene crons | 3 crons | No | No | No | No | No | No | No | No | No |

### Autonomous Runtime

| Feature | Axiom | ECC | ccpm | Spec Workflow | Others |
|---------|-------|-----|------|---------------|--------|
| Task queue | PostgreSQL-backed | No | GitHub Issues | No | No |
| Pipeline steps | 7-step chain | No | PRD/Epic/Task | No | No |
| Worktree isolation | Git worktrees per task | No | Git worktrees per task | No | No |
| Dashboard UI | Web control plane | No | GitHub Issues UI | MCP dashboard | No |
| Adversarial gate | 3-model gate before merge | AgentShield | No | No | No |
| Runs unattended | Days at a time | No | No | No | No |

### Credentials

| Feature | Axiom | agent-secrets | Others |
|---------|-------|---------------|--------|
| Encrypted vault | age-encrypted YAML | age-encrypted | No |
| Human-reviewed selection | .env.platform manifests | No | No |
| Provenance annotations | source + used_by | No | No |
| Lease TTLs | No (adopt candidate) | Yes | No |

---

## 4. What Axiom Deliberately Excludes (and Why)

| Feature | Why Not |
|---------|---------|
| Multi-tool portability | Claude Code's native tools (CronCreate, Agent, worktrees) are our advantage. Supporting 8 tools means lowest-common-denominator features. |
| 100+ skills/agents | Quality over quantity. Each skill is spec-aware and session-continuous. ECC's 119 skills serve breadth across teams; we serve depth for one. |
| Personas/role presets | A single developer doesn't need a "CEO reviewer" persona. Domain expertise lives in specs, not roleplay. |
| IDE integration | CLI-first is intentional. IDE lock-in limits workflow flexibility. |
| Cloud-based secrets | age over Vault/1Password: no daemon, no cloud dependency, works offline. |
| LLM credential selection | Safety invariant. Human-reviewed selection prevents credential leakage. |

---

## 5. Sources

- github.com/affaan-m/everything-claude-code
- github.com/SuperClaude-Org/SuperClaude_Framework
- github.com/automazeio/ccpm
- github.com/Pimzino/claude-code-spec-workflow
- github.com/gotalab/cc-sdd
- github.com/trailofbits/claude-code-config
- github.com/carlrannaberg/claudekit
- github.com/Chachamaru127/claude-code-harness
- github.com/joelhooks/agent-secrets
- kiro.dev
- humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents
- addyosmani.com/blog/good-spec/
- blog.gitguardian.com/claude-code-security-why-the-real-risk-lies-beyond-code/
