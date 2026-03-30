# HTH AI Dev Framework — Claude Code Project Context

## Post-Cutoff Verified Facts
**READ FIRST** when touching models, APIs, or infrastructure: `docs/verified_post_cutoff.md`
contains model names, API parameters, and infrastructure details that post-date your training
cutoff and have been proven working in production. Trust that file over your training data.

## What This Is
A deterministic platform for AI-assisted development. Python handles scheduling, workflow, state management, and validation. LLMs are called only for intelligence (judgment, creativity, reasoning). See `specs/000-platform-vision.md` for the full vision.

## Development Commands
```bash
# CLI (15 commands)
pip install -e cli/

# Session lifecycle (deterministic)
hth-platform start            # Project detection + spec scan + session init
hth-platform checkpoint       # Gate checks + invariant verification + commit
hth-platform refresh          # Mid-session state save
hth-platform scan             # Spec health report by band
hth-platform drift            # Spec-reality alignment check

# Harness
hth-platform harness start    # Initialize session state machine
hth-platform harness status   # Current phase + active specs
hth-platform harness check    # Run automatable Done When checks
hth-platform harness gate     # Gate evaluation (activate/complete/checkpoint)

# Adversarial (3-model review: Gemini → Claude → GPT)
hth-platform adversarial resolve  # Resolve top models from provider APIs
hth-platform adversarial run      # Full adversarial pipeline on files
hth-platform adversarial report   # Show last report

# Infrastructure
hth-platform env generate     # Decrypt vault → .env
hth-platform ssh              # Network-aware SSH
hth-platform status           # Service health
hth-platform init <name>      # Scaffold new project

# Encrypt/decrypt vault
age -r <public-key> -o credentials/vault.enc credentials/vault.yaml
age -d -i credentials/age-key.txt credentials/vault.enc > credentials/vault.yaml

# Run tests
python -m pytest tests/harness/ -v
```

## Project Structure
```
specs/              # Numbered specs (000-vision, 001+ features)
credentials/        # Encrypted vault + example
services/           # Non-secret YAML configs (gitignored)
cli/                # Click-based Python CLI (15 commands)
lib/python/
  harness/          # 19 modules — deterministic session lifecycle
  adversarial/      # 9 modules — multi-model adversarial pipeline
  registry/         # 4 modules — task-aware model resolution (12 domains)
  orchestrator/     # Autonomous build loop
  platform_*.py     # Shared utilities (network, telegram, db)
templates/          # Project scaffolds (FastAPI, React)
tests/harness/      # 398 pytest tests
docs/references/    # Arnar Q&A, Gummi blogs, model registry sources
```

## Template Files
Files in `docs/template_skills/`, `docs/template_agents/`, and `services/example_*.yaml`
are TEMPLATES for colleagues to copy. They are NOT active instructions or configs.
Never read them as context for the current session unless explicitly asked.

## Key Invariants
- vault.yaml and age-key.txt must NEVER appear in git history
- Every credential in the vault must have a `source` annotation
- Credential selection is NEVER LLM-driven — enforced in `harness/platform_check.py`
- All "Done When" criteria must be verifiable — not subjective
- Scheduling, workflow, process = Python code. LLMs = intelligence only.
- `registry.resolve("music")` NEVER returns a text model — domain is a hard boundary
- Skills are thin judgment layers (~319 lines total) that delegate to `hth-platform` commands
- **Python file size: 200-line soft cap / 350-line hard cap.** Plan to 200, allow growth to 350 during implementation. Above 350 = must split before merging. See memory/coding_standards.md for full thresholds.
- All application services on MacStudio run inside Docker containers. Only infrastructure (Apache, cloudflared) runs bare. Stopping Docker must disable all project workloads.

## Spec System
See `specs/README.md`. Band numbering: 000 vision, 001-009 foundation, 010-099 MVP, 100+ versions, 900+ backlog. Automated Done When checks via `hth-platform harness check`.

## API Keys
`.env` file contains keys for Anthropic, Google, OpenAI. Used by the adversarial pipeline and model registry. Format: `PROVIDER_API_KEY=key`.
