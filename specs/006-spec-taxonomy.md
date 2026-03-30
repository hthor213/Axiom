# 006: Spec Taxonomy

**Status:** draft

## Problem

The numbered spec system uses simple sequential numbering. As projects grow past ~10 specs, there's no convention for organizing by maturity (foundation vs MVP vs ideas) or by subsystem. The Golf Trip Planner evolved ad-hoc bands; this formalizes the pattern.

## Approach

Band-based numbering with documented conventions:
- 000 vision, 001-009 foundation, 010-099 MVP, 100+ version bands, 900+ backlog
- Optional subsystem bands (X00=vision, X01-X09=implementation)
- INDEX.md as topical card catalog (topic -> spec numbers across bands)
- 900-series promotion rules (assign real number, old file becomes redirect)
- Skills updated: /start reads INDEX.md, /checkpoint maintains it

## Done When

- [x] specs/README.md documents band numbering, subsystem pattern, and 900-series rules
- [x] specs/INDEX.md exists with topical groupings for all current specs
- [x] /start skill reads INDEX.md and reports specs organized by band
- [x] /checkpoint skill updates INDEX.md when spec status changes
- [x] Preamble's Spec Awareness Protocol mentions INDEX.md
- [x] Vision spec (000) references the taxonomy
