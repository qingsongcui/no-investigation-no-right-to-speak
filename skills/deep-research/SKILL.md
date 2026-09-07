---
name: deep-research
description: Investigate a user question with recorded evidence and answer it directly; high-stakes decisions get independent review, formal audit keeps a double-gate path.
version: 0.1.0
---

# Deep Research

After reading this file fully, operate under the root `AGENTS.md`. This is the
research entry point, not a checklist that demands the full pipeline on every
run.

## 1. Understand and route

First state in a few sentences the core problem to solve. Infer reasonable
preferences directly; ask only for missing budget/eligibility information that
would change the conclusion, while pushing ahead on work that does not depend
on the answer. Never routinely ask for a depth tier, page count, or claim
count.

Default to `answer`. Use `reviewed` for consequential decisions, explicit
causal conclusions, or substantive evidence conflicts. Use `audited` for formal
audits and for continuing legacy v2.4 investigations.

Route to `reviewed` by default when the answer will drive decisions about
investment, immigration, employment, medical care, legal action, insurance,
credit, housing, or education/admission — and record the routing reason in the
investigation scope. This is a judgment call by the initiating agent, not a
keyword match: a concept explanation that merely mentions one of these areas
does not auto-escalate, while a decision inside one of them must not be
quietly downgraded.

New task:

```bash
python3 tools/research.py init <dir> --question '<user question>' --author-id '<operator id>'
# High-stakes work adds --stakes high; planned causal conclusions add --causal
```

This creates only `research.json`. Fill in `scope`, `constraints`, and
`questions`; the number of questions follows actual confusion, never a
mechanical split of a long question into dozens of claims. `init` performs no
search and calls no model.

## 2. Investigate: answer one real open point per round

Form a refutable overall explanation first, then check the open point that
would change the conclusion most. Prefer primary, specific pages on the main
thread. Search and access follow the runtime's native tools; time-sensitive,
technical, and high-risk information follows the current tool requirements.

Append each adopted piece of evidence to `research.json` sources: accurate
title, URL, access time, the excerpt actually read or a faithful summary, and
limitations. Do not copy whole pages, and do not log irrelevant search hits.
When a re-checkable snapshot is needed, store the original content and fill in
`snapshot_path`/`snapshot_sha256`. A reprint from the same origin must not
pose as independent corroboration.

Record real `query`, `purpose`, `source_ids`, and `gain` in `searches`; a gain
of "nothing new" is allowed. Strongest counterexamples, alternative
explanations, affected-party experience, and source chains are investigated
when relevant, never as five query types times claim count. On source conflict,
compare dates, definitions, samples, and originals; escalate to `reviewed`
when needed.

For genuinely independent problems, use the collector role with one concrete
open point each and one scratch output file; never send several agents to
re-read the whole ledger. Pass self-contained tasks, read-only inputs, unique
output paths, and untrusted JSON data. Do not create sidebar tasks the user
did not ask for.

`findings` keeps only judgments the report actually uses, typed `fact` /
`inference` / `recommendation` / `causal` / `unknown`, with `question_ids`,
`source_ids`, `premises`, and `limitation`. Judgments and questions map both
ways. Visa thresholds do not imply employment probabilities; two correlated
indicators do not imply a single cause.

In `reviewed` mode, every source behind a `fact` or `causal` finding needs
`source_kind` (`primary`, `secondary`, or `user_provided`), an
`evidence_locator` (heading, paragraph range, page range, or table label),
and a SHA-256-verified snapshot stored inside the investigation directory.

## 3. Stop or keep digging

Ask: are the user's questions answered or explicitly left unknown? What missing
piece would change the recommendation? Is there a workable source for it?

- Workable and important next step exists: keep digging.
- Key data unobtainable or costlier than authorized: write the attempted
  outcome into `gaps` with `status=access_required/bounded` and a resolution,
  and state the impact in the answer. Never output false certainty.
- Answerable now, further search only adds examples: `stop.reason=answered`.
- Bounded but still useful: `stop.reason=bounded`, with the boundary
  explained.
- User budget exhausted: `budget_exhausted`; never dress it up as complete.

No fixed round, source, word, or page quotas. Never rename a fixable critical gap as non-critical just to stop.

## 4. Write a normal answer

Lead with one true sentence or paragraph, then follow the reader's questions.
Ask first: what is my judgment, why, and what should the user understand or do
next. Writing detail lives in `roles/report.md`.

`final_report.md` needs no summary, charts, outlook section, or fixed
references heading. Place citations as Markdown links near the claims they
support, with an optional reference list; never heap links only at the end.
Length follows explanatory completeness; deleting words is not clarity work.

After writing, fill each question/finding with a real `report_excerpt` so
omissions are detectable. Locate key judgments only; do not register every
sentence as a claim.

## 5. Verify and review independently

`answer`: the author re-checks every key fact, source mapping, user
constraint, and the strongest counterexample, then runs `research.py check`.

`reviewed`: first run `check --draft` (final review not yet required); take
the `research.py fingerprint`; send a **fresh thread** with none of the
author's history to the review role, giving only the user question,
`research.json`, `final_report.md`, and the original sources — never the
conclusion the author hopes for. `reviewer_id` holds the actual reviewing
agent's identifier and `provenance` records the actual review execution.
Writing "independently passed" as the author is forbidden. When no
independent reviewer is available, say the independent review is incomplete: a
clearly labeled draft may be delivered, never claimed as passed. Review
problems trigger targeted re-investigation or rewriting; after any change,
re-take the fingerprint and have the final version reviewed. Unresolved
blocking issues are not delivered as done.

```bash
python3 tools/research.py check <dir>
```

The program verifies only structure and source traceability; it does not
understand every sentence. A PASS is never a quality certificate. Whether the
answer and its advice hold is carried by actual source checking and the review
notes.

## 6. Audited compatibility path

Investigations that already use the legacy entry and have no `research.json`
follow the v2.4 contracts: research design/requirements/gaps, evidence
ledger, independent evidence-gate and identification-gate, gate math, two-stage
synthesis, report contract with frozen sources. Do not rewrite stored state or
authorizations. The two gates may read the same frozen input in parallel with
no author history; `gate_math` runs only once both outputs arrive. See the
role files and the contract fixtures under `tests/fixtures/valid/`. Writing
still prefers natural expression; a new audit report may set
`presentation="natural"` in `report_contract.json` to keep evidence/coverage
checks while dropping the summary and outlook-heading form requirements. Old
files default to legacy.

## 7. Timing, resuming, exporting

Real stage timings can be recorded with `research.py event <dir> --stage
search --seconds <measured> --note 'what was done'`; `metrics` aggregates
them. Parallel-stage totals are not wall-clock latency. Leave unobserved
values empty.

When resuming, read the existing record first and add only missing work. The
`journal query` input must include the input-file content fingerprint, the
role version, and the freshness boundary; after a hit, still check the output
files exist and are unchanged and the sources are not stale. A cache hit is
not proof the source is still valid.

Default delivery is the answer plus Markdown. Call `export_pdf.py` only when
the user asks for files; it is formatting and must not add conclusions,
bylines, or data. Never copy outputs to the desktop unasked.
