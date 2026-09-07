# Evidence-First Research

[![verify](https://github.com/qingsongcui/evidence-first-research/actions/workflows/verify.yml/badge.svg)](https://github.com/qingsongcui/evidence-first-research/actions/workflows/verify.yml)

Evidence-first research workflow and validation toolkit for AI agents.

This repository gives an AI agent a disciplined way to answer questions with
tracked sources, explicit uncertainty, and — for high-stakes or causal claims —
one fresh independent review. The Python tools validate structure and
provenance only. A PASS never means the answer is true; it means the citations
resolve, the findings map to the report, and (in `reviewed` mode) the review
still matches the reviewed files.

## Three paths

| Mode | Use for | Required files | Review |
|---|---|---|---|
| `answer` | General facts, explanations, comparisons | `research.json`, `final_report.md` | Author self-check |
| `reviewed` | High-stakes decisions, causal conclusions, serious source conflicts | Above plus `review.json` | One fresh, independent review |
| `audited` | Formal evidence audit, or continuing an old v2.4 investigation | Legacy v2.4 contracts (see `skills/deep-research/SKILL.md`) | Two independent gates |

Normal questions stay on `answer`. `audited` is a more demanding optional
compatibility path, not the recommended default. High-stakes or causal work
must not be downgraded to `answer`: the validator rejects it.

## Five-minute verification

```text
python3 -m unittest discover -s tests -p 'test*.py'
python3 tools/research.py check examples/agent-skill-installation-reviewed
python3 tools/validate.py speak examples/agent-skill-installation-reviewed
```

All three must exit `0`. The second command checks the shipped `reviewed`
demonstration (source kinds, heading-level locators, SHA-256-verified source
snapshot, live review binding). The third runs the same directory through the
`speak` entry point, which dispatches to the v3 validator when it finds a
`research.json`.

## Limitations

1. This toolkit does not browse by itself. Searching and reading sources is
   done by the operating agent with whatever tools its runtime provides.
2. It does not certify source truth or semantic entailment. It checks that
   cited sources were recorded, that snapshots match, and that findings map to
   report text — not that the sources are correct or that they truly imply the
   conclusions.
3. It does not cryptographically prove reviewer independence. The
   `input_fingerprint` in `review.json` proves the reviewed files did not
   change after review; `reviewer_id` and `provenance` are attestations, and
   real independence must be backed by actual tool-call records.
4. It does not guarantee resistance to model-level prompt injection. External
   material is treated as untrusted data (see `docs/security.md`), but tagging
   is a bookkeeping boundary, not a security proof.

## Layout

- `tools/` — validators and helpers (`research.py` for the v3 workflow,
  `validate.py` for the legacy audited path and `speak` dispatch).
- `schemas/` — JSON contracts for research records and reviews.
- `templates/` — starter records for new investigations.
- `skills/deep-research/` — the agent workflow: when to use each path, how to
  record evidence, how to request independent review.
- `examples/agent-skill-installation-reviewed/` — the only shipped
  demonstration; see `examples/README.md`.
- `tests/` — behavior regression suite plus synthetic audited-path fixtures.
- `docs/` — architecture, security model, and evaluation method.
