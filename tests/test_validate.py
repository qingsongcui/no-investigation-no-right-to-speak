"""deep-research v2.4.0 校验器回归测试。

运行：
  python3 tests/test_validate.py
或
  python3 -m unittest tests.test_validate
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "tools" / "validate.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid"


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        shutil.copytree(FIXTURE, self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def run_validator(self, cmd):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), cmd, str(self.dir)],
            capture_output=True, text=True, cwd=str(REPO),
        )

    def load_auth(self):
        path = self.dir / "claim_authorization.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def save_auth(self, auth):
        path = self.dir / "claim_authorization.json"
        path.write_text(json.dumps(auth, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_gate_passes(self):
        r = self.run_validator("gate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[PASS]", r.stdout)

    def test_speak_passes(self):
        r = self.run_validator("speak")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[PASS]", r.stdout)

    def test_gate_rejects_tampered_total(self):
        auth = self.load_auth()
        auth["claims"][0]["total"] = 90
        self.save_auth(auth)
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[FAIL]", r.stdout)

    def test_gate_rejects_definitive_without_closure(self):
        auth = self.load_auth()
        auth["claims"][0]["allowed_wording"] = "现有证据表明，增速确定处于 6% 以上。"
        self.save_auth(auth)
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[FAIL]", r.stdout)

    def test_gate_rejects_trend_without_condition_word(self):
        auth = self.load_auth()
        auth["claims"][1]["allowed_wording"] = "未来一年该省工业增速大概率维持在 5% 至 7% 区间。"
        self.save_auth(auth)
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[FAIL]", r.stdout)

    def test_gate_rejects_orphan_ledger_claim(self):
        path = self.dir / "evidence_ledger.jsonl"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"C-02"', '"C-99"', 1), encoding="utf-8")
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[FAIL]", r.stdout)

    def test_speak_rejects_missing_row(self):
        # 纯净版：正文不应包含发言权对照表，任何表格出现即硬拦截（旧“遗漏”场景已沉底）
        report_path = self.dir / "final_report.md"
        report = report_path.read_text(encoding="utf-8")
        injected = report + "\n## 发言权对照表\n\n| 主张 | 发言权 | 关键来源 |\n|---|---|---|\n| 2025 年，某省规模以上工业增加值同比增长 6.5%。 | 暂定 | 国家统计局 |\n"
        report_path.write_text(injected, encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不应包含发言权对照表", r.stdout)

    def test_speak_rejects_machine_id(self):
        report_path = self.dir / "final_report.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(report.replace("## 执行摘要", "## 执行摘要（对应 C-01）"), encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[FAIL]", r.stdout)
    def test_speak_rejects_pipeline_jargon(self):
        report_path = self.dir / "final_report.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(report.replace("## 增速的成色", "## 我们怎么推到这个结论\n先说分析框架再上事实。"), encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("过程套话", r.stdout)

    def test_speak_rejects_duplicate_url(self):
        report_path = self.dir / "final_report.md"
        report = report_path.read_text(encoding="utf-8")
        report_path.write_text(report + "\n- 重复来源：https://www.example.gov.cn/stats/2026-02.html\n", encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("重复", r.stdout)
    def test_speak_rejects_wrong_label(self):
        # 纯净版硬拦截：错误标签的表格同样先触发“不应包含”硬拦截，旧标签校验仍保留
        report_path = self.dir / "final_report.md"
        report = report_path.read_text(encoding="utf-8")
        injected = report + "\n## 发言权对照表\n\n| 主张 | 发言权 | 关键来源 |\n|---|---|---|\n| 2025 年，某省规模以上工业增加值同比增长 6.5%。 | 已确认 | 国家统计局 |\n"
        report_path.write_text(injected, encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不应包含发言权对照表", r.stdout)
    def test_predictive_closure_does_not_exempt_blocking_downgrade(self):
        auth = self.load_auth()
        for c in auth["claims"]:
            if c["claim_id"] == "C-02":
                c["claim_type"] = "trend"
                c["blocking_issues"] = ["存在替代解释需情景观察"]
                # v2.4: closure cannot exempt a blocker; keeping provisional must fail.
                c["level"] = "provisional"
        self.save_auth(auth)
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("存在阻断项，降一级", r.stdout)

    def test_factual_blocking_still_downgrades(self):
        auth = self.load_auth()
        for c in auth["claims"]:
            if c["claim_id"] == "C-01":
                c["blocking_issues"] = ["关键一手证据缺失"]
                # C-01 is factual, raw is provisional, but level is not stepped down
                c["level"] = "provisional"
        self.save_auth(auth)
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("存在阻断项，降一级", r.stdout)
class QuickTierTests(unittest.TestCase):
    """quick 档轻门禁端到端：gate_math.py 轻分支 + validate.py gate 不跑 7 维公式。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        (self.dir / "evidence_collection").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_validator(self, cmd):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), cmd, str(self.dir)],
            capture_output=True, text=True, cwd=str(REPO),
        )

    def write_files(self):
        brief = """slug: demo-quick
workflow_version: "2.4"
state: IDENTIFICATION_GATED
stakes: low
depth: quick
claims:
  - claim_id: C-01
    claim: "该市夏季用电缺口是否存在。"
    claim_type: factual
    is_critical: false
  - claim_id: C-02
    claim: "该市电网改造未来半年进度将（以调查结果为准）。"
    claim_type: trend
    is_critical: true
"""
        (self.dir / "research_brief.yaml").write_text(brief, encoding="utf-8")
        design = {"schema_version":"2.4","investigation":"demo-quick","questions":[
            {"question_id":"RQ-01","question":"用电缺口","research_type":"descriptive","claim_ids":["C-01"],"outcome_variable":"缺口","exposure_variable":"","unit_of_analysis":"城市","time_granularity":"月度","population":"城市电网","required_data":["负荷公告"],"acceptable_proxies":[],"unacceptable_substitutes":["评论"],"confounders":[],"identification_strategy":"公告核验","feasible":True,"fallback_type":"none"},
            {"question_id":"RQ-02","question":"改造进度","research_type":"predictive","claim_ids":["C-02"],"outcome_variable":"进度","exposure_variable":"批复","unit_of_analysis":"项目","time_granularity":"半年","population":"电网项目","required_data":["批复"],"acceptable_proxies":[],"unacceptable_substitutes":["评论"],"confounders":[],"identification_strategy":"条件推演","feasible":True,"fallback_type":"none"}]}
        (self.dir / "research_design.json").write_text(json.dumps(design, ensure_ascii=False), encoding="utf-8")
        reqs = {"schema_version":"2.4","investigation":"demo-quick","requirements":[
            {"requirement_id":"ER-01","question_ids":["RQ-01"],"claim_ids":["C-01"],"evidence_type":"numeric","description":"负荷","critical":True,"minimum_acceptance":"公告","status":"met","evidence_ids":["E-001"],"information_gain":{}},
            {"requirement_id":"ER-02","question_ids":["RQ-02"],"claim_ids":["C-02"],"evidence_type":"mechanism","description":"批复","critical":True,"minimum_acceptance":"批复","status":"met","evidence_ids":["E-002"],"information_gain":{}}]}
        (self.dir / "evidence_requirements.json").write_text(json.dumps(reqs, ensure_ascii=False), encoding="utf-8")
        (self.dir / "gap_register.json").write_text(json.dumps({"schema_version":"2.4","investigation":"demo-quick","gaps":[]}, ensure_ascii=False), encoding="utf-8")
        ledger = [
            {"evidence_id": "E-001", "claim_ids": ["C-01"], "source_name": "供电局公告",
             "publisher": "市供电局", "source_url": "https://example.gov.cn/gongdian/1",
             "published_at": "2026-08-01", "retrieved_at": "2026-08-14",
             "primary_or_secondary": "primary", "directness": "direct", "source_quality": 0.9,
             "independence_group": "gongdian-1", "publisher_interest": "government",
             "quotation_or_data": "7 月最大负荷创历史新高。", "supports_or_refutes": "supports",
             "limitations": ["单一城市单月数据"], "search_round": 1},
            {"evidence_id": "E-002", "claim_ids": ["C-02"], "source_name": "发改委批复",
             "publisher": "市发改委", "source_url": "https://example.gov.cn/fgw/2",
             "published_at": "2026-08-05", "retrieved_at": "2026-08-14",
             "primary_or_secondary": "primary", "directness": "direct", "source_quality": 0.9,
             "independence_group": "fgw-2", "publisher_interest": "government",
             "quotation_or_data": "电网改造工程获批，计划 6 个月内完成 60%。", "supports_or_refutes": "supports",
             "limitations": ["计划进度非实际进度"], "search_round": 1},
        ]
        with open(self.dir / "evidence_ledger.jsonl", "w", encoding="utf-8") as fh:
            for row in ledger:
                fh.write(json.dumps(row, ensure_ascii=False) + chr(10))
        gate_scores = {
            "ledger_selfcheck": {"rows_read": 2, "eid_first": "E-001", "eid_last": "E-002",
                                 "claims_covered": ["C-01", "C-02"]},
            "claims": [
                {"claim_id": "C-01", "level": "hypothesis",
                 "allowed_wording": "现有数据表明该市夏季存在用电缺口。",
                 "evidence_ids": ["E-001"], "premises": [], "falsification_signals": [],
                 "counterpoints": [], "counterpoint_resolutions": []},
                {"claim_id": "C-02", "level": "weak_signal",
                 "allowed_wording": "若批复工程按计划推进，电网改造进度未来半年或达六成。",
                 "evidence_ids": ["E-002"], "premises": [], "falsification_signals": [],
                 "counterpoints": [], "counterpoint_resolutions": []},
            ],
        }
        (self.dir / "evidence_gate_scores.json").write_text(json.dumps(gate_scores, ensure_ascii=False), encoding="utf-8")
        identification = {"ledger_selfcheck": gate_scores["ledger_selfcheck"], "claims": [
            {"claim_id":"C-01","identification_level":"descriptive","dimension_status":"complete","same_unit_observation":False,"unresolved_requirements":[],"blocking_issues":[]},
            {"claim_id":"C-02","identification_level":"mechanistic","dimension_status":"complete","same_unit_observation":True,"unresolved_requirements":[],"blocking_issues":[]}
        ]}
        (self.dir / "identification_gate_scores.json").write_text(json.dumps(identification, ensure_ascii=False), encoding="utf-8")

    def run_gate_math(self):
        return subprocess.run(
            [sys.executable, str(REPO / "tools" / "gate_math.py"), str(self.dir)],
            capture_output=True, text=True, cwd=str(REPO),
        )

    def test_quick_light_gate_end_to_end(self):
        self.write_files()
        r = self.run_gate_math()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("quick 轻门禁", r.stdout)
        auth = json.loads((self.dir / "claim_authorization.json").read_text(encoding="utf-8"))
        self.assertEqual(auth["claims"][0]["level"], "hypothesis")
        self.assertNotIn("scores", auth["claims"][0])
        r2 = self.run_validator("gate")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("[PASS]", r2.stdout)

    def test_quick_missing_selfcheck_rejected(self):
        self.write_files()
        gate = json.loads((self.dir / "evidence_gate_scores.json").read_text(encoding="utf-8"))
        del gate["ledger_selfcheck"]
        (self.dir / "evidence_gate_scores.json").write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
        r = self.run_gate_math()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ledger_selfcheck", r.stdout)

    def test_quick_claim_type_from_brief(self):
        self.write_files()
        r = self.run_gate_math()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        auth = json.loads((self.dir / "claim_authorization.json").read_text(encoding="utf-8"))
        types = {c["claim_id"]: c["claim_type"] for c in auth["claims"]}
        self.assertEqual(types["C-01"], "factual")
        self.assertEqual(types["C-02"], "trend")

class GrokOptimizationsTests(unittest.TestCase):
    """测试 Grok 优化项：双向严格主张比对、哈希流水账断点续跑等。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        shutil.copytree(FIXTURE, self.dir)
        brief = """slug: demo-province-industry
workflow_version: "2.4"
state: IDENTIFICATION_GATED
claims:
  - claim_id: C-01
    claim: "2025 年，某省规模以上工业增加值同比增长 6.5%。"
    claim_type: factual
    is_critical: true
  - claim_id: C-02
    claim: "若出口需求保持当前水平，未来一年该省工业增速将大概率维持在 5% 至 7% 区间。"
    claim_type: trend
    is_critical: true
  - claim_id: C-03
    claim: "该省未来三年产业升级的具体路径已经明确。"
    claim_type: factual
    is_critical: false
"""
        (self.dir / "research_brief.yaml").write_text(brief, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
    def test_gate_math_rejects_duplicate_claim_id(self):
        gate = {
            "ledger_selfcheck": {"rows_read": 2, "eid_first": "E-01", "eid_last": "E-02",
                                 "claims_covered": ["C-01", "C-02", "C-03"]},
            "claims": [
                {"claim_id": "C-01", "scores": {"Q": 85, "D": 80, "I": 70, "C": 75, "R": 85, "X": 70, "P": 60}},
                {"claim_id": "C-01", "scores": {"Q": 85, "D": 80, "I": 70, "C": 75, "R": 85, "X": 70, "P": 60}},
                {"claim_id": "C-03", "scores": {"Q": 40, "D": 20, "I": 30, "C": 10, "R": 50, "X": 20, "P": 0}},
            ]
        }
        (self.dir / "evidence_gate_scores.json").write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
        ident = {"ledger_selfcheck": gate["ledger_selfcheck"], "claims": [
            {"claim_id": cid, "identification_level":"descriptive", "dimension_status":"bounded", "same_unit_observation":False, "unresolved_requirements":[], "blocking_issues":[]}
            for cid in ["C-01","C-02","C-03"]]}
        (self.dir / "identification_gate_scores.json").write_text(json.dumps(ident), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(REPO / "tools" / "gate_math.py"), str(self.dir)],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("重复主张评分", r.stdout)

    def test_gate_math_rejects_missing_claim_id(self):
        gate = {
            "ledger_selfcheck": {"rows_read": 2, "eid_first": "E-01", "eid_last": "E-02",
                                 "claims_covered": ["C-01", "C-02", "C-03"]},
            "claims": [
                {"claim_id": "C-01", "scores": {"Q": 85, "D": 80, "I": 70, "C": 75, "R": 85, "X": 70, "P": 60}},
                # C-02 missing
                {"claim_id": "C-03", "scores": {"Q": 40, "D": 20, "I": 30, "C": 10, "R": 50, "X": 20, "P": 0}},
            ]
        }
        (self.dir / "evidence_gate_scores.json").write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
        ident = {"ledger_selfcheck": gate["ledger_selfcheck"], "claims": [
            {"claim_id": cid, "identification_level":"descriptive", "dimension_status":"bounded", "same_unit_observation":False, "unresolved_requirements":[], "blocking_issues":[]}
            for cid in ["C-01","C-02","C-03"]]}
        (self.dir / "identification_gate_scores.json").write_text(json.dumps(ident), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(REPO / "tools" / "gate_math.py"), str(self.dir)],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("双向精确一一对应", r.stdout)

    def test_journal_record_query_and_clear(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("journal", REPO / "tools" / "journal.py")
        journal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(journal)

        # Test recording
        inp = {"branch": "us_macro", "claims": ["C-01", "C-02"]}
        out = {"branch": "us_macro", "rows_written": 25}
        entry = journal.record(self.dir, "collector", inp, out)
        self.assertEqual(entry["seq"], 1)
        self.assertTrue(len(entry["input_hash"]) >= 16)

        # Test query hit
        hit = journal.query(self.dir, "collector", inp)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["output"]["rows_written"], 25)

        # Test query miss
        miss = journal.query(self.dir, "collector", {"branch": "other"})
        self.assertIsNone(miss)

        # Test clear
        cleared = journal.clear(self.dir)
        self.assertTrue(cleared)
        self.assertIsNone(journal.query(self.dir, "collector", inp))

class BriefDetailedTests(unittest.TestCase):
    """双密度报告（brief/detailed/both）校验：speak --file 与导出隔离。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        shutil.copytree(FIXTURE, self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def run_validator(self, cmd, extra_args=None):
        args = [sys.executable, str(VALIDATOR), cmd, str(self.dir)]
        if extra_args:
            args.extend(extra_args)
        return subprocess.run(args, capture_output=True, text=True, cwd=str(REPO))

    def test_speak_with_custom_brief_file_passes(self):
        # 将默认报告复制为 brief 变体，speak --file 应同样通过（共享同一校验纪律）
        src = self.dir / "final_report.md"
        dst = self.dir / "final_report_brief.md"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        r = self.run_validator("speak", ["--file", "final_report_brief.md"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[PASS]", r.stdout)

    def test_speak_with_custom_full_file_passes(self):
        # 模拟 detailed 版：在 brief 基础上追加一章深度内容（仍保持纯净纪律），校验通过
        src = self.dir / "final_report.md"
        dst = self.dir / "final_report_full.md"
        extra = "\n## 详细机制拆解：从出口订单到工业产出的传导\n\n本章基于合成推演 CM-01 的完整链路展开：出口订单稳定带来生产排期饱满，进而支撑工业增加值。若该链路断裂，需观察替代解释是否成立。\n"
        dst.write_text(src.read_text(encoding="utf-8") + extra, encoding="utf-8")
        r = self.run_validator("speak", ["--file", "final_report_full.md"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[PASS]", r.stdout)

    def test_speak_rejects_forbidden_in_custom_file(self):
        # 精简版同样受纯净拦截：注入审计表应被 --file 校验捕获
        src = self.dir / "final_report.md"
        dst = self.dir / "final_report_brief.md"
        dst.write_text(src.read_text(encoding="utf-8") + "\n## 发言权对照表\n\n| 主张 | 发言权 | 关键来源 |\n|---|---|---|\n| test | 暂定 | src |\n", encoding="utf-8")
        r = self.run_validator("speak", ["--file", "final_report_brief.md"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不应包含发言权对照表", r.stdout)

    def test_speak_with_missing_custom_file_fails(self):
        r = self.run_validator("speak", ["--file", "nonexistent.md"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("缺失", r.stdout)


class V24RootCauseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        shutil.copytree(FIXTURE, self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def run_validator(self, cmd):
        return subprocess.run([sys.executable, str(VALIDATOR), cmd, str(self.dir)],
                              capture_output=True, text=True, cwd=str(REPO))

    def test_open_critical_gap_with_path_and_budget_blocks_design(self):
        gaps = json.loads((self.dir / "gap_register.json").read_text(encoding="utf-8"))
        gaps["gaps"].append({"gap_id":"G-02","requirement_ids":["ER-02"],"claim_ids":["C-02"],
            "description":"缺月度序列","critical":True,"attempted_paths":[],"next_feasible_path":"检索月报",
            "expected_information_gain":"补齐同口径序列","estimated_cost":"一轮","access_mode":"public","status":"open"})
        (self.dir / "gap_register.json").write_text(json.dumps(gaps, ensure_ascii=False), encoding="utf-8")
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("禁止进入门禁", r.stdout)

    def test_causal_without_same_unit_cannot_complete(self):
        brief = (self.dir / "research_brief.yaml").read_text(encoding="utf-8")
        brief = brief.replace("claim_type: trend", "claim_type: causal")
        (self.dir / "research_brief.yaml").write_text(brief, encoding="utf-8")
        auth = json.loads((self.dir / "claim_authorization.json").read_text(encoding="utf-8"))
        c = next(x for x in auth["claims"] if x["claim_id"] == "C-02")
        c["claim_type"] = "causal"
        c["same_unit_observation"] = False
        c["identification_level"] = "mechanistic"
        c["dimension_status"] = "complete"
        (self.dir / "claim_authorization.json").write_text(json.dumps(auth, ensure_ascii=False), encoding="utf-8")
        r = self.run_validator("gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("同分析单位", r.stdout)

    def test_synthesis_warning_is_hard_failure(self):
        syn = json.loads((self.dir / "final_synthesis.json").read_text(encoding="utf-8"))
        syn["causal_chains"][0]["alternative_explanations"] = []
        (self.dir / "final_synthesis.json").write_text(json.dumps(syn, ensure_ascii=False), encoding="utf-8")
        r = self.run_validator("synthesis")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("alternative_explanations", r.stdout)

    def test_homepage_source_is_hard_failure(self):
        rows = [json.loads(x) for x in (self.dir / "source_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        rows[0]["canonical_url"] = "https://www.example.gov.cn/"
        (self.dir / "source_manifest.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("机构首页", r.stdout)

    def test_title_mismatch_is_hard_failure(self):
        rows = [json.loads(x) for x in (self.dir / "source_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        rows[0]["fetched_title"] = "网站首页"
        (self.dir / "source_manifest.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("标题不匹配", r.stdout)

    def test_report_contract_missing_claim_fails_regardless_of_length(self):
        contract = json.loads((self.dir / "report_contract.json").read_text(encoding="utf-8"))
        contract["sections"] = contract["sections"][:1]
        (self.dir / "report_contract.json").write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        report = self.dir / "final_report.md"
        report.write_text(report.read_text(encoding="utf-8") + "\n" + ("很长的无新增内容。" * 1000), encoding="utf-8")
        r = self.run_validator("speak")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("未覆盖授权主张", r.stdout)

    def test_migration_marker_is_idempotent_and_does_not_create_contracts(self):
        root = Path(self._tmp.name) / "repo"
        inv = root / "investigations" / "old"
        inv.mkdir(parents=True)
        (inv / "research_brief.yaml").write_text("slug: old\nstate: COMPLETE\n", encoding="utf-8")
        cmd = [sys.executable, str(REPO / "tools" / "migrate_v24.py"), "--root", str(root), "--apply"]
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        first = (inv / "research_brief.yaml").read_text(encoding="utf-8")
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        self.assertEqual(first, (inv / "research_brief.yaml").read_text(encoding="utf-8"))
        self.assertFalse((inv / "research_design.json").exists())
        self.assertIn("MIGRATION_REQUIRED", first)


class ExportEngineTests(unittest.TestCase):
    """测试高定排版与 Word/PDF 导出引擎的函数与状态解析。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "inv"
        shutil.copytree(FIXTURE, self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    @unittest.skipUnless(importlib.util.find_spec('docx') is not None,'python-docx not installed')
    def test_detect_best_style(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("export_pdf", REPO / "tools" / "export_pdf.py")
        export_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export_mod)

        # 默认产业/科技 -> gs
        self.assertEqual(export_mod.detect_best_style(self.dir), "gs")

        # 宏观/资产配置 -> bridgewater
        brief_path = self.dir / "research_brief.yaml"
        brief_path.write_text(brief_path.read_text(encoding="utf-8") + "\nmacro-finance 资产配置 利率 美债\n", encoding="utf-8")
        self.assertEqual(export_mod.detect_best_style(self.dir), "bridgewater")

    @unittest.skipUnless(importlib.util.find_spec('docx') is not None,'python-docx not installed')
    def test_resolve_status_label(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("export_pdf", REPO / "tools" / "export_pdf.py")
        export_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export_mod)

        contract_path = self.dir / "report_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["overall_status"] = "COMPLETE_CAUSAL"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")

        label = export_mod.resolve_status_label(self.dir)
        self.assertEqual(label, "Causal – High Conviction")

        contract["overall_status"] = "COMPLETE_DESCRIPTIVE"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        label = export_mod.resolve_status_label(self.dir)
        self.assertEqual(label, "Descriptive – Evidence Bounded")

    @unittest.skipUnless(importlib.util.find_spec('docx') is not None,'python-docx not installed')
    def test_render_docx_both_styles(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("export_pdf", REPO / "tools" / "export_pdf.py")
        export_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export_mod)

        md_text = (self.dir / "final_report.md").read_text(encoding="utf-8")
        blocks = export_mod.parse_markdown(md_text)
        dynamic_stats = export_mod.extract_dynamic_kpi_stats(blocks, md_text)

        out_gs = self.dir / "test_gs.docx"
        out_bw = self.dir / "test_bw.docx"

        # 测试高盛风格 Word 生成
        export_mod.render_goldman_sachs_docx(blocks, "测试标题", "2026-09", out_gs, dynamic_stats=dynamic_stats)
        self.assertTrue(out_gs.exists())
        self.assertGreater(out_gs.stat().st_size, 1000)

        # 测试桥水风格 Word 生成（验证无 inv_dir NameError）
        export_mod.render_bridgewater_docx(blocks, "测试标题", "2026-09", out_bw)
        self.assertTrue(out_bw.exists())
        self.assertGreater(out_bw.stat().st_size, 1000)

    def test_adaptive_density_mode_passes(self):
        # 测试 report_mode: auto 在 brief.yaml 中能正常通过 speak 校验
        brief_path = self.dir / "research_brief.yaml"
        brief_text = brief_path.read_text(encoding="utf-8")
        brief_path.write_text(brief_text.replace("report_mode: detailed", "report_mode: auto"), encoding="utf-8")
        cmd = [sys.executable, str(REPO / "tools" / "validate.py"), "speak", str(self.dir)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

