# 003: Validation Tiers

**Status:** draft

## Problem

No tiered testing strategy. Everything is either manual or a full-agent review. Need escalating levels of rigor — fast static checks for every commit, LLM judgment before PR, full adversarial review before merge.

## Approach

Define 3 tiers:

| Tier | What | When |
|------|------|------|
| 1 — Static | Lint, type check, schema validation, spec invariant check, visual screenshot verification | Every commit |
| 2 — LLM-as-judge | Quick model pass to evaluate quality, completeness | Before PR |
| 3 — Full agent | Spawn review agent, run E2E tests, spec alignment check | Before merge |
| 4 — Adversarial | Multi-model adversarial review: challenger generates tests + critique, author rebuts, arbiter decides. Models resolved dynamically at runtime (-> spec:011) | Before merge to main |

### Tier 1 includes visual verification for UI projects

Projects with a web frontend should include Playwright-based screenshot verification as a Tier 1 check. The UI agent template (`docs/template_agents/ui.md`) enforces a mandatory screenshot→read→verify→fix loop for every UI change. This catches layout regressions, clipped text, broken grids, and rendering bugs that code review alone misses — at zero LLM cost.

## Done When

- [ ] Tier definitions documented in this spec (above)
- [ ] `/review` skill (-> spec:004) uses Tier 1 checks (static) + Tier 2 (LLM-as-judge for quality)
- [ ] `/ship` skill (-> spec:005) references tiers in its test/review flow
- [ ] Vision spec (-> spec:000) mentions validation tiers as a platform capability
