#!/usr/bin/env python3
"""P0-2 Sentence-level Semantic Entailment Gate (v2.5) — clause-level with negation scope"""
import json
import re
import sys
from pathlib import Path

REGRESSION = [
    ("小众", "C-04", "T001 UNKNOWN规模→小众"),
    ("价格.*下降", "C-01", "T002 销售面积下降→价格下降"),
    ("主体.*不松|就业市场.*紧", "C-02", "T003 3.9%失业率→就业市场紧"),
    ("导致", "C-05", "T004 研究相关→导致（无因果识别时）"),
    ("全国男性", "C-05", "T005 样本农村男性→全国男性"),
]

SENT_SPLIT = re.compile(r"[。！？.!?]+")
CLAUSE_SPLIT = re.compile(r"[，,；;]+")

def load_lexicon(root: Path):
    p = root / "claim_semantic_lexicon.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {e["claim_id"]: e for e in data.get("lexicon", [])}
    except Exception:
        return {}

def check(root: Path):
    report = root / "final_report.md"
    if not report.exists():
        print(f"[FAIL] 缺失 {report}")
        return 1
    text = report.read_text(encoding="utf-8")
    body = text.split("## 参考资料")[0] if "## 参考资料" in text else text.split("参考资料")[0] if "参考资料" in text else text
    lex = load_lexicon(root)
    errors = []
    sentences = [s.strip() for s in SENT_SPLIT.split(body) if s.strip()]
    for s_idx, sent in enumerate(sentences, 1):
        clauses = [c.strip() for c in CLAUSE_SPLIT.split(sent) if c.strip()]
        if not clauses:
            clauses = [sent]
        for c_idx, clause in enumerate(clauses, 1):
            for cid, entry in lex.items():
                for pat in entry.get("forbidden_patterns") or []:
                    try:
                        if re.search(pat, clause):
                            if any(neg in clause for neg in ("不能","不可","无法","不足以","尚不支持","不直接","不是","并非")):
                                continue
                            errors.append(f"[FAIL] 句{s_idx}从句{c_idx}越权 {cid} 禁用“{pat}”命中: {clause[:60]}...")
                    except re.error:
                        if pat in clause:
                            errors.append(f"[FAIL] 句{s_idx}从句{c_idx}越权 {cid} 禁用词“{pat}”: {clause[:60]}")
            NEG = ("不能", "不可", "无法", "不足以", "尚不支持", "不直接", "不外推", "不能外推", "不是", "并非", "非全国", "不等于")
            for pat, cid, tid in REGRESSION:
                if re.search(pat, clause):
                    if any(neg in clause for neg in NEG):
                        continue
                    entry = lex.get(cid)
                    if entry and entry.get("level") in ("no_standing", "weak_signal") or entry and entry.get("dimension_status") in ("no_standing","data_access_required"):
                        if tid.startswith("T002") and "销售" in clause and "价格" in clause:
                            errors.append(f"[FAIL] {tid} 句{s_idx}从句{c_idx}: {clause[:60]}")
                        elif tid.startswith("T003") and "失业率" in clause and re.search(r"不松|紧", clause):
                            errors.append(f"[FAIL] {tid} 句{s_idx}从句{c_idx}: {clause[:60]}")
                        elif tid not in ("T002","T003"):
                            errors.append(f"[FAIL] {tid} 句{s_idx}从句{c_idx}: {clause[:60]}")
    if errors:
        for e in errors:
            print(e)
        print(f"\n== entailment 校验完成: {len(errors)} 错误 ==")
        print("结果: [FAIL]")
        return 1
    print("== entailment 校验完成: 0 错误 ==")
    print("结果: [PASS]")
    return 0

def main():
    if len(sys.argv) != 2:
        print("用法: python3 tools/entailment_check.py <investigation_dir>")
        return 2
    return check(Path(sys.argv[1]))

if __name__ == "__main__":
    raise SystemExit(main())
