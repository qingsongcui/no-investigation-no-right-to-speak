"""v3 behavior tests: routing, evidence boundaries, independent review and compatibility."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from tools.research import initialize, validate, fingerprint, metrics, CRITERIA

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'case'
        initialize(self.root,'这项指标说明什么？')
        self.data=json.loads((self.root/'research.json').read_text())
        self.data.update(scope='解释给定指标的含义',findings=[{'id':'F1','text':'它衡量数量。','kind':'fact','question_ids':['Q1'],'source_ids':['S1'],'premises':[],'limitation':'不衡量质量','report_excerpt':'它衡量数量。'}],sources=[{'id':'S1','title':'指标说明','url':'https://example.org/definition','accessed_at':'2026-09-05','evidence_text':'本指标统计数量，不涉及质量。','limitation':''}],searches=[{'query':'指标定义','purpose':'核对定义','source_ids':['S1'],'gain':'区分数量和质量'}],stop={'reason':'answered','explanation':'定义已核对，不继续搜重复解释。'})
        self.data['questions'][0].update(answer='它衡量数量。',status='answered',finding_ids=['F1'],report_excerpt='它衡量数量。')
        (self.root/'final_report.md').write_text('它衡量数量。不能据此判断质量。[指标说明](https://example.org/definition)')
        self.save()
    def tearDown(self): self.tmp.cleanup()
    def save(self): (self.root/'research.json').write_text(json.dumps(self.data,ensure_ascii=False))
    def errors(self): self.save();return validate(self.root)[0]
    def reviewed(self, version='3.1', probe_id=None):
        self.data.update(mode='reviewed', workflow_version=version)
        self.save()
        self.review={'reviewer_id':'independent-agent','provenance':'synthetic test fixture, not a real review','input_fingerprint':fingerprint(self.root),'verdict':'pass','checks':[{'criterion':c,'verdict':'pass','reason':'Synthetic fixture checks definition against provided excerpt.'} for c in CRITERIA],'issues':[]}
        if probe_id is not None:
            next(check for check in self.review['checks'] if check['criterion'] == 'reasoning')['probe_id'] = probe_id
        self.save_review()
    def save_review(self): (self.root/'review.json').write_text(json.dumps(self.review))
    def test_natural_short_answer_without_sections_passes(self): self.assertEqual(self.errors(),[])
    def test_default_init_is_two_file_workflow(self):
        self.assertEqual(self.data['mode'], 'answer')
        self.assertEqual(self.data['workflow_version'], '3.2')
        self.assertNotIn('probes', self.data)
        self.assertFalse((self.root/'research_brief.yaml').exists())
        root = Path(self.tmp.name) / 'ordinary'
        initialize(root, '这项指标说明什么？')
        plan = self.read_next(root)
        self.assertEqual(plan['stage'], 'investigate')
        self.assertEqual(plan['tasks'][0]['type'], 'question')
        self.assertEqual(self.read_next()['stage'], 'draft')
    def test_high_stakes_routes_to_reviewed(self):
        root = Path(self.tmp.name) / 'high'
        self.assertEqual(initialize(root, '移民选择', stakes='high'), 'reviewed')
        record = json.loads((root / 'research.json').read_text())
        self.assertEqual(record['probes'], [])
    def test_no_high_stakes_downgrade(self):
        self.data['stakes']='high';self.assertTrue(any('High stakes' in x for x in self.errors()))
    def test_causal_route_cannot_downgrade(self):
        self.data['causal']=True;self.assertTrue(any('High stakes' in x for x in self.errors()))
    def test_init_refuses_overwrite(self):
        with self.assertRaises(ValueError): initialize(self.root,'替换')
    def test_missing_source_blocks(self): self.data['findings'][0]['source_ids']=[];self.assertTrue(self.errors())
    def test_unknown_source_blocks(self): self.data['findings'][0]['source_ids']=['missing'];self.assertTrue(self.errors())
    def test_duplicate_id_blocks(self): self.data['sources']*=2;self.assertTrue(self.errors())
    def test_broken_reciprocal_mapping_blocks(self): self.data['questions'][0]['finding_ids']=[];self.assertTrue(self.errors())
    def test_open_critical_gap_blocks(self):
        self.data['gaps']=[{'issue':'关键定义冲突','question_ids':['Q1'],'critical':True,'status':'open','resolution':'','next_path':'原始手册'}]
        self.assertEqual(self.read_next()['stage'], 'investigate')
        self.assertTrue(self.errors())
    def test_undisclosed_historical_example_blocks(self): self.data['purpose']='historical_example';self.assertTrue(self.errors())
    def test_missing_answer_coverage_blocks(self): self.data['questions'][0]['report_excerpt']='不存在';self.assertTrue(self.errors())
    def test_new_unregistered_citation_blocks(self):
        with (self.root/'final_report.md').open('a') as f:f.write('[新来源](https://other.org/source)')
        self.assertTrue(self.errors())
    def test_review_required(self):
        self.data.update(mode='reviewed', workflow_version='3.1')
        self.assertTrue(self.errors())
    def test_independent_review_fixture_passes(self): self.reviewed();self.assertEqual(self.errors(),[])
    def test_self_review_blocks(self): self.reviewed();self.review['reviewer_id']='root';self.save_review();self.assertTrue(self.errors())
    def test_report_change_invalidates_review(self):
        self.reviewed()
        with (self.root/'final_report.md').open('a') as f:f.write(' 新的解释。')
        self.assertTrue(any('stale' in x for x in self.errors()))
    def test_evidence_change_invalidates_review(self): self.reviewed();self.data['sources'][0]['evidence_text']='不同证据';self.assertTrue(any('stale' in x for x in self.errors()))
    def test_review_cannot_pass_with_blocker(self):
        self.reviewed();self.review['issues']=[{'severity':'blocking','quote':'数量','reason':'口径错误','requested_change':'核对定义'}];self.save_review();self.assertTrue(self.errors())
    def test_review_requires_all_quality_criteria(self): self.reviewed();self.review['checks'].pop();self.save_review();self.assertTrue(self.errors())
    def test_snapshot_tampering_blocks(self):
        p=self.root/'source.txt';p.write_text('original');self.data['sources'][0].update(snapshot_path='source.txt',snapshot_sha256=hashlib.sha256(b'original').hexdigest());self.assertEqual(self.errors(),[])
        p.write_text('changed');self.assertTrue(self.errors())
    def test_unknown_timing_not_zero(self): self.assertIsNone(metrics(self.root)['recorded_work_seconds'])
    def test_malformed_data_fails_closed(self): self.data['sources']='broken';self.assertTrue(self.errors())
    def test_speak_dispatches_new_mode(self):
        r=subprocess.run([sys.executable,str(REPO/'tools/validate.py'),'speak',str(self.root)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_draft_does_not_require_final_review(self):
        self.data['mode']='reviewed';self.save();self.assertEqual(validate(self.root,final=False)[0],[])

    def test_answered_cannot_hide_bounded_question(self):
        self.data['questions'][0]['status']='bounded';self.assertTrue(self.errors())
    def test_causal_requires_evidence_and_design(self):
        self.data['findings'][0].update(kind='causal',premises=['Hypothesis'],source_ids=[])
        self.assertTrue(self.errors())
    def test_final_requires_scope(self):
        self.data['scope']='';self.assertTrue(self.errors())
    @unittest.skipUnless(importlib.util.find_spec('docx') is not None,'python-docx not installed')
    def test_export_blocks_stale_review_before_writing(self):
        from tools.export_pdf import export_single_report
        self.reviewed()
        with (self.root/'final_report.md').open('a') as f: f.write('Changed')
        self.assertEqual(export_single_report(self.root,self.root/'final_report.md'),1)
        self.assertFalse((self.root/'final_report.docx').exists())

    def test_old_v30_reviewed_record_still_validates(self):
        self.reviewed(version='3.0')
        self.assertEqual(self.errors(), [])

    def read_next(self, root=None):
        if root is None:
            self.save()
            root = self.root
        result = subprocess.run(
            [sys.executable, str(REPO/'tools/research.py'), 'next', str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def plan_probe(self):
        probe = {
            'id': 'P1',
            'question_id': 'Q1',
            'initial': '这项指标可用来判断交付质量',
            'alternative': '指标只记录交付数量，质量需要另看材料',
            'test': '如果计算公式没有质量项，放弃用该指标判断质量',
            'next_path': '打开统计手册，核对分子和分母',
        }
        self.data['probes'] = [probe]
        return probe

    def complete_probe(self, probe):
        self.data['searches'][0]['probe_id'] = probe['id']
        probe['result'] = {
            'outcome': 'revised',
            'observation': '统计定义只列数量，没有质量项',
            'impact': '报告只给出数量判断，另列质量方面的证据边界',
            'source_ids': ['S1'],
            'finding_ids': ['F1'],
        }
        return probe['result']

    def test_explicit_deep_keeps_answer_mode_and_requests_first_probe(self):
        root = Path(self.tmp.name) / 'deep'
        result = subprocess.run(
            [sys.executable, str(REPO/'tools/research.py'), 'init', str(root),
             '--question', '有哪些理由能解释交付差异？', '--deep'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((root/'research.json').read_text())
        self.assertEqual(record['mode'], 'answer')
        self.assertEqual(record['probes'], [])
        self.assertEqual(list(root.iterdir()), [root/'research.json'])
        self.assertEqual(self.read_next(root)['stage'], 'frame')
        self.data['probes'] = []
        self.assertTrue(self.errors())

    def test_reviewed_probe_drives_next_step_and_final_review(self):
        self.data['mode'] = 'reviewed'
        self.assertEqual(self.read_next()['stage'], 'frame')
        probe = self.plan_probe()
        plan = self.read_next()
        self.assertEqual(plan['stage'], 'investigate')
        self.assertEqual(plan['tasks'][0]['next_path'], probe['next_path'])
        self.reviewed(version='3.2', probe_id='P1')
        self.assertEqual(validate(self.root, final=False)[0], [])
        self.assertTrue(self.errors())

        self.complete_probe(probe)
        self.assertEqual(self.read_next()['stage'], 'draft')
        for probe_id in (None, 'P9'):
            with self.subTest(probe_id=probe_id):
                self.reviewed(version='3.2', probe_id=probe_id)
                self.assertTrue(self.errors())
        self.reviewed(version='3.2', probe_id='P1')
        result = subprocess.run(
            [sys.executable, str(REPO/'tools/validate.py'), 'speak', str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_probe_requires_attempt_and_evidence_linked_to_finding(self):
        probe = self.plan_probe()
        result = self.complete_probe(probe)
        self.assertEqual(self.errors(), [])
        self.data['searches'][0].pop('probe_id')
        self.assertTrue(self.errors())
        self.data['searches'][0]['probe_id'] = 'P1'
        self.data['sources'].append(dict(
            self.data['sources'][0], id='S2', url='https://example.org/other',
            evidence_text='另一份材料只给出通用定义。',
        ))
        result['source_ids'] = ['S2']
        self.assertTrue(self.errors())  # Registered, but absent from this attempt.
        self.data['searches'][0]['source_ids'].append('S2')
        self.assertTrue(self.errors())  # Read for this probe, but absent from its finding.
        result['source_ids'].append('S1')
        self.assertEqual(self.errors(), [])
        result['source_ids'] = []
        self.assertTrue(self.errors())

    def test_report_cites_a_source_shared_by_the_probe_and_its_finding(self):
        result = self.complete_probe(self.plan_probe())
        evidence_url = 'https://example.org/implementation'
        self.data['sources'].append(dict(
            self.data['sources'][0], id='S2', url=evidence_url,
            title='统计公式', evidence_text='分子为交付件数，公式未计质量。',
        ))
        self.data['searches'][0]['source_ids'] = ['S2']
        self.data['findings'][0]['source_ids'].append('S2')
        result['source_ids'] = ['S2']
        self.save()
        self.assertEqual(validate(self.root, final=False)[0], [])
        self.assertTrue(self.errors())

        report = self.root / 'final_report.md'
        with report.open('a', encoding='utf-8') as handle:
            handle.write(f'后台算式见[统计公式]({evidence_url})。')
        self.assertEqual(self.errors(), [])

    def test_bounded_probe_requires_a_real_attempt_and_matching_critical_gap(self):
        probe = self.plan_probe()
        probe['result'] = {
            'outcome': 'bounded',
            'observation': '公开手册仅列交付量，质量记录需登录',
            'impact': '可回答数量定义，实际质量尚待核查',
            'source_ids': [],
            'finding_ids': ['F1'],
            'gap_issue': '质量记录需要访问权限',
        }
        self.data['questions'][0]['status'] = 'bounded'
        self.data['stop'].update(reason='bounded', explanation='只能解释交付量。')
        self.data['questions'].append(dict(self.data['questions'][0], id='Q2'))
        self.data['findings'][0]['question_ids'].append('Q2')
        gap = {
            'issue': probe['result']['gap_issue'],
            'question_ids': ['Q2'],
            'critical': True,
            'status': 'access_required',
            'resolution': '已定位业务系统的访问页面，当前没有所需权限。',
            'next_path': '授权后读取同期质量记录。',
        }
        self.data['gaps'] = [gap]
        self.data['searches'].append({
            'query': '访问同期质量记录',
            'purpose': '确认待补的实际质量',
            'source_ids': [],
            'gain': '业务系统要求登录，未读取记录。',
            'probe_id': 'P1',
        })
        self.assertTrue(self.errors())  # The gap belongs to another question.
        gap['question_ids'] = ['Q1']
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.read_next()['stage'], 'draft')
        self.data['searches'].pop()
        self.assertTrue(self.errors())  # A gap description alone cannot close the probe.

    def test_comparison_and_fee_explanation_use_different_report_shapes(self):
        # Synthetic rules for this format regression. Both reports use the same evidence.
        self.data['sources'][0].update(
            title='试验收费规则', evidence_text='按笔收费。甲类可退出，乙类须继续参与。')
        reports = [
            ('怎样计算费用？', '费用按笔计算。',
             '费用按笔计算。每一笔单独结算。[收费规则](https://example.org/definition)'),
            ('甲乙两类能否退出？', '甲类可以退出，乙类须继续参与。',
             '# 两类商家的退出选择\n\n甲类可以退出，乙类须继续参与。'
             '[收费规则](https://example.org/definition)\n\n| 类别 | 能否退出 |\n|---|---|\n| 甲 | 可以 |\n| 乙 | 须继续参与 |')]
        for question, conclusion, report in reports:
            with self.subTest(question=question):
                self.data.update(question=question, scope=question)
                self.data['questions'][0].update(text=question, answer=conclusion, report_excerpt=conclusion)
                self.data['findings'][0].update(text=conclusion, report_excerpt=conclusion)
                (self.root/'final_report.md').write_text(report, encoding='utf-8')
                self.assertEqual(self.errors(), [])
        self.data['findings'][0]['source_ids'] = []
        self.assertTrue(self.errors())

class CompatibilityTests(unittest.TestCase):
    def test_natural_audit_accepts_inline_citations_and_checks_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / 'audit'
            shutil.copytree(REPO/'tests/fixtures/valid', case)
            contract_path = case/'report_contract.json'
            contract = json.loads(contract_path.read_text())
            contract['presentation'] = 'natural'
            contract_path.write_text(json.dumps(contract))
            report = case/'final_report.md'
            body = report.read_text().split('## 参考资料')[0]
            sources = [json.loads(line)['canonical_url'] for line in (case/'source_manifest.jsonl').read_text().splitlines()]
            body += f'据[年度公报]({sources[0]})及[行业观察]({sources[1]})。口径见[原始统计]({sources[0]})。'
            command = [sys.executable, str(REPO/'tools/validate.py'), 'speak', str(case)]
            for label, content, valid in [('inline', body, True), ('unregistered', body + ' [新材料](https://other.org/record)', False),
                                           ('no citations', '关于该年度工业增速的调查。', False)]:
                with self.subTest(case=label):
                    report.write_text(content, encoding='utf-8')
                    result = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, valid, result.stdout + result.stderr)

    def test_natural_audited_keeps_evidence_checks_without_forced_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'inv';shutil.copytree(REPO/'tests/fixtures/valid',p)
            contract=json.loads((p/'report_contract.json').read_text());contract['presentation']='natural'
            for section in contract['sections']:
                for k in ['mechanism','strongest_alternative','falsification_signal']:section.pop(k,None)
            (p/'report_contract.json').write_text(json.dumps(contract))
            report=p/'final_report.md';report.write_text(report.read_text().replace('执行摘要','先回答问题').replace('接下来','后续观察').replace('前瞻','后续').replace('行动','建议'))
            r=subprocess.run([sys.executable,str(REPO/'tools/validate.py'),'speak',str(p)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            (p/'source_manifest.jsonl').unlink()
            r=subprocess.run([sys.executable,str(REPO/'tools/validate.py'),'speak',str(p)],capture_output=True,text=True);self.assertNotEqual(r.returncode,0)
    @unittest.skipUnless(importlib.util.find_spec('docx') is not None,'python-docx not installed')
    def test_plain_export_preserves_links_without_branding(self):
        from tools.export_pdf import render_plain_docx,parse_markdown
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'plain.docx';render_plain_docx(parse_markdown('# 普通回答\n\n事实与解释。[来源](https://example.org/source)'),p)
            with zipfile.ZipFile(p) as z:
                xml=z.read('word/document.xml').decode();rels=z.read('word/_rels/document.xml.rels').decode()
            self.assertIn('普通回答',xml);self.assertIn('https://example.org/source',rels);self.assertNotIn('MEMORANDUM',xml)

if __name__=='__main__':unittest.main()
