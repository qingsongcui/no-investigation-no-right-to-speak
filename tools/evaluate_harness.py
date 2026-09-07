#!/usr/bin/env python3
"""P1-C Evaluation Harness v0 — 20-task benchmark with UPR

指标:
  UPR = 保持UNKNOWN的应未知维度 / 全部ground-truth UNKNOWN
  Unsupported Claim Rate, Citation Entailment, Primary Recovery 等

用法: python3 tools/evaluate_harness.py investigations/<slug>/
"""
import json, re, sys
from pathlib import Path

def evaluate(root: Path):
    root = Path(root)
    if (root / "research.json").exists():
        try:
            from tools.research import validate, metrics, read
        except ImportError:
            from research import validate, metrics, read
        errors, warnings = validate(root)
        review_path = root / "review.json"
        try:
            review = read(review_path) if review_path.exists() else None
        except (ValueError, OSError):
            review = None
        result = {"structural_pass": not errors, "errors": errors, "warnings": warnings,
                  "quality_review": review, "metrics": metrics(root),
                  "truth_accuracy": "not_machine_measured",
                  "web_gpt_comparison": "not_performed"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(bool(errors))
    print("[NOTE] Legacy rule diagnostics only; not semantic entailment, accuracy or calibrated confidence.")
    auth_path = root / "claim_authorization.json"
    lex_path = root / "claim_semantic_lexicon.json"
    ledger_path = root / "evidence_ledger.jsonl"
    report_path = root / "final_report.md"
    facts_path = root / "normalized_facts.jsonl"
    if not auth_path.exists():
        print("[FAIL] 缺失 claim_authorization.json")
        return 1
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    claims = auth.get("claims") or []
    # UPR: ground-truth UNKNOWN 为 dimension_status in (no_standing, data_access_required) 或 level no_standing
    gt_unknown = [c for c in claims if c.get("dimension_status") in ("no_standing","data_access_required") or c.get("level")=="no_standing"]
    total_unknown = len(gt_unknown)
    # 报告中是否仍保持 UNKNOWN（未出现 forbidden 语义）
    lex = {}
    if lex_path.exists():
        try:
            lex = {e["claim_id"]: e for e in json.loads(lex_path.read_text(encoding="utf-8")).get("lexicon", [])}
        except:
            pass
    report_text = report_path.read_text(encoding="utf-8").split("## 参考资料")[0] if report_path.exists() else ""
    preserved = 0
    for c in gt_unknown:
        cid = c["claim_id"]
        entry = lex.get(cid, {})
        forbidden = entry.get("forbidden_patterns") or []
        # 若报告中未命中任何 forbidden，则视为保持 UNKNOWN
        hit = any(re.search(pat, report_text) for pat in forbidden if pat)
        if not hit:
            preserved += 1
    upr = preserved / total_unknown if total_unknown else 1.0
    # Unsupported Claim Rate：报告中出现规模/因果词但无授权
    unsupported = total_unknown - preserved
    ucr = unsupported / len(claims) if claims else 0
    # Citation Entailment：fact DB 中 price=UNKNOWN 时报告是否出现价格判断
    price_unknown = False
    price_in_report = False
    if facts_path.exists():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                f = json.loads(line)
                if f.get("metric")=="real_estate_price_yoy" and f.get("value")=="UNKNOWN":
                    price_unknown = True
            except:
                pass
        if price_unknown and re.search(r"价格.*下降|房价.*%", report_text):
            price_in_report = True
    # Primary Recovery：factual claims 中 primary+direct 比例
    ledger = {}
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                ledger[r["evidence_id"]] = r
            except:
                pass
    factual_claims = [c for c in claims if c.get("claim_type")=="factual"]
    primary_ok = 0
    for c in factual_claims:
        eids = c.get("evidence_ids") or []
        if any(ledger.get(eid, {}).get("primary_or_secondary")=="primary" for eid in eids):
            primary_ok += 1
    primary_rate = primary_ok / len(factual_claims) if factual_claims else 0
    # Independence: distinct families vs rows
    families = set(r.get("evidence_family") or r.get("independence_group") for r in ledger.values())
    indep_rate = len(families) / len(ledger) if ledger else 0
    # CAVR: Claim Authorization Violation Rate
    # 统计报告原子句中违反 lexicon 的比例（由 entailment_check 已统计，此处复用 UPR 逻辑）
    cavr = 1 - upr  # 简化：CAVR = 1 - UPR（越权即违反授权）
    # Confidence Engine Q*I*S*D*R（简化规则型）
    # Q: 平均 source_quality, I: 独立性, S: scope match (same_unit), D: identification, R: replication
    import collections
    qs = [r.get("source_quality",0.5) for r in ledger.values()]
    Q = sum(qs)/len(qs) if qs else 0
    I = indep_rate
    # S: same_unit 比例
    same_unit_cnt = sum(1 for c in claims if c.get("same_unit_observation"))
    S = same_unit_cnt / len(claims) if claims else 0
    # D: identification_level 分布，causal 需谨慎
    D = sum(1 for c in claims if c.get("identification_level") in ("descriptive","mechanistic")) / len(claims) if claims else 0
    # R: 多源一致性（简用独立 family 数/总 claims）
    R = min(1.0, len(families)/ (len(claims)*5)) if claims else 0
    confidence = Q*I*S*D*R
    conf_label = "HIGH" if confidence>0.6 else "MEDIUM" if confidence>0.3 else "LOW"
    print(f"== Harness v0: {root.name} ==")
    print(f"UPR (Unknown Preservation Rate): {preserved}/{total_unknown} = {upr:.2%}")
    print(f"CAVR (Authorization Violation Rate): {cavr:.2%} (target 0%)")
    print(f"Unsupported Claim Rate: {unsupported}/{len(claims)} = {ucr:.2%}")
    print(f"Citation Entailment (price UNKNOWN not leaked): {'PASS' if not (price_unknown and price_in_report) else 'FAIL'}")
    print(f"Primary Source Recovery (factual): {primary_ok}/{len(factual_claims)} = {primary_rate:.0%}")
    print(f"Independence: {len(families)}/{len(ledger)} families = {indep_rate:.0%}")
    print(f"Uncalibrated legacy heuristic Q*I*S*D*R: {confidence:.3f} → {conf_label} (Q={Q:.2f} I={I:.2f} S={S:.2f} D={D:.2f} R={R:.2f})")
    print(f"Claims: {len(claims)} total, {total_unknown}应未知")
    fail = False
    if upr < 0.8:
        print(f"[FAIL] UPR {upr:.0%} <80%（UNKNOWN→小众类越权未守住）")
        fail = True
    if ucr > 0.2:
        print(f"[WARN] Unsupported {ucr:.0%} >20%")
    if indep_rate < 0.5:
        print(f"[WARN] 独立性 {indep_rate:.0%} <50%")
    if fail:
        print("结果: [FAIL]")
        return 1
    print("结果: [PASS]")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python3 tools/evaluate_harness.py <investigation_dir>")
        sys.exit(2)
    sys.exit(evaluate(Path(sys.argv[1])))
