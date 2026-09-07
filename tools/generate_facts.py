#!/usr/bin/env python3
"""P1-A Fact Extractor: evidence_ledger + source_manifest -> normalized_facts.jsonl

将 119 行台账转为原子事实，Writer 仅可读取 Fact DB 中的 value/period/unit，
price=UNKNOWN 时无法生成价格事实，从模型侧阻断“量价”幻觉。
"""
import json, re, sys
from pathlib import Path
from datetime import date

# 关键指标抽取规则：(metric, pattern, unit, geography)
RULES = [
    ("gdp_yoy", r"国内生产总值.*?同比.*?([0-9.]+)\s*%", "%", "CN"),
    ("gdp_q2_yoy", r"二季度.*?([0-9.]+)\s*%|Q2.*?([0-9.]+)\s*%", "%", "CN"),
    ("industrial_va_yoy", r"规上工业.*?([0-9.]+)\s*%|工业增加值.*?([0-9.]+)\s*%", "%", "CN"),
    ("retail_yoy", r"社零.*?([0-9.+\-]+)\s*%|社会消费品.*?\s*([0-9.+\-]+)\s*%", "%", "CN"),
    ("fixed_investment_yoy", r"固定资产投资.*?([\-0-9.]+)\s*%", "%", "CN"),
    ("private_investment_yoy", r"民间投资.*?([\-0-9.]+)\s*%", "%", "CN"),
    ("real_estate_investment_yoy", r"房地产开发投资.*?([\-0-9.]+)\s*%", "%", "CN"),
    ("real_estate_sales_yoy", r"商品房销售面积.*?([\-0-9.]+)\s*%|销售面积.*?([\-0-9.]+)\s*%", "%", "CN"),
    ("real_estate_funds_yoy", r"到位资金.*?([\-0-9.]+)\s*%", "%", "CN"),
    ("pmi_manufacturing", r"制造业PMI.*?([0-9.]+)", "", "CN"),
    ("pmi_small", r"小企业.*?([0-9.]+)", "", "CN"),
    ("pmi_construction", r"建筑业.*?([0-9.]+)", "", "CN"),
    ("unemployment_total", r"城镇调查失业率.*?([0-9.]+)\s*%", "%", "CN-urban"),
    ("unemployment_youth_16_24", r"16[—-]24岁.*?([0-9.]+)\s*%", "%", "CN-urban"),
    ("unemployment_youth_25_29", r"25[—-]29岁.*?([0-9.]+)\s*%", "%", "CN-urban"),
    ("unemployment_30_59", r"30[—-]59岁.*?([0-9.]+)\s*%", "%", "CN-urban"),
    ("weekly_hours", r"周平均工作时间.*?([0-9.]+)\s*小时", "小时", "CN"),
    ("migrant_workers", r"外出.*农民工.*?([0-9.]+)\s*万", "万人", "CN"),
    ("marriage_registrations_h1", r"结婚登记.*?([0-9.]+)\s*万对", "万对", "CN"),
    ("bride_price_effect_10w", r"十万元.*?([0-9.]+)\s*个百分点", "百分点", "CN-rural-migrant"),
]

def extract_value(pattern, text):
    m = re.search(pattern, text)
    if not m:
        return None
    for g in m.groups():
        if g and re.match(r"^-?[0-9.]+$", g):
            try:
                return float(g)
            except:
                return g
    return None

def main():
    if len(sys.argv) != 2:
        print("用法: python3 tools/generate_facts.py <investigation_dir>")
        return 1
    root = Path(sys.argv[1])
    ledger = root / "evidence_ledger.jsonl"
    manifest = root / "source_manifest.jsonl"
    if not ledger.exists():
        print(f"[FAIL] 缺失 {ledger}")
        return 1
    # 构建 source_id 映射
    source_map = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                # 映射 evidence_id -> source_id via evidence_ids
                for eid in r.get("evidence_ids") or []:
                    source_map[eid] = r.get("source_id")
            except:
                pass
    facts = []
    fid = 1
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        eid = row.get("evidence_id")
        text = row.get("quotation_or_data") or ""
        claim_ids = row.get("claim_ids") or []
        # 尝试匹配规则
        for metric, pat, unit, geo in RULES:
            val = extract_value(pat, text)
            if val is not None:
                period = "2026-01~07" if "1—7" in text or "1-7" in text else ("2026-07" if "7月" in text else "2026-H1")
                if "上半年" in text and metric.startswith("gdp"):
                    period = "2026-H1"
                if "二季度" in metric or "q2" in metric:
                    period = "2026-Q2"
                upstream = row.get("independence_group") or ""
                if "stats.gov.cn" in row.get("source_url",""):
                    family = upstream
                else:
                    family = row.get("independence_group") or "OTHER"
                # 判定 fact_type
                if metric == "bride_price_effect_10w":
                    ftype = "StudyEffectFact"
                elif metric.startswith("marriage"):
                    ftype = "NumericFact"
                else:
                    ftype = "NumericFact"
                facts.append({
                    "fact_id": f"F-{fid:03d}",
                    "evidence_id": eid,
                    "source_id": source_map.get(eid, "S-000"),
                    "fact_type": ftype,
                    "upstream_source": upstream,
                    "evidence_family": family,
                    "metric": metric,
                    "value": val,
                    "unit": unit,
                    "period": period,
                    "geography": geo,
                    "raw_passage": text[:120],
                    "supports_claim_ids": claim_ids,
                    "quality_grade": "A" if row.get("primary_or_secondary")=="primary" else "B",
                    "limitations": row.get("limitations") or []
                })
                # StudyEffect 额外字段
                if ftype == "StudyEffectFact":
                    facts[-1]["population"] = "16-29岁农村户籍未婚男性制造业零工"
                    facts[-1]["sample_n"] = 1338
                    facts[-1]["outcome_type"] = "self_reported_expectation"
                    facts[-1]["design"] = "observational"
                    facts[-1]["effect_type"] = "association"
                fid += 1
                break  # 每行只取首个匹配，避免重复
    # 显式加入 price=UNKNOWN 事实，防止量价幻觉
    # 若台账中无价格事实，则事实库中 price 保持 UNKNOWN，Writer 无材料可写价
    has_price = any(f["metric"]=="real_estate_price_yoy" for f in facts)
    if not has_price:
        facts.append({
            "fact_id": f"F-{fid:03d}",
            "evidence_id": "E-000",
            "source_id": "S-000",
            "fact_type": "UnknownFact",
            "unknown_subtype": "UNKNOWN_NOT_MEASURED",
            "upstream_source": "UNKNOWN",
            "evidence_family": "UNKNOWN",
            "metric": "real_estate_price_yoy",
            "value": "UNKNOWN",
            "unit": "%",
            "period": "2026-01~07",
            "geography": "CN",
            "raw_passage": "台账中无房价同比数据",
            "supports_claim_ids": [],
            "quality_grade": "D",
            "limitations": ["公开台账中未提供商品房价格同比，量与价不得混同"]
        })
        fid += 1
    out = root / "normalized_facts.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for fact in facts:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")
    print(f"normalized_facts.jsonl 已生成: {len(facts)} 条原子事实 (含 price=UNKNOWN 阻断)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
