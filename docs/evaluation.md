# Evaluating whether an answer is worth reading

Field conformance, source counts, word counts, and authorization scores are
not quality. Legacy regression checks cover only the specific errors they were
written for; they cannot be read as overall correctness rates, entailment
rates, or confidence probabilities.

## Six content criteria

| Criterion | Concrete question |
|---|---|
| Directness | Does it answer the original question, or quietly substitute a more familiar investment/policy template? |
| Evidence | Do the original pages actually support the numbers, dates, and scopes? Are access failures disclosed? |
| Reasoning | Is there an evidence bridge for the key explanation? What is the strongest counterexample? Is correlation presented as causation? |
| Constraints | Did budget, eligibility, and preferences actually change the recommendation? |
| Readability | Is it natural, coherent, and complete enough? Verbose, over-compressed, or template-stuffed? |
| Uncertainty | Are unknowns preserved while still answering the answerable part? |

A `reviewed` thread issues `review.json` against these criteria with concrete
reasons and quoted lines. The machine checks only that the review is complete
and matches the inputs; it cannot independently judge the review's honesty.
The author must not pre-fill an independent pass.

## Regression material

The legacy comparison fixtures under `tests/fixtures/valid/` exercise the old
audited contracts with synthetic placeholder sources. They pin tool behavior,
not answer quality: shorter output is not better output, and each change is
judged by coverage, reasoning boundaries, and readability.

Watch for these recurring failures:

- Recommending a high-cost path despite a stated limited budget.
- Asserting a specific asset flow from data that shows only a loan decline.
- Declaring a single cause for a group-level rate from one mismatched slice.
- Dodging analysis of a view's content for lack of representative data.
- Rewriting "uncertain" into awkward authorization jargon to satisfy a word
  list.

## Head-to-head evaluation (no pre-filled scores)

Pick real questions across four types — factual, explanatory, decisional,
disputed/causal — keeping the user's original wording and constraints. Collect
outputs from the old path, the new path, and the user's own baseline tool
under the same material boundary, recording date, model (when available), tool
permissions, and material limits. No group may see another group's prepared
answer.

Present outputs blind and in random order to an independent reviewer, compare
criterion by criterion with concrete reasons, then let the user pick the more
helpful one. Record: errors and omissions, whether key advice fits the
constraints, reading burden, real wall-clock time, and search/source-read
counts. Missing values stay unmeasured.

Fix order: remove critical factual, logical, and constraint errors first, then
compare understanding and decision help, then time and length. Speed never
excuses worse content; more content is not more value.
