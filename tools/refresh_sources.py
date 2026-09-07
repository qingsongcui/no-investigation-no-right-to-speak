#!/usr/bin/env python3
"""Refresh network-derived fields in an existing v2.4 source manifest.

Human-authored title, locator, supports and evidence mapping are preserved.
Only access status, final URL, fetched title, retrieval date and content hash are
updated. This deliberately cannot fabricate a source contract from a ledger.
"""
import argparse
import hashlib
import html
import json
import re
import urllib.request
from datetime import date
from pathlib import Path


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "deep-research-source-freezer/2.4"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        text = body.decode(charset, errors="replace")
        match = TITLE_RE.search(text)
        title = html.unescape(re.sub(r"\s+", " ", match.group(1)).strip()) if match else ""
        return response.status, response.geturl(), title, "sha256:" + hashlib.sha256(body).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("investigation_dir")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    path = Path(args.investigation_dir) / "source_manifest.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    refreshed = []
    failures = []
    for row in rows:
        try:
            status, final_url, fetched_title, fingerprint = fetch(row["canonical_url"], args.timeout)
            row.update({"access_status": status, "final_url": final_url,
                        "fetched_title": fetched_title, "content_fingerprint": fingerprint,
                        "retrieved_at": date.today().isoformat()})
        except Exception as exc:
            failures.append({"source_id": row.get("source_id"), "error": str(exc)})
        refreshed.append(row)
    if failures:
        print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2))
        return 1
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in refreshed), encoding="utf-8")
    print(json.dumps({"refreshed": len(refreshed), "manifest": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
