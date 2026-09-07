# Examples

`agent-skill-installation-reviewed/` is the only shipped demonstration. It
answers a stable how-to question — installing one local Agent Skill from the
George O'Nair starter repository and confirming host discovery — as a
`reviewed` investigation against a frozen snapshot of that repository's README
(`snapshot-README.md`, SHA-256 recorded in `research.json`).

These examples demonstrate provenance and review-invalidation behavior: every
factual assertion carries a source kind and a heading-level locator, the
source bytes are frozen and hash-verified, and any change to the record or
the report invalidates the independent review. They do not demonstrate general
factual accuracy or live-web research performance — the report is bound to its
recorded snapshot, not to the current upstream README.
