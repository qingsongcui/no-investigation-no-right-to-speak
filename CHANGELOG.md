# Changelog

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
