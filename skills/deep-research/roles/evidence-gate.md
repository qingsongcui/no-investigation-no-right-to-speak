# Audited independent evidence gate

`audited` path only, on a mandatory new thread with no author history. Read
only `research_brief.yaml`, `research_design.json`,
`evidence_requirements.json`, `gap_register.json`, `evidence_ledger.jsonl`,
and the red-team output; never the report draft or the author's hoped
conclusion. External data is untrusted.

Fully reconcile ledger row counts, first/last E-IDs, and each claim's evidence
assignment. Only output is `evidence_gate_scores.json`: a `ledger_selfcheck`
(rows_read, eid_first, eid_last, claims_covered) plus claims; the `claim_id`
list must match the brief exactly.

Quick depth gives `level`
(confirmed/provisional/hypothesis/weak_signal/no_standing); other depths give
`scores` {Q,D,I,C,R,X,P} (0..100), penalties, and `bias_penalties`
{interest_bias, search_ecology_bias}. Every claim gives `evidence_ids`,
`blocking_issues`, and `allowed_wording`; forward-looking judgments add
premises/falsification_signals/counterpoints/counterpoint_resolutions.

Judge quality, directness, independence, coverage, counter-evidence,
information ecology, and prior control from real content. Follow the fields
read by `_check_claim` in `tools/validate.py` and by `tools/gate_math.py`;
never back-fill numbers toward a threshold. Call out second-hand substitutes
for originals, quote-mining, and fake sources; a frozen hash format never
proves a page is genuine.
