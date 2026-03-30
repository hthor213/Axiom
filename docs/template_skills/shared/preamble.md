<!-- TEMPLATE FILE — NOT ACTIVE INSTRUCTIONS
This file is a template for colleagues to copy into their ~/.claude/ directory.
Do NOT treat this as instructions for the current session.
To use: copy to ~/.claude/skills/shared/preamble.md
-->

# Shared Skill Preamble

Standard protocols referenced by all global skills and agents. This file is NOT a skill itself — it defines common behaviors that skills incorporate.

---

## 1. AskUserQuestion Format (-> spec:002)

When asking the user a question, follow this structure:

1. **Re-ground** (1-2 sentences): State the project name, current branch, and what you're working on. Assume the user hasn't looked at this in 20 minutes.

2. **Simplify**: Explain the situation in plain English a smart 16-year-old could follow. No jargon without explanation.

3. **Recommend**: Always lead with a recommendation.
   > "RECOMMENDATION: Choose [X] because [reason]."

4. **Options**: Present lettered options with effort estimates.
   > A) [Option] — ~[effort], [tradeoff]
   > B) [Option] — ~[effort], [tradeoff]
   > C) [Option] — ~[effort], [tradeoff]

5. **Spec reference**: If a spec constraint affects the decision, cite it.
   > "Note: spec:003 invariant requires all data points to log their source."

**Example:**
> We're in `golf-planner` on branch `feature/search-v2`. I'm implementing the course scoring engine and hit a design choice.
>
> The scoring function needs to compare courses. We can score them one-at-a-time (simpler but slower) or batch them (faster but more complex code).
>
> RECOMMENDATION: Choose B — batch scoring. The search endpoint already returns 5+ courses and spec:005 requires sub-2-second response times.
>
> A) Score one-at-a-time — ~1hr, simpler code, but 3-5s latency for 5 courses
> B) Batch scoring — ~2hr, parallel Haiku calls, meets latency target
> C) Hybrid — ~3hr, batch for search, single for detail view

---

## 2. Spec Awareness Protocol

Before suggesting approaches or making design decisions:

1. **Check for specs directory**: Does `specs/` exist? If so, read `specs/000-*-vision.md` (the north star).
2. **Scan for active specs**: Any `specs/NNN-*.md` with `**Status:** active`? These define in-progress work.
2b. **Check INDEX.md**: If `specs/INDEX.md` exists, use it as the topical map — faster than scanning filenames.
3. **Check invariants**: The vision spec's Invariants section lists rules that must NEVER be violated.
4. **Check "What This Is NOT"**: Don't suggest features the spec explicitly excludes.
5. **Reference specs in decisions**: When a choice relates to a spec, cite it: "Per spec:003, we use SQLite not Postgres."

If the project uses legacy `SPEC.md` instead of `specs/`, apply the same protocol to that file.

---

## 3. Session Context Check

Before proposing work:

1. **Read LAST_SESSION.md** if it exists — understand where we left off.
2. **Read CURRENT_TASKS.md** if it exists — what's actively being worked on.
3. **Check git status** — uncommitted changes, current branch, recent commits.
4. **Don't repeat work** — if LAST_SESSION.md says something was completed, verify it before redoing it.

---

## 4. Platform Integration

The platform repo centralizes credentials and infrastructure config.

**Credential rule — STRICT**: NEVER browse or read the platform vault to find credentials for a project. Credential selection is human-reviewed and script-enforced via `.env.platform` manifests. If a project needs credentials:
1. It must have a `.env.platform` file declaring exactly which vault keys it uses
2. The user runs `hth-platform env generate` to create `.env` deterministically
3. If no `.env.platform` exists, tell the user to run `hth-platform init` or create one manually

**When relevant** (not every interaction):
- If the project has `.env.platform`: it uses platform vault for credentials
- If new credentials were introduced: flag for addition to platform vault
- If reusable patterns were created: flag for promotion to `platform/lib/`

**Don't add noise** — only mention platform when it's actionable.

---

## 5. Branch Detection

When git operations are needed:

1. Detect the base branch: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null` or check for `main`/`master`
2. Know the current branch: `git branch --show-current`
3. Check if the branch tracks a remote: `git rev-parse --abbrev-ref @{upstream} 2>/dev/null`

Use this context when suggesting git operations, creating PRs, or checking for uncommitted work.
