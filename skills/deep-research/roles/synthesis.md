# Synthesis

Done on the main thread by default; do not spawn a duplicate agent to re-read
everything. Organize the evidence into an answer to the user's question: which
facts jointly support what explanation, what the strongest alternative is, how
far the available material discriminates, and how user constraints shape the
advice.

On the v3 paths, write `findings` premises/limitations and the natural answer
directly; do not generate two documents with duplicated content.

`audited` keeps `provisional_synthesis.json`, `final_synthesis.json`,
`synthesis.md`, and the legacy contracts. Use `schemas/synthesis.schema.json`
and `tests/fixtures/valid/` as the field reference; causal claims never exceed
the identification gate, and mechanism chains are never padded with rhetoric.
Synthesis artifacts are internal reasoning support, not per-section report
templates.
