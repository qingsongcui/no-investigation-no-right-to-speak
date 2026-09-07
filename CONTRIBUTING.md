# Contributing

## Validator behavior changes

Any pull request that changes validator behavior (`tools/research.py`,
`tools/validate.py`, or the schemas) must add or update a reproduction fixture
under `tests/` that fails before the fix and passes after it. Prose-only
assertions about quality are not accepted as behaviour coverage.

## Examples

Before adding a public example, perform an actual source and provenance
review: confirm every cited source was really read, every snapshot matches the
reviewed bytes, and no third-party material is included without redistribution
authority. If authority cannot be established, use a project-authored static
fixture and label it synthetic.

## Never add to a pull request

- Live client research or real investigation output.
- Scraped source archives, bulk downloads, or credential-bearing material.
- Generated PDF/DOCX binaries or workbench-local state.

The `.gitignore` blocks these categories; do not force-add them.
