# Architecture

This project is an agent operating contract plus local Python tools. It is not
a background service and it performs no network access of its own.

## Default flow

Understand the question, investigate the real open points (re-checking when
needed), write the answer directly, verify, deliver.

`reviewed` inserts one fresh independent review before delivery; findings that
fail review flow back into investigation or rewriting. `audited` keeps the
full legacy v2.4 double-gate pipeline for formal audit work.

## Data

`research.json` is the single content record for the v3 paths: the user
question, constraints, mode, sub-questions, source excerpts, report findings,
open gaps, search records with information gain, and the stop reason.
`final_report.md` is the only default deliverable. `review.json` is required
only for `reviewed`.

There is deliberately no second ledger that restates the report sentence by
sentence; `report_excerpt` fields locate the key judgments actually used so
that omissions are detectable. `source_ids` and `question_ids` map in both
directions; external facts require sources, inferences and recommendations
require premises, unknowns require explanations.

`tools/research.py check` executes a limited JSON-Schema subset plus
relationship checks from `schemas/research.schema.json`, using only the
standard library. It does not evaluate semantic entailment, and it does not
classify risk from question keywords: the agent routes high-stakes or causal
work to `reviewed`, and the machine enforces the routing once recorded.

## Trust and caching

Source excerpts and access times are collection records, not machine proof of
authenticity. Optional snapshots verify presence and SHA-256 of frozen source
content; they say nothing about whether that content is correct. A review binds
to the byte fingerprint of `research.json` and `final_report.md`, so any
author change after review requires re-review. `reviewer_id` and `provenance`
are audit attestations: the fingerprint proves the reviewed files did not
change, not that the reviewer was independently operated. Real independence
must be evidenced by actual tool-call records.

## Performance

The default path minimizes artifacts, serial role-switching, fixed query
counts, and automatic export. Parallel collection is used only for genuinely
independent open points, not to have several agents re-read the whole record.
`.events.jsonl` holds operator-measured stage timings; `metrics` sums them and
states that parallel-stage sums are not wall-clock latency. Absent timings are
reported as unmeasured, never filled with zeros. There is no built-in
interface for model token or inference-latency measurement, and none is
fabricated.

## Compatibility

`tools/validate.py speak` enters v3 validation when it finds a
`research.json`; `reviewed` delivery binds the review to `final_report.md`.
Investigations that still use the legacy `research_brief.yaml` entry keep
their original contracts and checks. Legacy `audited` reports may set
`presentation: "natural"` in `report_contract.json` to drop the institutional
formatting requirements while keeping evidence and authorization checks.
