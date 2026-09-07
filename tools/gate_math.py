"""gate_math v2.4 — 证据门禁与识别门禁的机器合并层

用途：独立门禁 subagent 只做判断（七维打分 + 阻断项 + 措辞 + 证据引用），
产出 gate_scores.json；本脚本（由总调查官运行，纯机械变换）负责：
1. 主张文本、claim_type、is_critical 逐字取自 research_brief.yaml（brief 是唯一权威，
   gate_scores 里的这些字段一律忽略，杜绝判断层覆盖立案元数据）；
2. quick 档轻门禁：直接用门禁给的五级标签，不跑 7 维公式；
   standard/deep 档：用授权公式重算 total / raw_score_level，并按阻断项降级得到 level；
3. 硬校验 gate_scores 的 ledger_selfcheck（行数/E-ID 覆盖），防"读截断台账"的门禁混过；
4. 写出 claim_authorization.json。

总调查官不在此处输入任何判断性数字；judgment 全部来自 gate_scores.json。
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from tools.validate import (  # type: ignore
        WEIGHTS, WEIGHTS_PREDICTIVE, _level_for, _step_down, _has_closure, _parse_brief_meta, _brief_depth,
    )
except ImportError:  # 允许从仓库根目录直接运行
    from validate import WEIGHTS, WEIGHTS_PREDICTIVE, _level_for, _step_down, _has_closure, _parse_brief_meta, _brief_depth


def main():
    if len(sys.argv) != 2:
        print("用法: python3 tools/gate_math.py <investigation_dir>")
        return 1
    root = Path(sys.argv[1])
    brief_text = (root / "research_brief.yaml").read_text(encoding="utf-8")
    brief_meta = _parse_brief_meta(brief_text)
    if not brief_meta:
        print("[FAIL] brief 未解析到任何主张（claim_id + claim 格式）")
        return 1
    depth = _brief_depth(brief_text)
    light = depth == "quick"
    scores_path = root / "evidence_gate_scores.json"
    identification_path = root / "identification_gate_scores.json"
    if not scores_path.exists():
        print("[FAIL] 缺失 evidence_gate_scores.json（独立证据门禁的判断输出）")
        return 1
    if not identification_path.exists():
        print("[FAIL] 缺失 identification_gate_scores.json（独立识别门禁的判断输出）")
        return 1
    gate = json.loads(scores_path.read_text(encoding="utf-8"))
    identification_gate = json.loads(identification_path.read_text(encoding="utf-8"))

    # 台账自检硬校验
    ledger_path = root / "evidence_ledger.jsonl"
    actual_rows = 0
    actual_ids = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            actual_rows += 1
            try:
                actual_ids.append(json.loads(line).get("evidence_id"))
            except json.JSONDecodeError:
                pass
    sc = gate.get("ledger_selfcheck") or {}
    if not isinstance(sc, dict) or not sc.get("rows_read"):
        print("[FAIL] evidence_gate_scores.json 缺 ledger_selfcheck（门禁须在输出里固化它读到的台账行数与 E-ID 覆盖）")
        return 1
    if int(sc.get("rows_read")) != actual_rows:
        print("[FAIL] 门禁自检行数 " + str(sc.get("rows_read")) + " 与台账实际行数 " + str(actual_rows) + " 不符（门禁读了截断/过期台账？）")
        return 1
    # E-ID 首尾与连续性硬校验（文档声称逐字核验，此处真正落地）
    if not actual_ids:
        print("[FAIL] 台账为空，无 E-ID 可校验")
        return 1
    if len(actual_ids) != len(set(actual_ids)):
        dupes = sorted({x for x in actual_ids if actual_ids.count(x) > 1})
        print("[FAIL] 台账存在重复 E-ID: " + str(dupes))
        return 1
    try:
        sorted_ids = sorted(actual_ids, key=lambda x: int(str(x).split("-")[1]))
    except Exception:
        sorted_ids = sorted(actual_ids)
    expected_first = sorted_ids[0]
    expected_last = sorted_ids[-1]
    sc_first = sc.get("eid_first")
    sc_last = sc.get("eid_last")
    if not isinstance(sc_first, str) or not isinstance(sc_last, str):
        print("[FAIL] evidence_gate_scores.json ledger_selfcheck 缺 eid_first/eid_last（门禁须固化 E-ID 范围）")
        return 1
    if sc_first != expected_first:
        print("[FAIL] 门禁自检 eid_first " + repr(sc_first) + " 与台账实际首条 " + repr(expected_first) + " 不符")
        return 1
    if sc_last != expected_last:
        print("[FAIL] 门禁自检 eid_last " + repr(sc_last) + " 与台账实际末条 " + repr(expected_last) + " 不符")
        return 1
    try:
        nums = [int(str(x).split("-")[1]) for x in sorted_ids]
        expected_nums = list(range(nums[0], nums[0] + len(nums)))
        if nums != expected_nums:
            print("[FAIL] 台账 E-ID 不连续: 实际 " + str(sorted_ids) + " 期望连续 " + str(["E-%03d" % n for n in expected_nums]) + "（存在跳号或缺号）")
            return 1
    except Exception:
        pass
    covered = set(sc.get("claims_covered") or [])
    missing = [cid for cid in brief_meta if cid not in covered]
    if missing:
        print("[FAIL] 门禁自检声称的主张覆盖缺 " + str(missing) + "（门禁读的台账不完整？）")
        return 1
    raw_claims = gate.get("claims") or []
    if not isinstance(raw_claims, list) or not raw_claims:
        print("[FAIL] evidence_gate_scores.json claims 为空或非数组")
        return 1
    gate_cids = [g.get("claim_id") for g in raw_claims]
    if len(gate_cids) != len(set(gate_cids)):
        dupes = [cid for cid in set(gate_cids) if gate_cids.count(cid) > 1]
        print("[FAIL] evidence_gate_scores.json 存在重复主张评分: " + str(dupes))
        return 1
    if set(gate_cids) != set(brief_meta.keys()):
        missing_cids = sorted(set(brief_meta.keys()) - set(gate_cids))
        extra_cids = sorted(set(gate_cids) - set(brief_meta.keys()))
        print("[FAIL] 门禁主张清单与立案清单未达成双向精确一一对应 (缺: " + str(missing_cids) + ", 多: " + str(extra_cids) + ")")
        return 1

    id_sc = identification_gate.get("ledger_selfcheck") or {}
    if id_sc != sc:
        print("[FAIL] 两个独立门禁的 ledger_selfcheck 不一致")
        return 1
    id_claims = identification_gate.get("claims") or []
    id_by_cid = {x.get("claim_id"): x for x in id_claims if isinstance(x, dict)}
    if set(id_by_cid) != set(brief_meta):
        print("[FAIL] 识别门禁主张清单与立案清单未达成双向精确一一对应")
        return 1

    out = {
        "schema_version": "2.4",
        "investigation": root.name,
        "gate_date": date.today().isoformat(),
        "claims": [],
    }
    for g in raw_claims:
        cid = g.get("claim_id")
        meta = brief_meta[cid]
        ident = id_by_cid[cid]
        evidence_blocking = g.get("blocking_issues") or []
        identification_blocking = ident.get("blocking_issues") or []
        common = {
            "claim_id": cid,
            "claim": meta["claim"],
            "claim_type": meta["claim_type"],
            "is_critical": meta["is_critical"],
            "blocking_issues": evidence_blocking + identification_blocking,
            "allowed_wording": g.get("allowed_wording") or "",
            "evidence_ids": g.get("evidence_ids") or [],
            "premises": g.get("premises") or [],
            "falsification_signals": g.get("falsification_signals") or [],
            "counterpoints": g.get("counterpoints") or [],
            "counterpoint_resolutions": g.get("counterpoint_resolutions") or [],
            "evidence_level": g.get("evidence_level") or g.get("level") or "no_standing",
            "identification_level": ident.get("identification_level") or "descriptive",
            "dimension_status": ident.get("dimension_status") or "no_standing",
            "unresolved_requirements": ident.get("unresolved_requirements") or [],
            "same_unit_observation": bool(ident.get("same_unit_observation", False)),
        }
        if light:
            level = g.get("level")
            if level not in ("confirmed", "provisional", "hypothesis", "weak_signal", "no_standing"):
                print("[FAIL] " + cid + ": quick 档门禁必须给五级标签 level，收到 " + repr(level))
                return 1
            common["level"] = level
            out["claims"].append(common)
            continue
        is_predictive = meta["claim_type"] in ("predictive", "trend", "strategic", "causal")
        weights = WEIGHTS_PREDICTIVE if is_predictive else WEIGHTS
        sc2 = g.get("scores") or {}
        if not set(weights).issubset(sc2):
            print("[FAIL] " + cid + " 缺少评分维度: " + str(set(weights) - set(sc2)))
            return 1
        penalty_sum = sum((p.get("points") or 0) for p in (g.get("penalties") or []))
        bias = g.get("bias_penalties") or {}
        bias_sum = bias.get("interest_bias", 0) + bias.get("search_ecology_bias", 0)
        total = sum(weights[k] * sc2[k] for k in weights) - penalty_sum - bias_sum
        total = max(0.0, min(100.0, total))
        total = round(total, 1)
        raw = _level_for(total, is_predictive=is_predictive)
        blocking = common["blocking_issues"]
        # v2.4: 条件闭环不能豁免证据或识别阻断项。
        level = _step_down(raw) if blocking else raw
        common["scores"] = {k: sc2[k] for k in weights}
        common["penalties"] = g.get("penalties") or []
        common["bias_penalties"] = bias
        common["total"] = total
        common["raw_score_level"] = raw
        common["level"] = level
        out["claims"].append(common)
    (root / "claim_authorization.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # v2.5: 生成语义许可 lexicon（命题级 allow/forbid，供 Writer 硬约束与句级蕴含门禁）
    lexicon = {"schema_version": "2.5", "investigation": root.name, "generated_at": date.today().isoformat(), "lexicon": []}
    for c in out["claims"]:
        level = c.get("level")
        dim = c.get("dimension_status")
        ident = c.get("identification_level")
        same = bool(c.get("same_unit_observation"))
        allowed = []
        forbidden = []
        if level == "confirmed":
            allowed = ["多项独立证据一致表明", "证实", "可判定"]
        elif level == "provisional":
            allowed = ["现有证据倾向于表明", "可作有条件判断"]
        elif level == "hypothesis":
            allowed = ["观察到若干信号，尚不足以定论；带前提可作条件式推断", "初步信号"]
        elif level == "weak_signal":
            allowed = ["仅有微弱信号；带条件可给倾向性提及", "微弱信号"]
        else:
            allowed = ["暂无发言权：公开材料不足以判断", "规模未知", "无法判断是否扩大", "现有材料不足以判断"]
            forbidden.extend(["小众", "大规模", "爆发", "显著增长", "显著下降", "广泛影响", "主流之外", "规模有限", "影响较窄", "尚未普及", "未形成广泛", "席卷"])
        if ident != "causal" and c.get("claim_type") == "causal":
            forbidden.extend(["导致", "因果关系", "因果效应", "驱动.*扩散", "引发.*话语"])
        if not same:
            forbidden.extend(["全国男性.*比例", "全国平均.*因果", "总体.*导致"])
        # 价与量分离：若证据中无价格，直接禁价
        if c["claim_id"] in ("C-01", "C-02") and level in ("weak_signal","no_standing"):
            forbidden.extend(["量价", "价格.*下降", "价格.*三杀"])
        lexicon["lexicon"].append({
            "claim_id": c["claim_id"],
            "level": level,
            "dimension_status": dim,
            "identification_level": ident,
            "same_unit_observation": same,
            "allowed_templates": allowed,
            "forbidden_patterns": sorted(set(forbidden))
        })
    (root / "claim_semantic_lexicon.json").write_text(json.dumps(lexicon, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"claim_semantic_lexicon.json 已生成: {len(lexicon['lexicon'])} 条命题许可")
    print("claim_authorization.json 已由机器层写出: " + str(len(out["claims"])) + " 项主张 (档位: " + ("quick 轻门禁" if light else "公式重算") + ")")
    print("总调查官注意: 请运行 python3 tools/validate.py gate " + str(root) + " 复核")


if __name__ == "__main__":
    raise SystemExit(main())
