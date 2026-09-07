#!/usr/bin/env python3
"""Inspect or mark formal investigations for the v2.4 contract migration.

--check is read-only. --apply never invents research contracts: it only adds the
workflow marker and sets state=MIGRATION_REQUIRED. A human/agent must then build
the design, requirement, gap, dual-gate, synthesis and report contracts.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path


REQUIRED = [
    "research_design.json", "evidence_requirements.json", "gap_register.json",
    "evidence_gate_scores.json", "identification_gate_scores.json",
    "claim_authorization.json", "provisional_synthesis.json", "final_synthesis.json",
    "report_contract.json", "source_manifest.jsonl", "claim_source_map.json",
]


def formal_dirs(root):
    base = root / "investigations"
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name != "_quarantine")


def status(inv):
    brief = inv / "research_brief.yaml"
    text = brief.read_text(encoding="utf-8") if brief.exists() else ""
    v24 = bool(re.search(r'^\s*workflow_version:\s*["\']?2\.4["\']?\s*$', text, re.M))
    missing = [name for name in REQUIRED if not (inv / name).exists()]
    return {"investigation": inv.name, "workflow_v24": v24, "missing": missing,
            "status": "READY" if v24 and not missing else "MIGRATION_REQUIRED"}


def mark(inv):
    brief = inv / "research_brief.yaml"
    if not brief.exists():
        return False
    text = brief.read_text(encoding="utf-8")
    if re.search(r"^\s*workflow_version:", text, re.M):
        text = re.sub(r'^\s*workflow_version:.*$', 'workflow_version: "2.4"', text, count=1, flags=re.M)
    else:
        text = 'workflow_version: "2.4"\n' + text
    if re.search(r"^\s*state:", text, re.M):
        text = re.sub(r'^\s*state:.*$', 'state: MIGRATION_REQUIRED', text, count=1, flags=re.M)
    else:
        text += "\nstate: MIGRATION_REQUIRED\n"
    brief.write_text(text, encoding="utf-8")
    marker = {"schema_version": "2.4", "investigation": inv.name,
              "marked_at": date.today().isoformat(), "status": "MIGRATION_REQUIRED",
              "policy": "No inferred contracts; build missing artifacts from source evidence."}
    (inv / "migration_v24.json").write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    if args.apply:
        for inv in formal_dirs(root):
            mark(inv)
    rows = [status(inv) for inv in formal_dirs(root)]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 1 if args.check and any(x["status"] != "READY" for x in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
