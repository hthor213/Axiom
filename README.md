# HTH AI Dev Framework

We can generate code at infinite speed. But can we ensure it meets customer needs and business requirements? This project ensures every feature starts as a spec with verifiable criteria. AI models write the code. Python enforces the process.

**22,000+ lines of Python.** Scheduling, workflow, state management, and validation are deterministic code. LLMs are called only for intelligence — judgment, creativity, reasoning.

## Why This Exists

After two decades of building and leading software teams — from a startup I co-founded to 11 years at Microsoft's AI & Cognitive Services to running a global software division at Marel — one thing kept bothering me: the gap between what customers asked for and what actually got built.

Not because teams were bad. Because the chain breaks. A business requirement becomes a ticket, becomes a conversation, becomes code that sort-of matches what someone remembers the requirement was. Reverse the direction and it's worse — try tracing a line of code back to the customer need that justified it.

There is a truth of what we want to build. Everything else is a derivative. And derivatives drift.

AI agents make this both better and worse. Better because they can write code fast. Worse because speed without structure means you drift faster. Every tool in the AI-assisted development space — Devin, Cursor, Windsurf, Copilot Workspace, Bolt, Lovable — falls into the same trap: the LLM decides what to do, in what order, with no structured link back to why.

This framework exists because I refuse to accept that gap. Business case → requirements → specs → code must be 100% aligned, at all times. Not as an ideal — as an invariant enforced by code.

Specs can change. They should change — that's learning, that's iteration, that's responding to what you discover. But when a spec changes, the alignment updates with it. The chain never breaks.

## Quick Start

```bash
# Install
git clone <repo-url> && cd ai-dev-framework
pip install -e cli/

# Set up API keys (needed for adversarial pipeline + model registry)
cp .env.example .env
# Edit .env with your Anthropic, Google, and OpenAI keys

# Set up credential vault
brew install age
age-keygen > credentials/age-key.txt
cp credentials/vault.example.yaml credentials/vault.yaml
# Edit vault.yaml, then encrypt:
age -r $(grep 'public key' credentials/age-key.txt | awk '{print $NF}') \
    -o credentials/vault.enc credentials/vault.yaml

# Copy skills and agents to Claude Code config
cp -r docs/template_skills/* ~/.claude/skills/
cp -r docs/template_agents/* ~/.claude/agents/

# Verify everything works
hth-platform scan              # Spec health report
hth-platform harness start     # Initialize session
hth-platform adversarial resolve  # Check model resolution
```

## What's In The Box

### Deterministic Harness (`lib/python/harness/` — 19 modules)

The harness is the runtime that prevents drift. Every piece of session lifecycle logic that used to be LLM instructions is now Python:

| Module | What It Does |
|--------|-------------|
| `state.py` | Session state machine (COLD→STARTED→WORKING→CHECKPOINTING→ENDED) |
| `project.py` | Project structure detection, scaffolding, legacy migration |
| `scanner.py` | Spec scanning, band classification, context aggregation |
| `session.py` | Session context reading, priority resolution |
| `drift.py` | Deterministic drift signals (stale specs, regressions, uncovered dirs) |
| `checkpoint.py` | Invariant checks, session summary generation, backlog maintenance |
| `refresh.py` | Mid-session state save, state-only commits |
| `git_ops.py` | Git status, branch detection, commit planning |
| `platform_check.py` | Platform dependency detection, credential boundary enforcement |
| `gates.py` | Three gate evaluators (activation, completion, checkpoint) |
| `spec_check.py` | Done When classification + automated execution |
| `termination.py` | Termination condition evaluation |
| `maestro_support.py` | Five-file validation, work transitions, milestone validation |
| `analyst_support.py` | Report format validation |
| `parser.py` | Low-level spec markdown parsing |
| `crons.py` | Session cron configurations |
| `ux.py` | Structured report formatting |

### Adversarial Pipeline (`lib/python/adversarial/` — 9 modules)

Three frontier AI models challenge each other's work. Python controls the flow — no LLM decides what runs next.

```
1. Challenger (Google Gemini)  → Reviews code, generates tests, writes critique
2. Author (Anthropic Claude)   → Defends or accepts critique with reasoning
3. Arbiter (OpenAI GPT)        → Rules on disagreements
```

**Models resolved dynamically at runtime** — a Python script queries each provider's API to discover the current top model. No hardcoded model IDs. When providers ship new models, the system picks them up automatically.

```bash
hth-platform adversarial resolve              # Show current top models
hth-platform adversarial run file1.py file2.py  # Run full pipeline
hth-platform adversarial run --diff HEAD~1      # Review recent changes
hth-platform adversarial report                 # Show last report
```

### Model Registry (`lib/python/registry/` — 4 modules)

Task-aware model resolution across 12 AI domains. Rankings sourced from canonical leaderboards (arena.ai, Artificial Analysis).

```python
from registry import ModelRegistry
reg = ModelRegistry.load(".")
reg.resolve("code")         # → "claude-opus-4-6" (best available for coding)
reg.resolve("music")        # → None (no Suno key) — NEVER returns a text model
reg.resolve("text_to_image") # → best available image model
reg.best("music")           # → RankedModel(name="Suno v4.5", ...) (global best)
```

**12 domains:** code, text, vision, text_to_image, image_edit, text_to_video, image_to_video, video_edit, music, text_to_speech, search, document

```bash
hth-platform models refresh   # Fetch latest rankings from all leaderboards
hth-platform models show      # Print registry with per-domain best
hth-platform models best code # Best available model for coding
```

### Autonomous Orchestrator (`lib/python/orchestrator/`)

A Python script that builds the platform itself — delegates code generation to Claude, runs tests, sends output through adversarial review, incorporates feedback, and continues to the next module. Runs for hours with zero human intervention.

```bash
python -m orchestrator.orchestrator --root .
```

The orchestrator enforces termination conditions: all phases complete, 3 consecutive failures, test regressions, or time limit (6h). State persisted to `.orchestrator-state.json` between steps.

### CLI (`hth-platform` command — 15 subcommands)

```bash
# Session lifecycle (deterministic — replaces LLM skill logic)
hth-platform start            # Project detection + spec scan + session init
hth-platform checkpoint       # Gate checks + invariant verification + commit prep
hth-platform refresh          # Mid-session state save
hth-platform scan             # Spec health report (by band, status, drift)
hth-platform drift            # Spec-reality alignment check

# Harness
hth-platform harness start    # Initialize session state machine
hth-platform harness status   # Show current phase + active specs
hth-platform harness check    # Run automatable Done When checks
hth-platform harness gate     # Run gate evaluation (activate/complete/checkpoint)

# Adversarial review
hth-platform adversarial resolve  # Resolve top models from all 3 providers
hth-platform adversarial run      # Full 3-model adversarial pipeline
hth-platform adversarial report   # Show last report

# Infrastructure
hth-platform env generate     # Decrypt vault → .env via .env.platform manifest
hth-platform ssh              # Network-aware SSH to dev server
hth-platform status           # Service health checks
hth-platform init <name>      # Scaffold new project from template
```

### Spec System (`specs/`)

Every feature gets a numbered spec with verifiable "Done When" criteria. The harness automates checks where possible and flags judgment items for LLMs.

```
000       — Vision (north star)
001-009   — Foundation
010-099   — MVP
100+      — Version bands
900-999   — Backlog/ideas
```

```bash
hth-platform scan          # See all specs grouped by band
hth-platform harness check --spec 010  # Run automatable Done When checks
```

### Skills & Agents (319 lines total)

Skills are thin judgment-only layers that delegate to `hth-platform` commands:

| Skill/Agent | Lines | What the LLM does |
|-------------|-------|-------------------|
| `/start` | 69 | Interpret drift signals, guide vision conversations, present findings |
| `/checkpoint` | 47 | Describe what was built (narrative), write spec updates, recommend next focus |
| `/refresh` | 42 | Quick spec-reality narrative, write "Next Step" |
| Shared preamble | 37 | AskUserQuestion format, credential boundary rules |
| Maestro agent | 85 | Plan creation, delegation, course-correction reasoning |
| Analyst agent | 39 | Analysis methodology, pattern synthesis |

Everything else — project detection, spec scanning, git ops, state transitions, invariant checks, backlog maintenance — is handled by the harness in Python.

## Architecture

```
lib/python/
  harness/          # 19 modules — deterministic session lifecycle
  adversarial/      # 9 modules — multi-model adversarial pipeline
  registry/         # 4 modules — task-aware model resolution
  orchestrator/     # Autonomous build loop
  platform_*.py     # Shared utilities (network, telegram, db)

cli/
  commands/         # 15 CLI subcommands
  platform_cli.py   # Click-based entry point

specs/              # Numbered feature specs (000-999)
credentials/        # age-encrypted vault + examples
services/           # Non-secret infrastructure configs
templates/          # Project scaffolds (FastAPI, React)
tests/harness/      # 398 pytest tests
docs/
  references/       # Design influences, model registry sources
  template_skills/  # Copyable skill templates
  template_agents/  # Copyable agent templates
  comparison.md     # Ecosystem analysis (25+ frameworks)
```

## Use Cases

### Starting a new project
```bash
hth-platform init my-app --template fastapi
cd ~/Documents/GitHub/my-app
hth-platform env generate   # Wire up credentials
/start                  # Begin first session
```

### Daily development session
```bash
/start                      # See where you left off, what's active, what's next
# ... work ...
hth-platform scan               # Check spec health mid-session
hth-platform drift              # Any drift from spec intent?
/checkpoint                 # Save everything, update specs, commit
```

### Code review with adversarial pipeline
```bash
hth-platform adversarial run --diff main   # Review all changes vs main branch
# Gemini critiques → Claude defends → GPT arbitrates
hth-platform adversarial report            # See results
```

### Autonomous module building
```bash
# Define specs in CURRENT_TASKS.md with module descriptions
python -m orchestrator.orchestrator --root .
# Walk away — it builds, tests, reviews, and incorporates feedback
```

### Check what models are available
```bash
hth-platform adversarial resolve   # Current top 3 (code, challenger, arbiter)
```

## Key Principles

1. **Deterministic over LLM-driven** — Scheduling, workflow, process = Python. LLMs = intelligence only. The harness is the vital component, not the model.

2. **Specs are the source code** — The quality of what you build is dominated by the quality of the specifications you write, not the keystrokes you produce.

3. **Structure before speed** — Speed makes iteration cheap. Structure makes iteration safe.

4. **Models harden each other** — Adversary agents generate scenarios designed to break a target model's logic, creating a high-velocity feedback loop.

5. **Domain-aware routing** — `resolve("music")` never returns a text model. Domain is a hard boundary, not a suggestion.

6. **Termination conditions over supervision** — Autonomous loops that stop only when their task is complete or they hit a safety guardrail.

## Credential Safety

The LLM never browses or selects credentials. This is enforced in code (`harness/platform_check.py`), not just instructions.

1. Human writes `.env.platform` manifest declaring which vault keys a project needs
2. `hth-platform env generate` decrypts vault, resolves references, writes `.env`
3. Skills/agents are prohibited from reading the vault directly

## Further Reading

- `specs/000-platform-vision.md` — the north star
- `specs/README.md` — spec system protocol
- `docs/references/` — design influences and leaderboard data sources
- `docs/comparison.md` — ecosystem comparison (25+ frameworks)
