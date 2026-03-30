# Anthropic Engineering — Harness Design for Long-Running Application Development

**Source:** https://www.anthropic.com/engineering/harness-design-long-running-apps
**Author:** Prithvi Rajasekaran (Anthropic Labs)
**Date:** March 24, 2026

## Why This Matters

This article validates the core architecture of Axiom. Anthropic's engineering team independently arrived at the same pattern: **generator-evaluator separation**, **deterministic harness controlling LLM sessions**, and **artifact-based handoffs between agents**. They frame it through GAN theory; we frame it through spec-driven development. Same destination, different paths.

Axiom's adversarial pipeline, runtime server, and worktree isolation were designed and implemented before this article was published — from first principles and conversations documented in [special-thanks.md](special-thanks.md).

---

## The Problem

Two persistent failure modes in long-running agentic systems:

1. **Context degradation**: Models lose coherence as context windows fill.
2. **Self-evaluation bias**: Agents reliably overpraise their own work.

> "Context resets — clearing the context window entirely and starting a fresh agent, combined with a structured handoff — addresses both these issues."

---

## Anthropic's Three-Agent System

| Role | What it does |
|------|-------------|
| **Planner** | Expands brief prompts into detailed product specs. High-level deliverables, not implementation details. |
| **Generator** | Implements features iteratively. Self-evaluates before handoff. Maintains version control. |
| **Evaluator** | Uses Playwright for interactive testing. Grades against criteria with hard thresholds. Negotiates "sprint contracts" pre-implementation. |

---

## Axiom's Pipeline (current)

Our pipeline evolved independently to a similar three-phase structure, with an additional mentor role:

```
Queue → Claim → Worktree → Plan → Build → Test → Adversarial Review → Gate
```

### Phase 1: Plan (Claude plans, GPT mentors)

The server puts Claude Code into **planning mode** — it generates a build plan for the spec item without writing any code. The plan covers: what files to create/modify, what tests to write, and how the Done When criteria will be met.

GPT then reviews the plan as a **mentor** (constructive, not adversarial): checks if the plan covers all acceptance criteria, flags missing steps, suggests additions. The mentor feedback is stored alongside the plan in PostgreSQL and fed into the execution prompt.

| Step | Model | Role |
|------|-------|------|
| Generate plan | Claude (Claude Code CLI in plan mode) | Architect |
| Review plan | GPT | Mentor — additive, not hostile |

### Phase 2: Build (Claude executes)

Claude Code receives the full spec, the approved plan, the mentor's feedback, and builds in an isolated git worktree. It has full agent capabilities — sub-agents, file creation, tool use — but works within the plan's scope. The server enforces termination: max turns, time limits, failure counts.

### Phase 3: Verify (pytest + Gemini challenges + GPT arbitrates)

Three-stage verification, each run by a different party:

| Step | Who | What |
|------|-----|------|
| **Tests** | pytest (deterministic) | Unit tests, file size checks, harness verification |
| **Adversarial review** | Gemini (Challenger) → Claude (Author rebuttal) → GPT (Arbiter) | Multi-round structured debate. Up to 3 rounds. Conceded issues are fixed; disputed issues escalate to arbitration. |
| **Quality gate** | Server (deterministic) | Tests pass AND adversarial verdict is PASS → result goes to human for final review |

The key constraint: **the model that writes the code never reviews it, and the model that reviews it never judges disputes about it.** Provider separation is enforced — not by convention, but by architecture.

### Phase 4: Human Review (Dashboard)

Results appear in the dashboard. The human approves, rejects, or requests changes. Approved results trigger merge and deploy. The human is trusted for judgment and intent — not for memory or process.

---

## Alignment

| Anthropic Concept | Axiom Implementation |
|---|---|
| Generator agent | Claude Code in isolated worktree |
| Evaluator agent | 3-model adversarial pipeline (Gemini → Claude → GPT) |
| Planner agent | Claude in plan mode + GPT mentor review |
| Sprint contracts | Spec "Done When" criteria + plan as contract |
| Context resets | Fresh session per task, server manages state in PostgreSQL |
| Artifact-based handoffs | Git commits in worktrees, plan + mentor feedback stored in DB |
| Criteria-driven steering | Spec content + plan + mentor feedback injected into agent prompt |
| Simplify over time | Band system: vision → foundation → MVP → versions |

The shared insight: **the harness is deterministic infrastructure; the LLM provides intelligence within that structure.** Neither Anthropic nor Axiom trusts the LLM to manage its own process.

---

## Key Differences

**What Anthropic does that we don't yet:**
- **Evaluator calibration loop** — tracking divergences between evaluator verdicts and human judgment to iteratively refine prompts. Our approve/reject buttons in the dashboard could feed this, but the loop isn't closed yet.
- **Playwright-based interactive testing** — their evaluator navigates running applications. We run pytest and Playwright functional tests (spec 029), but don't yet use Playwright as an adversarial evaluator tool.

**What Axiom does that Anthropic doesn't describe:**
- **Plan-then-execute with mentor review** — our planning phase is explicit: Claude plans, GPT mentors, then Claude builds with both plan and feedback as context.
- **Multi-model adversarial debate** — not just generator vs. evaluator, but a structured multi-round debate with escalation to a third-party arbiter.
- **Spec inference** — scanning existing codebases to propose specs, bridging "regular project" to "spec-driven project."
- **Autonomous multi-day runtime** — runs unattended for days, with Telegram notifications when builds complete.
