# PROVENANCE

Every file in this public repository was either authored for this release or
copied from the author's private workbench after a file-by-file provenance
review. No third-party code is vendored: all tools use the Python standard
library, except the optional `tools/export_pdf.py`, which imports the
third-party `python-docx` package at use time and is not required for the
release verification commands.

## Copied directories

- `tools/` — original research/validation/export utilities; standard library
  except the optional `python-docx` import in `export_pdf.py`. Origin: author
  workbench. Redistribution: permitted, original work, MIT.
- `schemas/` — original JSON contracts for the v3 research/review workflow and
  the legacy audited compatibility path. Origin: author workbench.
  Redistribution: permitted, original work, MIT.
- `templates/` — original starter records for new investigations. Origin:
  author workbench. Redistribution: permitted, original work, MIT.
- `tests/` (including `tests/fixtures/valid/`) — original behavior tests plus
  synthetic audited-path fixtures using `example.org` placeholder URLs. Origin:
  author workbench. Redistribution: permitted, original work, MIT.
- `skills/deep-research/` (from workbench `.workbuddy/skills/deep-research/`)
  — original agent workflow and role prompts, rewritten in English for this
  release with public paths. Origin: author workbench. Redistribution:
  permitted, original work, MIT.
- `docs/architecture.md`, `docs/security.md`, `docs/evaluation.md` — public
  English descriptions of actual behavior and limitations, rewritten for this
  release from workbench originals. Redistribution: permitted, original work,
  MIT.

## Not copied

Live investigations, client research output, source archives, backups, prior
historical examples, generated PDF/DOCX files, and workbench memory/state were
deliberately excluded and are additionally blocked by `.gitignore`.

## Example snapshot

`examples/agent-skill-installation-reviewed/snapshot-README.md` is a frozen
copy of the public `qingsongcui/claude-code-skills` README taken at release
time, recorded with SHA-256. It is a review fixture owned by this example, not
a claim over the upstream repository, which keeps its own MIT license.
