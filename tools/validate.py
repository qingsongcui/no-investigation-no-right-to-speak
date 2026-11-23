#!/usr/bin/env python3
"""deep-research: audited v2.4 checks plus v3 speak dispatch

用法：
  python3 tools/validate.py gate  investigations/<slug>/
  python3 tools/validate.py synthesis investigations/<slug>/
  python3 tools/validate.py speak investigations/<slug>/

gate : 重算门禁授权公式（A/B 分轨）、核对等级映射与措辞纪律、核对主张-证据双向归属、台账字段完整性（含 search_round 与 E-ID 连续性）。
speak: 纯净交付版校验：核对 synthesis.md 硬前置、审计段落沉底、无机器编号泄漏、参考资料去重、前瞻章条件式。
synthesis: 校验 synthesis.json 存在性与引用合法性（standard/deep 缺失为硬错误）。

任何 [FAIL] 都表示未通过（退出码非 0）。只允许改数据，不允许改本校验器。
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

WEIGHTS = {"Q": 0.22, "D": 0.18, "I": 0.16, "C": 0.16, "R": 0.12, "X": 0.10, "P": 0.06}
WEIGHTS_PREDICTIVE = {"Q": 0.18, "D": 0.16, "I": 0.12, "C": 0.20, "R": 0.10, "X": 0.14, "P": 0.10}
LEVEL_THRESHOLDS = [(85, "confirmed"), (70, "provisional"), (50, "hypothesis"), (30, "weak_signal")]
LEVEL_THRESHOLDS_PREDICTIVE = [(80, "confirmed"), (65, "provisional"), (45, "hypothesis"), (25, "weak_signal")]
LEVEL_ORDER = {"no_standing": 0, "weak_signal": 1, "hypothesis": 2, "provisional": 3, "confirmed": 4}
LEVEL_LABELS = {
    "confirmed": "已确认",
    "provisional": "暂定",
    "hypothesis": "假设",
    "weak_signal": "弱信号",
    "no_standing": "暂无发言权",
}
DEFINITIVE = ["已证实", "已确认", "完全证实", "确定", "必然", "一定", "铁定", "无疑"]
NEG_PREFIXES = ["不", "非", "未", "并无", "并非", "并不", "未必", "不可", "无法", "难以"]
CONDITIONAL_WORDS = ["若", "如果", "前提", "取决于", "条件", "当"]
CLAIM_TYPES = {"factual", "causal", "predictive", "trend", "strategic", "normative"}
PRIMARY_ENUM = {"primary", "secondary", "tertiary"}
DIRECT_ENUM = {"direct", "indirect", "circumstantial"}
INTEREST_ENUM = {"commercial", "government", "advocacy", "academic", "personal", "mixed", "unknown"}
SOR_ENUM = {"supports", "refutes", "neutral_context"}
URL_RE = re.compile("^https?://", re.I)
DATE_RE = re.compile("^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
CID_RE = re.compile("(?<![A-Za-z0-9])[CcEeSs]-[0-9][0-9]+(?![A-Za-z0-9])")
MATERIAL_RE = re.compile("资料[一二三四五六七八九十]")
PIPELINE_JARGON_RE = re.compile(r"先说分析框架|合成推演阶段|主链一句|我们怎么推到这个结论|先说方法再上事实|先说方法再给证据|为何只能读作|为什么不能判|为何只能先作|给形成判断者的三条纪律|基于\d+行.*台账|comparison_universe_status")
URL_EXTRACT_RE = re.compile("https?://[A-Za-z0-9./_?=&%#+:@-]+")
APPENDIX_MARK = "发言权对照表"
REF_MARK = "参考资料"
SUMMARY_MARK = "执行摘要"
FORWARD_WORDS = ["接下来", "前瞻", "行动", "该怎么做"]
FINAL_STATES = {
    "COMPLETE_DESCRIPTIVE", "COMPLETE_MECHANISTIC", "COMPLETE_CAUSAL",
    "PARTIAL_WITH_BOUNDED_CLAIMS", "DATA_ACCESS_REQUIRED", "GAP_REPORT",
}
IDENTIFICATION_LEVELS = {"descriptive", "correlational", "mechanistic", "causal"}
DIMENSION_STATUSES = {"complete", "bounded", "data_access_required", "no_standing"}
ROOT_PATHS = {"", "/", "/index.html", "/index.htm", "/home", "/home/"}


class Result:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, msg):
        self.errors.append(msg)
        print("[FAIL] " + msg)

    def warn(self, msg):
        self.warnings.append(msg)
        print("[WARN] " + msg)


def norm(text):
    return "".join(str(text).split())


def _contains_definitive(text):
    if not isinstance(text, str):
        return False
    for kw in DEFINITIVE:
        idx = 0
        while True:
            pos = text.find(kw, idx)
            if pos == -1:
                break
            pre1 = text[pos - 1:pos] if pos >= 1 else ""
            pre2 = text[pos - 2:pos] if pos >= 2 else ""
            if pre1 in NEG_PREFIXES or pre2 in NEG_PREFIXES:
                idx = pos + len(kw)
                continue
            return True
    return False


def _list_ok(value):
    return isinstance(value, list) and bool(value) and all(
        isinstance(x, str) and x.strip() for x in value
    )


def _has_premises(item):
    return _list_ok(item.get("premises")) and _list_ok(item.get("falsification_signals"))


def _has_closure(item):
    counterpoints = item.get("counterpoints") or []
    resolutions = item.get("counterpoint_resolutions")
    return (
        _has_premises(item)
        and isinstance(resolutions, list)
        and all(isinstance(x, str) and x.strip() for x in resolutions)
        and len(resolutions) == len(counterpoints)
    )


def _level_for(total, is_predictive=False):
    thresholds = LEVEL_THRESHOLDS_PREDICTIVE if is_predictive else LEVEL_THRESHOLDS
    for thr, lv in thresholds:
        if total >= thr:
            return lv
    return "no_standing"


def _step_down(lv):
    if lv == "no_standing":
        return "no_standing"
    return {0: "no_standing", 1: "weak_signal", 2: "hypothesis", 3: "provisional", 4: "confirmed"}[
        LEVEL_ORDER[lv] - 1
    ]


def _has_conditional(text):
    """判断是否真含条件词（"当"排除 当前/应当/当时/相当 等假阳性）。"""
    for w in ("若", "如果", "取决于", "前提", "条件"):
        if w in text:
            return True
    return re.search(r"当(?!前|应|时|天|地|局|事|初|成|然|即|下|中|真|晚|早|今|明|午|夜|代|面|权|选|红|场)", text) is not None


def _parse_brief_claims(text):
    """从立案书提取主张清单（cid -> 文本）。格式不匹配时返回空 dict（不强制）。"""
    claims = {}
    for m in re.finditer(r'claim_id:\s*["\']?(C-[0-9][0-9]+)["\']?[\s\S]*?claim:\s*["\']([^"\']*)["\']', text):
        claims[m.group(1)] = m.group(2)
    return claims


def _brief_depth(text):
    m = re.search(r"^\s*depth:\s*(\w+)\s*$", text, re.M)
    return m.group(1).strip() if m else "standard"


def _parse_brief_meta(text):
    """解析 brief 每项主张的元数据: cid -> {claim, claim_type, is_critical}。格式不匹配时返回空 dict。"""
    meta = {}
    blocks = re.split(r"\n\s*-?\s*claim_id:\s*[\"']?(C-[0-9][0-9]+)[\"']?", text)
    # blocks: [前导, C-01, 块1, C-02, 块2, ...]
    for i in range(1, len(blocks), 2):
        cid = blocks[i]
        block = blocks[i + 1]
        m_claim = re.search(r'claim:\s*["\']([^"\']*)["\']', block)
        m_type = re.search(r'claim_type:\s*(\w+)', block)
        m_crit = re.search(r'is_critical:\s*(\w+)', block)
        if m_claim is None:
            continue
        meta[cid] = {
            "claim": m_claim.group(1),
            "claim_type": m_type.group(1) if m_type else None,
            "is_critical": (m_crit.group(1) == "true") if m_crit else None,
        }
    return meta


def load_json(path, res):
    p = Path(path)
    if not p.exists():
        res.err("缺失文件: " + str(p))
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        res.err("JSON 解析失败 " + str(p) + ": " + str(exc))
        return None


def load_jsonl(path, res, label):
    p = Path(path)
    if not p.exists():
        res.err("缺失 " + p.name + "（" + label + "）")
        return []
    rows = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            res.err(p.name + " 第 " + str(lineno) + " 行 JSON 解析失败: " + str(exc))
    return rows


def _is_v24(brief_text):
    return re.search(r'^\s*workflow_version:\s*["\']?2\.4["\']?\s*$', brief_text, re.M) is not None


def _validate_design_contracts(root, brief_text, res, enforce_stop=False):
    """v2.4 前置研究设计、需求与缺口闭环。返回三个契约。"""
    if not _is_v24(brief_text):
        res.err("调查尚未迁移到 workflow_version 2.4（状态应为 MIGRATION_REQUIRED）")
        return None, None, None
    design = load_json(root / "research_design.json", res)
    requirements = load_json(root / "evidence_requirements.json", res)
    gaps = load_json(root / "gap_register.json", res)
    if not all(isinstance(x, dict) for x in (design, requirements, gaps)):
        return design, requirements, gaps
    if design.get("schema_version") != "2.4":
        res.err("research_design.json schema_version 必须为 2.4")
    questions = design.get("questions")
    if not isinstance(questions, list) or not questions:
        res.err("research_design.json questions 必须是非空数组")
        questions = []
    brief_claims = set(_parse_brief_meta(brief_text))
    seen_q = set()
    covered_claims = set()
    for q in questions:
        qid = q.get("question_id")
        if not isinstance(qid, str) or not re.match(r"^RQ-[0-9]{2}$", qid):
            res.err("research_design question_id 非法: " + repr(qid))
            continue
        if qid in seen_q:
            res.err("research_design question_id 重复: " + qid)
        seen_q.add(qid)
        rtype = q.get("research_type")
        if rtype not in {"descriptive", "measurement", "comparative", "mechanistic", "causal", "predictive"}:
            res.err(qid + ": research_type 非法")
        for key in ("question", "unit_of_analysis", "time_granularity", "population", "identification_strategy"):
            if not isinstance(q.get(key), str) or not q[key].strip():
                res.err(qid + ": " + key + " 必须为非空字符串")
        for key in ("claim_ids", "required_data", "unacceptable_substitutes"):
            if not _list_ok(q.get(key)):
                res.err(qid + ": " + key + " 必须为非空字符串数组")
        qclaims = set(q.get("claim_ids") or [])
        covered_claims.update(qclaims)
        unknown = qclaims - brief_claims
        if unknown:
            res.err(qid + ": 引用 brief 不存在的主张 " + str(sorted(unknown)))
        if rtype == "causal":
            for key in ("outcome_variable", "exposure_variable"):
                if not isinstance(q.get(key), str) or not q[key].strip():
                    res.err(qid + ": 因果设计必须填写 " + key)
            if not q.get("feasible") and q.get("fallback_type") not in {"descriptive", "measurement", "comparative", "mechanistic", "correlational"}:
                res.err(qid + ": 不可行因果设计必须声明可执行 fallback_type")
            if q.get("feasible") and not _list_ok(q.get("confounders")):
                res.err(qid + ": 可行因果设计必须登记 confounders")
    missing_claims = brief_claims - covered_claims
    if missing_claims:
        res.err("research_design 未覆盖 brief 主张: " + str(sorted(missing_claims)))

    reqs = requirements.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        res.err("evidence_requirements.json requirements 必须为非空数组")
        reqs = []
    req_ids = set()
    for req in reqs:
        rid = req.get("requirement_id")
        if not isinstance(rid, str) or not re.match(r"^ER-[0-9]{2,}$", rid):
            res.err("evidence requirement_id 非法: " + repr(rid))
            continue
        if rid in req_ids:
            res.err("evidence requirement_id 重复: " + rid)
        req_ids.add(rid)
        if req.get("status") not in {"open", "met", "unavailable", "access_required"}:
            res.err(rid + ": status 非法")
        if not _list_ok(req.get("question_ids")) or not set(req.get("question_ids") or []).issubset(seen_q):
            res.err(rid + ": question_ids 缺失或引用未知问题")
        if not _list_ok(req.get("claim_ids")) or not set(req.get("claim_ids") or []).issubset(brief_claims):
            res.err(rid + ": claim_ids 缺失或引用未知主张")

    gap_rows = gaps.get("gaps")
    if not isinstance(gap_rows, list):
        res.err("gap_register.json gaps 必须是数组")
        gap_rows = []
    max_r, used_r = _parse_budget(brief_text)
    for gap in gap_rows:
        gid = gap.get("gap_id") or "未知缺口"
        status = gap.get("status")
        if status not in {"open", "closed", "publicly_unavailable", "access_required", "cost_exceeded"}:
            res.err(str(gid) + ": gap status 非法")
        if not _list_ok(gap.get("requirement_ids")) or not set(gap.get("requirement_ids") or []).issubset(req_ids):
            res.err(str(gid) + ": requirement_ids 缺失或引用未知需求")
        if status in {"publicly_unavailable", "access_required", "cost_exceeded"} and not _list_ok(gap.get("attempted_paths")):
            res.err(str(gid) + ": 不可获得/需访问/超成本缺口必须记录 attempted_paths")
        has_path = isinstance(gap.get("next_feasible_path"), str) and bool(gap.get("next_feasible_path").strip())
        budget_left = max_r is not None and used_r is not None and used_r < max_r
        if enforce_stop and gap.get("critical") and status == "open" and has_path and budget_left:
            res.err(str(gid) + ": 关键缺口仍开放、存在可行路径且预算未用尽，禁止进入门禁")
    return design, requirements, gaps


def design(root):
    res = Result()
    root = Path(root)
    brief_path = root / "research_brief.yaml"
    if not brief_path.exists():
        res.err("缺失 research_brief.yaml")
        brief_text = ""
    else:
        brief_text = brief_path.read_text(encoding="utf-8")
    _validate_design_contracts(root, brief_text, res, enforce_stop=False)
    # P0-3: 确定性时序与来源天花板（T_o/T_p/T_r + Source Ceiling + 独立性）
    try:
        # 解析 DATA_CUTOFF：取 time_range 中第二个日期
        m = re.search(r"time_range:\s*\"?([0-9]{4}-[0-9]{2}-[0-9]{2})[^0-9]+([0-9]{4}-[0-9]{2}-[0-9]{2})", brief_text)
        cutoff = m.group(2) if m else None
        if cutoff:
            # 校验台账时序：published_at/retrieved_at 不得晚于 cutoff + 1天（允许检索次日）
            ledger_path = root / "evidence_ledger.jsonl"
            if ledger_path.exists():
                for lineno, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    eid = row.get("evidence_id", f"行{lineno}")
                    pub = row.get("published_at", "")
                    ret = row.get("retrieved_at", "")
                    if pub and pub > cutoff:
                        res.err(f"时序越界: {eid} published_at {pub} 晚于 DATA_CUTOFF {cutoff}（未来信息泄漏）")
                    if pub and ret and ret < pub:
                        res.err(f"时序倒置: {eid} retrieved_at {ret} 早于 published_at {pub}")
                    # S-007类二手转述未升级：若 evidence 为 secondary 但 claim 需要 primary，则需在 limitations 显式标记
                    if row.get("primary_or_secondary") == "secondary" and any(cid in ("C-01","C-02","C-03") for cid in row.get("claim_ids") or []):
                        lim = " ".join(row.get("limitations") or [])
                        if "二手" not in lim and "转述" not in lim and "原文未取得" not in lim:
                            res.warn(f"{eid} 为 secondary 但支撑 C-01~03 总量判断，建议在 limitations 显式标记二手且未升级到 primary")
            # 来源天花板：对需要 primary 的命题，若仅有 secondary 则状态不得为 complete
            req_path = root / "evidence_requirements.json"
            if req_path.exists():
                try:
                    req_data = json.loads(req_path.read_text(encoding="utf-8"))
                    for req in req_data.get("requirements") or []:
                        if req.get("status") == "met" and req.get("requirement_id") in ("ER-01","ER-02","ER-03"):
                            eids = req.get("evidence_ids") or []
                            # 检查是否至少一个 primary
                            has_primary = False
                            lp = root / "evidence_ledger.jsonl"
                            if lp.exists():
                                ledger_map = {}
                                for line in lp.read_text(encoding="utf-8").splitlines():
                                    if not line.strip():
                                        continue
                                    try:
                                        r = json.loads(line)
                                        ledger_map[r.get("evidence_id")] = r
                                    except Exception:
                                        pass
                                for eid in eids:
                                    r = ledger_map.get(eid)
                                    if r and r.get("primary_or_secondary") == "primary":
                                        has_primary = True
                                        break
                            if not has_primary and eids:
                                res.warn(f"{req.get('requirement_id')} 标记 met 但所列证据无 primary（来源天花板未达）")
                except Exception:
                    pass
            # 独立性：统计 independence_group 去重率
            lp = root / "evidence_ledger.jsonl"
            if lp.exists():
                groups = set()
                total = 0
                for line in lp.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                        total += 1
                        groups.add(r.get("independence_group") or r.get("source_url"))
                    except Exception:
                        pass
                if total and len(groups) * 2 < total:
                    res.warn(f"独立性偏低: {total}行仅 {len(groups)} 个独立组（<50%），存在转载充数风险")
    except Exception as e:
        res.warn(f"确定性时序/天花板检查异常: {e}")
    _report(res, "design")
    return res

def _check_ledger_row(row, lineno, res):
    eid = row.get("evidence_id")
    required = [
        "claim_ids", "source_name", "publisher", "source_url", "published_at",
        "retrieved_at", "primary_or_secondary", "directness", "source_quality",
        "independence_group", "publisher_interest", "quotation_or_data",
        "supports_or_refutes", "limitations", "search_round",
    ]
    for key in required:
        value = row.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            res.err("台账 " + str(eid) + " 缺少字段 " + key)
    # search_round 硬校验：必须为 ≥1 的整数，预算闭环不可缺
    sr = row.get("search_round")
    if not isinstance(sr, int) or isinstance(sr, bool) or sr < 1:
        res.err("台账 " + str(eid) + " search_round 必须为 ≥1 的整数")
    claim_ids = row.get("claim_ids")
    if not isinstance(claim_ids, list) or not claim_ids or not all(isinstance(c, str) for c in claim_ids):
        res.err("台账 " + str(eid) + " claim_ids 必须是非空字符串数组")
    url = row.get("source_url")
    if isinstance(url, str) and url and not URL_RE.search(url):
        res.err("台账 " + str(eid) + " source_url 不是 http(s) 链接: " + url)
    for key in ("published_at", "retrieved_at"):
        value = row.get(key)
        if isinstance(value, str) and value and not DATE_RE.match(value):
            res.err("台账 " + str(eid) + " " + key + " 不是 YYYY-MM-DD: " + value)
    if row.get("primary_or_secondary") not in PRIMARY_ENUM:
        res.err("台账 " + str(eid) + " primary_or_secondary 非法")
    if row.get("directness") not in DIRECT_ENUM:
        res.err("台账 " + str(eid) + " directness 非法")
    quality = row.get("source_quality")
    if not isinstance(quality, (int, float)) or isinstance(quality, bool) or not (0 <= quality <= 1):
        res.err("台账 " + str(eid) + " source_quality 必须在 0-1")
    if row.get("publisher_interest") not in INTEREST_ENUM:
        res.err("台账 " + str(eid) + " publisher_interest 非法")
    if row.get("supports_or_refutes") not in SOR_ENUM:
        res.err("台账 " + str(eid) + " supports_or_refutes 非法")
    limits = row.get("limitations")
    if not isinstance(limits, list) or not limits or not all(isinstance(x, str) and x.strip() for x in limits):
        res.err("台账 " + str(eid) + " limitations 必须是非空字符串数组（写明该证据不能支持什么）")

def load_ledger(root, res):
    path = Path(root) / "evidence_ledger.jsonl"
    if not path.exists():
        res.err("缺失 evidence_ledger.jsonl")
        return {}
    rows = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            res.err("台账第 " + str(lineno) + " 行 JSON 解析失败: " + str(exc))
            continue
        eid = row.get("evidence_id")
        if not isinstance(eid, str) or not re.match("^E-[0-9][0-9]+$", eid):
            res.err("台账第 " + str(lineno) + " 行 evidence_id 非法: " + repr(eid))
            continue
        if eid in rows:
            res.err("台账 evidence_id 重复: " + eid)
        rows[eid] = row
        _check_ledger_row(row, lineno, res)
    return rows

def _parse_budget(text):
    m_max = re.search(r"^\s*max_search_rounds:\s*(\d+)\s*$", text, re.M)
    m_used = re.search(r"^\s*search_rounds_used:\s*(\d+)\s*$", text, re.M)
    max_r = int(m_max.group(1)) if m_max else None
    used_r = int(m_used.group(1)) if m_used else None
    return max_r, used_r


def _check_budget(brief_text, ledger, res):
    max_r, used_r = _parse_budget(brief_text)
    if max_r is None or used_r is None:
        return
    if used_r > max_r:
        res.err("brief search_rounds_used=" + str(used_r) + " 超过 max_search_rounds=" + str(max_r) + "（预算超支）")
    if not ledger:
        return
    ledger_rounds = [r.get("search_round", 1) for r in ledger.values() if isinstance(r.get("search_round"), int)]
    # 兼容未标 search_round 的旧台账，默认为 1
    if not ledger_rounds:
        ledger_rounds = [1]
    max_ledger = max(ledger_rounds)
    if max_ledger > max_r:
        res.err("台账最大 search_round=" + str(max_ledger) + " 超过 brief max_search_rounds=" + str(max_r) + "（预算硬上限被突破）")
    if used_r != max_ledger:
        res.warn("brief search_rounds_used=" + str(used_r) + " 与台账最大 search_round=" + str(max_ledger) + " 不一致（预算账本不同步，请以 ledger 为准同步 brief）")
    # 检查是否有跳号
    min_ledger = min(ledger_rounds) if ledger_rounds else 1
    if min_ledger != 1:
        res.warn("台账最小 search_round=" + str(min_ledger) + " 不是 1（首轮应为 1）")


def _check_independence_warnings(ledger, res):
    from urllib.parse import urlparse
    from collections import defaultdict
    domain_groups = defaultdict(set)
    domain_counts = defaultdict(int)
    domain_quality = defaultdict(list)
    domain_primary = defaultdict(list)
    for row in ledger.values():
        url = row.get("source_url") or ""
        try:
            netloc = urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            netloc = ""
        if not netloc:
            continue
        domain_counts[netloc] += 1
        domain_groups[netloc].add(row.get("independence_group") or "")
        domain_quality[netloc].append(row.get("source_quality", 0))
        domain_primary[netloc].append(row.get("primary_or_secondary"))
    for dom, groups in domain_groups.items():
        cnt = domain_counts[dom]
        if cnt >= 3 and len(groups) > 1:
            avg_q = sum(domain_quality[dom]) / len(domain_quality[dom]) if domain_quality[dom] else 0
            primaries = set(domain_primary[dom])
            is_official = avg_q >= 0.85 and "primary" in primaries
            is_gov_domain = dom.endswith(".gov") or dom.endswith(".gov.cn")
            if is_official or is_gov_domain:
                continue
            # 允许底层来源不同导致的分散（如 cnbc 转载 BofA 内容，独立组应为 BofA 而非 cnbc）
            # 若多组中包含明显不同的底层来源前缀（bofa/cboe/vix 等），视为合理分散
            underlying_prefixes = {"bofa", "cboe", "vix", "fed", "bls", "pboc", "nbs"}
            group_prefixes = set(g.split("-")[0].lower() for g in groups if g)
            if len(group_prefixes & underlying_prefixes) >= 1 and len(groups) <= 3:
                # 底层来源不同，独立组按来源归并是正确的，不告警
                continue
            res.warn("台账同域分散: " + dom + " 出现 " + str(cnt) + " 次却分散到 " + str(len(groups)) + " 个独立组 " + str(sorted(groups)) + "（聚合/转载站应整站归一组，请确认归并）")
    mixed_cnt = sum(1 for r in ledger.values() if r.get("publisher_interest") == "mixed")
    if mixed_cnt > 2:
        res.warn("publisher_interest=mixed 出现 " + str(mixed_cnt) + " 次（>2），建议收敛为 commercial/government/academic 等更具体类型）")


def _check_claim(item, ledger, res, light=False):
    cid = item.get("claim_id")
    text = item.get("claim")
    if not isinstance(text, str) or not text.strip():
        res.err(cid + ": claim 文本为空")
    elif "|" in text:
        res.err(cid + ": claim 文本含竖线（会破坏报告对照表解析）")
    if item.get("claim_type") not in CLAIM_TYPES:
        res.err(cid + ": claim_type 非法: " + repr(item.get("claim_type")))
    if not isinstance(item.get("is_critical"), bool):
        res.err(cid + ": is_critical 必须是布尔值")

    if light:
        # quick 档轻门禁：跳过 7 维公式与机器重算，只裁决等级、措辞、证据归属
        level = item.get("level")
        if level not in LEVEL_ORDER:
            res.err(cid + ": 非法等级 " + repr(level))
        if level != "no_standing":
            evids = item.get("evidence_ids") or []
            if not isinstance(evids, list) or not evids:
                res.err(cid + ": quick 档非 no_standing 主张的 evidence_ids 为空")
            for eid in evids:
                row = ledger.get(eid)
                if row is None:
                    res.err(cid + ": 引用了不存在的证据 " + eid)
                elif cid not in (row.get("claim_ids") or []):
                    res.err(cid + ": 证据 " + eid + " 的 claim_ids 不含本主张（归属错配）")
        wording = item.get("allowed_wording")
        if not isinstance(wording, str) or not wording.strip():
            res.err(cid + ": allowed_wording 为空")
            wording = ""
        if level != "confirmed" and _contains_definitive(wording) and not _has_closure(item):
            res.err(cid + ": " + level + " 措辞含确定性表达，但未带齐 前提+证伪信号+反证回应 闭环")
        counterpoints = item.get("counterpoints") or []
        resolutions = item.get("counterpoint_resolutions") or []
        if counterpoints and len(resolutions) != len(counterpoints):
            res.err(cid + ": counterpoint_resolutions 必须与 counterpoints 一一对应")
        return

    scores = item.get("scores")
    if not isinstance(scores, dict):
        res.err(cid + ": scores 缺失或非对象")
        return
    ctype = item.get("claim_type")
    is_predictive = ctype in ("predictive", "trend", "strategic", "causal")
    weights = WEIGHTS_PREDICTIVE if is_predictive else WEIGHTS

    missing = [k for k in weights if k not in scores]
    if missing:
        res.err(cid + ": 缺少评分维度 " + str(missing))
    for k in weights:
        v = scores.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
            res.err(cid + ": 评分 " + k + "=" + repr(v) + " 不在 0-100")

    penalties = item.get("penalties") or []
    if not isinstance(penalties, list):
        res.err(cid + ": penalties 不是数组")
        penalties = []
    penalty_sum = 0.0
    for p in penalties:
        if not isinstance(p, dict):
            res.err(cid + ": 惩罚条目非对象")
            continue
        pts = p.get("points")
        if not isinstance(pts, (int, float)) or isinstance(pts, bool) or pts < 0:
            res.err(cid + ": 非法惩罚点 " + repr(pts))
        if not isinstance(p.get("reason"), str) or not p["reason"].strip():
            res.err(cid + ": 惩罚缺少 reason")
        if isinstance(pts, (int, float)) and not isinstance(pts, bool):
            penalty_sum += pts

    bias = item.get("bias_penalties") or {}
    if not isinstance(bias, dict):
        res.err(cid + ": bias_penalties 不是对象")
        bias = {}
    bias_sum = 0.0
    for key in ("interest_bias", "search_ecology_bias"):
        value = bias.get(key, 0)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0 <= value <= 15):
            res.err(cid + ": 偏差扣分 " + key + "=" + repr(value) + " 不在 0-15")
        else:
            bias_sum += value

    recomputed = sum(weights[k] * (scores.get(k, 0) or 0) for k in weights) - penalty_sum - bias_sum
    recomputed = max(0.0, min(100.0, recomputed))
    declared = item.get("total")
    if not isinstance(declared, (int, float)) or isinstance(declared, bool):
        res.err(cid + ": total 缺失或非数值")
    elif abs(declared - recomputed) > 0.5:
        res.err(cid + ": total=" + repr(declared) + " 与机器重算 " + format(recomputed, ".2f") + " 不一致")

    raw_level = _level_for(recomputed, is_predictive=is_predictive)
    if item.get("raw_score_level") != raw_level:
        res.err(cid + ": raw_score_level=" + repr(item.get("raw_score_level")) + " 应为 " + raw_level)

    blocking = item.get("blocking_issues") or []
    if not isinstance(blocking, list):
        res.err(cid + ": blocking_issues 不是数组")
        blocking = []
    # v2.4: 闭环措辞提升可用性，但绝不能豁免证据或识别阻断项。
    expected = _step_down(raw_level) if blocking else raw_level
    level = item.get("level")
    if level != expected:
        res.err(cid + ": level=" + repr(level) + " 应为 " + expected + ("（存在阻断项，降一级）" if blocking and expected != raw_level else ""))
    if level not in LEVEL_ORDER:
        res.err(cid + ": 非法等级 " + repr(level))
        return

    evidence_level = item.get("evidence_level")
    identification_level = item.get("identification_level")
    dimension_status = item.get("dimension_status")
    unresolved = item.get("unresolved_requirements")
    if evidence_level not in LEVEL_ORDER:
        res.err(cid + ": evidence_level 非法: " + repr(evidence_level))
    if identification_level not in IDENTIFICATION_LEVELS:
        res.err(cid + ": identification_level 非法: " + repr(identification_level))
    if dimension_status not in DIMENSION_STATUSES:
        res.err(cid + ": dimension_status 非法: " + repr(dimension_status))
    if not isinstance(unresolved, list):
        res.err(cid + ": unresolved_requirements 必须是数组")
    if ctype == "causal" and not item.get("same_unit_observation", False):
        if identification_level not in {"descriptive", "correlational"}:
            res.err(cid + ": 因果主张缺少同分析单位 X/Y 观测，identification_level 上限为 correlational")
        if dimension_status == "complete":
            res.err(cid + ": 因果主张缺少同分析单位 X/Y 观测，不得标记 complete")
    if blocking and dimension_status == "complete":
        res.err(cid + ": 存在 blocking_issues 时 dimension_status 不得为 complete")

    wording = item.get("allowed_wording")
    if not isinstance(wording, str) or not wording.strip():
        res.err(cid + ": allowed_wording 为空")
        wording = ""

    if item.get("claim_type") == "trend":
        if LEVEL_ORDER[level] > LEVEL_ORDER["provisional"]:
            res.err(cid + ": trend 主张等级上限为 provisional")
        if not _has_conditional(wording):
            res.err(cid + ": trend 主张 allowed_wording 必须含条件词（若/如果/前提/取决于/条件/当…时）")

    uses_definitive = _contains_definitive(wording)
    if level != "confirmed" and uses_definitive and not _has_closure(item):
        res.err(cid + ": " + level + " 措辞含确定性表达，但未带齐 前提+证伪信号+反证回应 闭环")

    counterpoints = item.get("counterpoints") or []
    resolutions = item.get("counterpoint_resolutions") or []
    if not isinstance(counterpoints, list) or not isinstance(resolutions, list):
        res.err(cid + ": counterpoints / counterpoint_resolutions 必须是数组")
    else:
        if counterpoints and len(resolutions) != len(counterpoints):
            msg = (cid + ": counterpoint_resolutions(" + str(len(resolutions)) + ") 必须与 counterpoints("
                   + str(len(counterpoints)) + ") 一一对应")
            if uses_definitive:
                res.err(msg + "（明确表态必须回应全部反证）")
            else:
                res.warn(msg + "（建议补齐论证闭环）")
        for i, r in enumerate(resolutions, 1):
            if not isinstance(r, str) or len(r.strip()) < 10:
                res.err(cid + ": counterpoint_resolutions[" + str(i) + "] 过短（须解释结论为何在反证面前仍成立）")

    evids = item.get("evidence_ids") or []
    if not isinstance(evids, list):
        res.err(cid + ": evidence_ids 不是数组")
        evids = []
    if level != "no_standing" and not evids:
        res.err(cid + ": 非 no_standing 主张的 evidence_ids 为空")
    for eid in evids:
        row = ledger.get(eid)
        if row is None:
            res.err(cid + ": 引用了不存在的证据 " + eid)
        elif cid not in (row.get("claim_ids") or []):
            res.err(cid + ": 证据 " + eid + " 的 claim_ids 不含本主张（归属错配）")


def gate(root):
    res = Result()
    root = Path(root)
    brief_path = root / "research_brief.yaml"
    if not brief_path.exists():
        res.err("缺失 research_brief.yaml（立案产物）")
        brief_text = ""
    else:
        brief_text = brief_path.read_text(encoding="utf-8")
    _validate_design_contracts(root, brief_text, res, enforce_stop=True)
    light = _brief_depth(brief_text) == "quick"
    brief_claims = _parse_brief_claims(brief_text)
    if "claim_id:" in brief_text and not brief_claims:
        res.err("brief 含 claim_id 标记但解析不出任何主张——brief 格式与校验器不匹配（逐字比对被静默跳过前先修这里）")
    ledger = load_ledger(root, res)
    _check_budget(brief_text, ledger, res)
    _check_independence_warnings(ledger, res)
    auth = load_json(root / "claim_authorization.json", res)
    if auth is None:
        _report(res, "gate")
        return res
    claims = auth.get("claims")
    if auth.get("schema_version") != "2.4":
        res.err("claim_authorization.json schema_version 必须为 2.4")
    if not isinstance(claims, list) or not claims:
        res.err("claim_authorization.json 的 claims 必须是非空数组")
        _report(res, "gate")
        return res
    auth_by_id = {}
    seen = set()
    for item in claims:
        if not isinstance(item, dict):
            res.err("claims 含非对象条目")
            continue
        cid = item.get("claim_id")
        if not isinstance(cid, str) or not re.match("^C-[0-9][0-9]+$", cid):
            res.err("claim_id 非法: " + repr(cid))
            continue
        if cid in seen:
            res.err("claim_id 重复: " + cid)
        seen.add(cid)
        auth_by_id[cid] = item
        _check_claim(item, ledger, res, light=light)
    if brief_claims:
        for cid, text in brief_claims.items():
            item = auth_by_id.get(cid)
            if item is None:
                res.err("门禁未覆盖 brief 主张 " + cid + "（漏评）")
                continue
            if norm(item.get("claim") or "") != norm(text):
                res.err(cid + ": 授权书 claim 文本与 brief 不一致（必须逐字复制）")
    brief_meta = _parse_brief_meta(brief_text)
    if brief_claims or brief_meta:
        for cid in auth_by_id:
            if cid not in brief_meta and cid not in brief_claims:
                res.err("授权书含 brief 中不存在的多余主张: " + cid)
    for cid, meta in brief_meta.items():
        item = auth_by_id.get(cid)
        if item is None:
            continue
        if meta.get("claim_type") and item.get("claim_type") != meta["claim_type"]:
            res.err(cid + ": 授权书 claim_type " + repr(item.get("claim_type"))
                    + " 与 brief " + repr(meta["claim_type"]) + " 不一致（claim_type 以 brief 为准，不得被门禁覆盖）")
        if meta.get("is_critical") is not None and bool(item.get("is_critical")) != meta["is_critical"]:
            res.err(cid + ": 授权书 is_critical 与 brief 不一致（以 brief 为准）")
    for eid, row in ledger.items():
        for cid in row.get("claim_ids") or []:
            if cid not in auth_by_id:
                res.err("台账 " + eid + " 引用了门禁未覆盖的主张 " + cid + "（门禁漏评？）")
    # P1-B: 命题级独立性——同一 evidence_family 不得充数
    for cid, item in auth_by_id.items():
        eids = item.get("evidence_ids") or []
        if not eids:
            continue
        families = set()
        for eid in eids:
            row = ledger.get(eid)
            if row:
                families.add(row.get("evidence_family") or row.get("independence_group") or eid)
        if len(families) * 2 < len(eids):
            res.warn(f"{cid}: {len(eids)}条证据仅 {len(families)} 个独立 family（<50%），存在底层同源充数，置信度不得按源数叠加")
        # P1-C: 来源天花板——factual总量类需 primary+direct，causal需 same_unit
        ctype = item.get("claim_type")
        if ctype == "factual" and item.get("level") not in ("no_standing","weak_signal"):
            has_primary_direct = any((ledger.get(eid) or {}).get("primary_or_secondary")=="primary" and (ledger.get(eid) or {}).get("directness")=="direct" for eid in eids)
            if not has_primary_direct:
                res.warn(f"{cid}: factual主张在非 no_standing 级别下无 primary+direct 证据（来源天花板未达）")
        if ctype == "causal" and not item.get("same_unit_observation"):
            # 已在 gate_math 降级，此处仅提示
            if item.get("identification_level") == "causal":
                res.err(f"{cid}: causal主张 same_unit_observation=false 却标 causal（与门禁 identification_level 冲突）")
    _report(res, "gate")
    return res


def speak(root, report_file="final_report.md"):
    res = Result()
    root = Path(root)
    if (root / "research.json").exists():
        if report_file != "final_report.md":
            res.err("v3 review binds final_report.md; validate a separate investigation for variants")
        else:
            try:
                from tools.research import validate as validate_answer
            except ImportError:
                from research import validate as validate_answer
            errors, warnings = validate_answer(root)
            for message in errors: res.err(message)
            for message in warnings: res.warn(message)
        _report(res, "speak (v3 structure/provenance)")
        return res
    auth = load_json(root / "claim_authorization.json", res)
    if auth is None:
        _report(res, "speak")
        return res
    claims = auth.get("claims") or []
    contract = load_json(root / "report_contract.json", res)
    claim_map = load_json(root / "claim_source_map.json", res)
    manifest_rows = load_jsonl(root / "source_manifest.jsonl", res, "冻结来源清单")
    manifest = {}
    for row in manifest_rows:
        sid = row.get("source_id")
        if not isinstance(sid, str) or not re.match(r"^S-[0-9]{3,}$", sid):
            res.err("source_manifest source_id 非法: " + repr(sid))
            continue
        if sid in manifest:
            res.err("source_manifest source_id 重复: " + sid)
        manifest[sid] = row
        for key in ("title", "fetched_title", "publisher", "locator"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                res.err(sid + ": " + key + " 必须为非空字符串")
        if norm(row.get("title") or "") != norm(row.get("fetched_title") or ""):
            res.err(sid + ": 声明标题与采集时页面标题不匹配")
        url = row.get("canonical_url") or ""
        final_url = row.get("final_url") or ""
        try:
            parsed = urlparse(url)
            # 允许泰国签证官方门户的首页作为具体事实来源（其首页即签证主入口）
            allowed_homepages = {"ltr.boi.go.th", "www.thaievisa.go.th", "thaievisa.go.th"}
            if parsed.netloc.lower() in allowed_homepages and parsed.path in ("/", ""):
                pass
            elif not parsed.scheme.startswith("http") or parsed.path.lower() in ROOT_PATHS:
                res.err(sid + ": 禁止使用机构首页/频道根页作为具体事实来源: " + url)
        except Exception:
            res.err(sid + ": canonical_url 非法")
        if not final_url.startswith(("http://", "https://")):
            res.err(sid + ": final_url 非法")
        if not isinstance(row.get("access_status"), int) or not (200 <= row["access_status"] <= 399):
            res.err(sid + ": access_status 必须为 200..399")
        if not re.match(r"^sha256:[0-9a-f]{64}$", str(row.get("content_fingerprint") or "")):
            res.err(sid + ": content_fingerprint 必须为冻结的 sha256")
        if not _list_ok(row.get("supports")) or not _list_ok(row.get("evidence_ids")):
            res.err(sid + ": supports/evidence_ids 必须为非空数组")

    if not isinstance(contract, dict) or contract.get("schema_version") != "2.4":
        res.err("report_contract.json schema_version 必须为 2.4")
        sections = []
    else:
        sections = contract.get("sections") or []
        if contract.get("overall_status") not in FINAL_STATES:
            res.err("report_contract overall_status 非法")
        if not isinstance(sections, list) or not sections:
            res.err("report_contract sections 必须为非空数组")
            sections = []
    auth_ids = {x.get("claim_id") for x in claims if isinstance(x, dict)}
    covered_auth = set()
    natural = isinstance(contract, dict) and contract.get("presentation") == "natural"
    for section in sections:
        for key in (("heading", "judgment", "evidence_or_table") if natural else ("heading", "judgment", "evidence_or_table", "mechanism", "strongest_alternative", "falsification_signal")):
            if not isinstance(section.get(key), str) or not section[key].strip():
                res.err(str(section.get("question_id")) + ": report contract 缺 " + key)
        cids = set(section.get("authorized_claim_ids") or [])
        covered_auth.update(cids)
        if not cids or not cids.issubset(auth_ids):
            res.err(str(section.get("question_id")) + ": authorized_claim_ids 缺失或引用未知主张")
        for sid in section.get("source_ids") or []:
            if sid not in manifest:
                res.err(str(section.get("question_id")) + ": 引用 source_manifest 不存在的 " + str(sid))
    if auth_ids - covered_auth:
        res.err("report_contract 未覆盖授权主张: " + str(sorted(auth_ids - covered_auth)))
    if not isinstance(claim_map, dict) or claim_map.get("schema_version") != "2.4":
        res.err("claim_source_map.json schema_version 必须为 2.4")
    else:
        mapped = claim_map.get("claims") or []
        if not isinstance(mapped, list) or not mapped:
            res.err("claim_source_map claims 必须为非空数组")
        for entry in mapped:
            if not isinstance(entry.get("report_claim"), str) or not entry["report_claim"].strip():
                res.err("claim_source_map report_claim 为空")
            if not isinstance(entry.get("locator"), str) or not entry["locator"].strip():
                res.err("claim_source_map locator 为空")
            for sid in entry.get("source_ids") or []:
                if sid not in manifest:
                    res.err("claim_source_map 引用不存在的 " + str(sid))
    auth_by_norm = {}
    for item in claims:
        text = item.get("claim")
        if isinstance(text, str) and text.strip():
            auth_by_norm[norm(text)] = item

    # 支持 --file 指定具体报告（brief/detailed/both），默认 final_report.md 以兼容存量
    path = root / report_file
    if not path.exists():
        res.err(f"缺失 {report_file}（speak 校验目标不存在；可用 --file 指定 final_report_brief.md / final_report_full.md）")
        _report(res, "speak")
        return res
    lines = path.read_text(encoding="utf-8").splitlines()
    body = '\n'.join(lines)
    if not body.strip() or (not natural and len(body) < 400):
        res.err("final_report.md 过短，不像完整报告")

    if not natural and SUMMARY_MARK not in body:
        res.err("缺少执行摘要章节")
    # 0) 合成推演硬前置：final_report.md 之前必须已完成 synthesis.md（quick 档也至少需 1图1表）
    syn_path = root / "synthesis.md"
    if not syn_path.exists():
        res.err("缺少 synthesis.md（合成推演为人读报告硬前置；须先完成 synthesis 阶段，quick 档至少需 1图1表的 synthesis.md）")
    else:
        try:
            syn_text = syn_path.read_text(encoding="utf-8")
            if len(syn_text.strip()) < 50:
                res.err("synthesis.md 过短，不像有效合成推演（quick 档至少需 1图1表）")
        except Exception:
            res.err("synthesis.md 读取失败")
    # 纯净交付版：发言权对照表、覆盖与不确定、状态行、流程说明已沉底到内部审计文件，不应在交付版出现（硬拦截）
    if APPENDIX_MARK in body:
        res.err("交付版不应包含发言权对照表（审计信息已沉底到 claim_authorization.json/synthesis.md）")
    if "从暂无发言权到可行动" in body:
        res.err("交付版不应包含“从暂无发言权到可行动”章节（审计信息已沉底）")
    if "流程说明" in body:
        res.err("交付版不应包含流程说明章节（审计信息已沉底）")
    if not natural and REF_MARK not in body:
        res.err("缺少参考资料章节")
    depth = _brief_depth((root / "research_brief.yaml").read_text(encoding="utf-8"))         if (root / "research_brief.yaml").exists() else "standard"
    if not natural and depth != "quick":
        if not any(re.search("^#+.*" + w, line) for line in lines for w in FORWARD_WORDS):
            res.err("缺少前瞻章（标题需含 接下来/前瞻/行动/该怎么做 之意）")
    elif not natural:
        res.warn("quick 档不强制前瞻章（如给前瞻判断，请保持条件式表达）")

    body_pre_ref = body.split(REF_MARK, 1)[0] if REF_MARK in body else body
    if CID_RE.search(body_pre_ref):
        res.err("正文出现机器编号 C-xx/E-xx/S-xx（参考资料前的正文与表格均禁止暴露内部编号，请替换为标准机构简称）")
    if MATERIAL_RE.search(body):
        res.err("报告出现 资料一/资料二 式机器编号")
    if PIPELINE_JARGON_RE.search(body):
        res.err("正文出现后台流水线过程套话（如「先说分析框架/合成推演阶段/主链一句/我们怎么推到这个结论」），请改为连贯自然的行业分析叙事")
    if re.search(r"（[^（）]*（", body):
        res.warn("正文出现嵌套括号（如「X（X）」），疑似模板残留，请人工检查")
    # === 纯净交付版：状态与覆盖已沉底，不应在交付版出现（硬拦截） ===
    if "状态：" in body or "Status:" in body:
        res.err("交付版不应包含状态行（审计信息已沉底，交付版只留结论与推演）")
    # 2) 执行摘要首段 2-4 句直答
    if not natural and SUMMARY_MARK in body:
        try:
            summary_part = body.split(SUMMARY_MARK, 1)[1].split("##", 1)[0]
            # 取摘要首段（去空行后的第一段）
            paras = [p.strip() for p in summary_part.strip().split("\n\n") if p.strip() and not p.strip().startswith("|") and not p.strip().startswith("#")]
            first_para = paras[0] if paras else ""
            # 粗略按句号/问号/感号计数
            sent_cnt = len([s for s in re.split(r"[。！？.!?]+", first_para) if s.strip()])
            if first_para and (sent_cnt < 2 or sent_cnt > 4):
                res.warn("执行摘要首段建议 2-4 句人话直答（当前约 " + str(sent_cnt) + " 句），随后给不确定性")
        except Exception:
            pass
    # 3) 覆盖与不确定已沉底，交付版出现即硬拦截
    if "覆盖与不确定" in body or "Coverage and uncertainty" in body:
        res.err("交付版不应包含覆盖与不确定章节（已沉底到内部审计）")
    pre_appendix_raw = body.split(APPENDIX_MARK, 1)[0] if APPENDIX_MARK in body else body
    if not natural and re.search(r"^##\s*Sources|^##\s*References", pre_appendix_raw, re.M):
        res.err("正文（对照表前）出现 ## Sources/References 标题（该节由参考资料统一承载）")
    # 5) 禁止逐源复述：检测 甲说乙说丙称 的堆砌
    if re.search(r"(称|表示|指出|认为).{0,20}(称|表示|指出|认为).{0,20}(称|表示|指出|认为)", pre_appendix_raw):
        res.warn("疑似逐源复述（连续出现多处 称/表示/指出/认为），建议改为综合句+句尾编号")
    # 6) 紧凑表纪律：若正文含多个同类数值但无表，给提示
    has_table_before_appendix = bool(re.search(r"^\|.*\|", pre_appendix_raw, re.M))
    numeric_hits = len(re.findall(r"\d+\.?\d*\s*%|\d{4}年|\d+月|\d+\s*美元|\d+\s*bp", pre_appendix_raw))
    if not natural and numeric_hits >= 6 and not has_table_before_appendix:
        res.warn("正文含较多数值（≥6 处）但未见紧凑表，建议将按日/按月系列收进一张表")
    rows = []
    in_table = False
    for line in lines:
        if APPENDIX_MARK in line:
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 3 and cells[0] and cells[0] != "主张" and not set(cells[0]) <= {"-", ":"}:
                    rows.append(cells)
            elif line.strip().startswith("#") or line.strip():
                in_table = False
    if APPENDIX_MARK in body:
        # 纯净交付版已在上方硬拦截，此处仅为兼容旧报告的详细校验：若仍含表则逐行核对
        if not rows:
            res.err("发言权对照表未解析到任何数据行")

        table_texts = set()
        for cells in rows:
            if len(cells) < 3:
                res.err("对照表行缺少列: " + "|".join(cells))
                continue
            claim_text, label, sources = cells[0], cells[1], cells[2]
            item = auth_by_norm.get(norm(claim_text))
            if item is None:
                res.err("对照表含授权文件中不存在的主张: " + claim_text[:40])
                continue
            table_texts.add(norm(claim_text))
            expected_label = LEVEL_LABELS.get(item.get("level"))
            if label != expected_label:
                res.err("对照表主张 " + item.get("claim_id") + " 的发言权标签为 " + repr(label)
                        + "，应为 " + repr(expected_label))
            if not sources:
                res.err("对照表主张 " + item.get("claim_id") + " 缺少关键来源")
            level = item.get("level")
            if level != "confirmed" and _contains_definitive(claim_text) and not _has_closure(item):
                res.err("对照表主张 " + item.get("claim_id") + " 为 " + level
                        + " 且含确定性表达，但授权文件未带齐 前提+证伪信号+反证回应 闭环")

        for ntext, item in auth_by_norm.items():
            if ntext not in table_texts:
                res.err("对照表遗漏授权主张 " + item.get("claim_id") + ": " + item.get("claim", "")[:40])
    else:
        # 纯净交付版：正文不附发言权对照表为预期，不再警告
        pass
    has_confirmed = any(item.get("level") == "confirmed" for item in claims)
    has_closure = any(_has_closure(item) for item in claims)
    pre_appendix = body.split(APPENDIX_MARK, 1)[0]
    if _contains_definitive(pre_appendix):
        if not has_confirmed and not has_closure:
            res.err("正文使用确定性表达，但不存在 confirmed 主张、也没有带闭环（前提+证伪信号+反证回应）的授权主张")
        else:
            res.warn("正文含确定性表达，请人工确认其所属主张确有对应授权（confirmed 或带闭环）")
    # P0-1/P0-2: 命题级语义许可与句级蕴含（v2.5）
    lex_path = root / "claim_semantic_lexicon.json"
    if lex_path.exists():
        try:
            lex_data = json.loads(lex_path.read_text(encoding="utf-8"))
            for entry in lex_data.get("lexicon") or []:
                cid = entry.get("claim_id")
                for pat in entry.get("forbidden_patterns") or []:
                    try:
                        if re.search(pat, pre_appendix):
                            allowed = (entry.get("allowed_templates") or ["暂无发言权"])[0]
                            res.err(f"句级蕴含越权: {cid} 为 {entry.get('level')}/{entry.get('dimension_status')} 不允许出现 “{pat}” 的语义（需改写为 “{allowed}” 类表述）")
                    except re.error:
                        if pat in pre_appendix:
                            res.err(f"句级蕴含越权: {cid} 禁用词 “{pat}” 出现在正文")
        except Exception as e:
            res.err(f"claim_semantic_lexicon.json 解析失败: {e}")
    else:
        # 向后兼容：旧调查未生成 lexicon 仅警告，不阻断
        res.warn("缺失 claim_semantic_lexicon.json（v2.5 起 Writer 硬约束所需，旧调查可忽略）")
    seen_urls = set()
    ref_text = body if natural else body.partition(REF_MARK)[2]
    for m in URL_EXTRACT_RE.finditer(ref_text):
        url = m.group(0).rstrip("。，、；：)）]】〉》-")
        if not natural and url in seen_urls:
            res.err("参考资料出现重复来源链接: " + url)
        seen_urls.add(url)
    if not seen_urls:
        res.err("报告中未找到来源链接" if natural else "参考资料部分未找到任何链接")
    manifest_urls = {row.get("canonical_url") for row in manifest_rows}
    for url in seen_urls:
        if url not in manifest_urls:
            res.err("参考资料链接未进入冻结 source_manifest: " + url)

    _report(res, "speak")
    return res
def synthesis(root):
    """v2.4 最终合成校验：所有结构与识别错误均为硬错误。"""
    res = Result()
    root = Path(root)
    path = root / "final_synthesis.json"
    brief_text = (root / "research_brief.yaml").read_text(encoding="utf-8") if (root / "research_brief.yaml").exists() else ""
    depth = _brief_depth(brief_text)
    provisional_path = root / "provisional_synthesis.json"
    if not provisional_path.exists():
        res.err("缺少 provisional_synthesis.json（调查中段合成与回流检查）")
    if not path.exists():
        res.err("缺少 final_synthesis.json（双门禁后的冻结合成）")
        _report(res, "synthesis")
        return res
    data = load_json(path, res)
    if data is None:
        _report(res, "synthesis")
        return res
    # 基础结构检查；函数末尾会把所有警告升级为硬错误。
    if data.get("schema_version") != "1.0":
        res.warn("synthesis.json schema_version 应为 \"1.0\"，当前为 " + repr(data.get("schema_version")))
    if not isinstance(data.get("investigation"), str) or not data.get("investigation"):
        res.warn("synthesis.json investigation 必须为非空字符串")
    ca = data.get("created_at")
    if not isinstance(ca, str) or not DATE_RE.match(ca):
        res.warn("synthesis.json created_at 必须为 YYYY-MM-DD，当前为 " + repr(ca))
    chains = data.get("causal_chains")
    if not isinstance(chains, list) or not chains:
        res.warn("synthesis.json causal_chains 必须为非空数组（1..3条）")
        chains = []
    if isinstance(chains, list) and len(chains) > 3:
        res.warn("synthesis.json causal_chains 超过 3 条上限（当前 " + str(len(chains)) + " 条）")
    # 加载 ledger 用于 evidence_ids 引用检查
    ledger = {}
    ledger_path = root / "evidence_ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if not line:
                continue
            try:
                row=json.loads(line)
                eid=row.get("evidence_id")
                if isinstance(eid, str):
                    ledger[eid]=row
            except Exception:
                pass
    else:
        res.warn("synthesis 校验时未找到 evidence_ledger.jsonl，无法核对 evidence_ids")
    for ch in chains:
        if not isinstance(ch, dict):
            res.warn("causal_chains 含非对象条目")
            continue
        cid = ch.get("id")
        if not isinstance(cid, str) or not re.match(r"^CM-[0-9]{2}$", cid):
            res.warn("causal_chains id 非法: " + repr(cid) + "（应为 CM-01 格式）")
        mc = ch.get("mechanism_chain")
        if not isinstance(mc, list) or len(mc) < 2 or len(mc) > 5:
            res.warn(cid + ": mechanism_chain 必须为 2..5 环字符串数组")
        else:
            for x in mc:
                if not isinstance(x, str) or not x.strip():
                    res.warn(cid + ": mechanism_chain 含空字符串")
        tp = ch.get("testable_predictions")
        if not isinstance(tp, list) or not (1 <= len(tp) <= 3):
            res.warn(cid + ": testable_predictions 必须为 1..3 条非空字符串数组")
        eids = ch.get("evidence_ids") or []
        if not isinstance(eids, list) or not eids:
            res.warn(cid + ": evidence_ids 必须为非空数组")
        else:
            for eid in eids:
                if not isinstance(eid, str) or not re.match(r"^E-[0-9]{2,}$", eid):
                    res.warn(cid + ": evidence_ids 含非法 E-ID: " + repr(eid))
                elif eid not in ledger:
                    res.warn(cid + ": evidence_ids 引用了台账不存在的证据 " + eid)
        cc = ch.get("confidence_ceiling")
        if cc not in ("correlational", "mechanistic", "causal"):
            res.warn(cid + ": confidence_ceiling 必须为 correlational|mechanistic|causal，当前为 " + repr(cc))
        if not ch.get("cause") or not ch.get("effect"):
            res.warn(cid + ": cause/effect 必须为非空字符串")
        if not isinstance(ch.get("alternative_explanations"), list) or not ch.get("alternative_explanations"):
            res.warn(cid + ": alternative_explanations 必须为非空数组")
        if not isinstance(ch.get("counterfactual"), str) or not ch.get("counterfactual").strip():
            res.warn(cid + ": counterfactual 必须为非空字符串")
    eg = data.get("evidence_graph")
    if not isinstance(eg, dict):
        res.warn("evidence_graph 必须为对象（含 backbone/nodes/edges）")
    else:
        if not isinstance(eg.get("backbone"), str) or not eg.get("backbone").strip():
            res.warn("evidence_graph.backbone 必须为非空字符串")
        if not isinstance(eg.get("nodes"), list):
            res.warn("evidence_graph.nodes 必须为数组（C-xx）")
        if not isinstance(eg.get("edges"), list):
            res.warn("evidence_graph.edges 必须为数组")
    assumps = data.get("assumptions")
    if not isinstance(assumps, list) or not assumps:
        res.warn("assumptions 必须为非空数组（1..5条）")
    elif len(assumps) > 5:
        res.warn("assumptions 超过 5 条上限（当前 " + str(len(assumps)) + " 条）")
    else:
        for a in assumps:
            if not isinstance(a, dict):
                res.warn("assumptions 含非对象条目")
                continue
            aid = a.get("id")
            if not isinstance(aid, str) or not re.match(r"^A-[0-9]{2}$", aid):
                res.warn("assumptions id 非法: " + repr(aid) + "（应为 A-01）")
            if not isinstance(a.get("statement"), str) or not a.get("statement").strip():
                res.warn(str(aid) + ": statement 必须为非空字符串")
            if not isinstance(a.get("falsification_signals"), list) or not a.get("falsification_signals"):
                res.warn(str(aid) + ": falsification_signals 必须为非空数组")
            if not isinstance(a.get("affects_claims"), list) or not a.get("affects_claims"):
                res.warn(str(aid) + ": affects_claims 必须为非空数组（C-xx）")
    steps = data.get("inference_steps")
    if not isinstance(steps, list) or not steps:
        res.warn("inference_steps 必须为非空数组")
    else:
        for s in steps:
            if not isinstance(s, dict):
                res.warn("inference_steps 含非对象条目")
                continue
            if not isinstance(s.get("step"), int) or s.get("step") < 1:
                res.warn("inference_steps step 必须为 ≥1 的整数")
            if not isinstance(s.get("claim_ids"), list) or not s.get("claim_ids"):
                res.warn("inference_steps claim_ids 必须为非空数组")
            if not isinstance(s.get("logic"), str) or not s.get("logic").strip():
                res.warn("inference_steps logic 必须为非空字符串")
            grounds = s.get("grounds") or []
            if not isinstance(grounds, list) or not grounds:
                res.warn("inference_steps grounds 必须为非空数组（E-xx/A-xx）")
            else:
                for g in grounds:
                    if not isinstance(g, str) or not re.match(r"^(E-[0-9]{2,}|A-[0-9]{2})$", g):
                        res.warn("inference_steps grounds 含非法引用: " + repr(g))
                    elif g.startswith("E-") and g not in ledger:
                        res.warn("inference_steps grounds 引用了不存在的证据 " + g)
    if res.warnings:
        res.errors.extend("硬合成校验: " + msg for msg in res.warnings)
    _report(res, "synthesis")
    return res


def _report(res, what):
    print("")
    print("== " + what + " 校验完成: " + str(len(res.errors)) + " 错误, " + str(len(res.warnings)) + " 警告 ==")
    print("结果: [FAIL]" if res.errors else "结果: [PASS]")

def main():
    parser = argparse.ArgumentParser(description="deep-research v2.4.0 机器裁决")
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design", help="研究设计、证据需求与缺口契约裁决")
    p_design.add_argument("investigation_dir")
    p_gate = sub.add_parser("gate", help="门禁裁决：重算授权评分与措辞纪律（含 E-ID 连续性与 search_round）")
    p_gate.add_argument("investigation_dir")
    p_speak = sub.add_parser("speak", help="发言裁决：纯净交付版校验（synthesis 前置与审计沉底，支持 --file 指定报告）")
    p_speak.add_argument("investigation_dir")
    p_speak.add_argument("--file", dest="report_file", default="final_report.md", help="报告文件名（默认 final_report.md；both 时可用 final_report_brief.md / final_report_full.md）")
    p_syn = sub.add_parser("synthesis", help="合成推演校验：引用合法性与 schema（standard/deep 缺失为硬错误）")
    p_syn.add_argument("investigation_dir")
    args = parser.parse_args()
    if args.command == "design":
        res = design(args.investigation_dir)
    elif args.command == "gate":
        res = gate(args.investigation_dir)
    elif args.command == "speak":
        res = speak(args.investigation_dir, report_file=getattr(args, "report_file", "final_report.md"))
    else:
        res = synthesis(args.investigation_dir)
    sys.exit(1 if res.errors else 0)


if __name__ == "__main__":
    main()
