# Changelog

## 0.2.0 — Critical probes and interest-relationship investigation (2026-11-23)

Ports the v3.1/v3.2 method additions from the internal Chinese line into the
public toolkit. Adds bilingual documentation (English primary, Simplified
Chinese switchable).

- Critical probes: new live `reviewed` runs and `--deep` explanations record an
  up-front probe in `research.json` — tentative judgment, strongest competing
  explanation, and the observation that separates them — bound to real evidence
  and the final judgment. `research.py next` surfaces unfinished probes and
  fillable gaps before drafting.
- `research.py`: add `needs_probe` / `next_steps` / `validate_probes` and the
  `--deep` flag; `next` reads the next step from probes and gaps.
- `validate.py`: natural presentation mode skips the legacy Sources/References
  format checks while keeping citation and provenance checks.
- Interest-relationship investigation: when an answer turns on who pays,
  executes, or bears the consequences, follow one concrete order, shift, or
  dispute — tracking internal divergence, absent parties, and stage changes.
- Bilingual docs: `README.zh-CN.md` and `AGENTS.zh-CN.md` with cross-links;
  English remains primary.
- Tests: 74/74 OK.

## 0.1.0 — Public release (2026-09-07)

First public release of the evidence-first research workflow and validation
toolkit for AI agents.

- Three-path workflow: `answer` for general questions, `reviewed` for
  high-stakes or causal conclusions with one fresh independent review, and
  `audited` as a compatibility path for formal evidence audit.
- Reviewed-mode evidence contract: every source behind a `fact` or `causal`
  finding carries `source_kind`, an `evidence_locator`, and a SHA-256-verified
  in-investigation snapshot.
- Reviewer identity and provenance recorded as attestations; the input
  fingerprint proves reviewed files did not change after review, not that the
  reviewer was independently operated.
- One shipped demonstration: `examples/agent-skill-installation-reviewed`.
- Executable release gates: unit tests plus a `verify.yml` matrix (Python 3.9
  and 3.12, no third-party packages).
