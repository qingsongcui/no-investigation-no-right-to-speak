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
        self.data.update(scope='解释给定指标的含义',findings=[{'id':'F1','text':'它衡量数量。','kind':'fact','question_ids':['Q1'],'source_ids':['S1'],'premises':[],'limitation':'不衡量质量','report_excerpt':'它衡量数量。'}],sources=[{'id':'S1','title':'指标说明','url':'https://example.org/definition','accessed_at':'2026-09-05','evidence_text':'本指标统计数量，不涉及质量。','source_kind':'primary','evidence_locator':'定义段落','limitation':''}],searches=[{'query':'指标定义','purpose':'核对定义','source_ids':['S1'],'gain':'区分数量和质量'}],stop={'reason':'answered','explanation':'定义已核对，不继续搜重复解释。'})
        self.data['questions'][0].update(answer='它衡量数量。',status='answered',finding_ids=['F1'],report_excerpt='它衡量数量。')
        (self.root/'final_report.md').write_text('它衡量数量。不能据此判断质量。[指标说明](https://example.org/definition)')
        self.save()
    def tearDown(self): self.tmp.cleanup()
    def save(self): (self.root/'research.json').write_text(json.dumps(self.data,ensure_ascii=False))
    def errors(self): self.save();return validate(self.root)[0]
    def reviewed(self):
        self.data['mode']='reviewed';self.save()
        snap=self.root/'source.txt';snap.write_text('original')
        self.data['sources'][0].update(snapshot_path='source.txt',snapshot_sha256=hashlib.sha256(b'original').hexdigest());self.save()
        self.review={'reviewer_id':'independent-agent','provenance':'synthetic test fixture, not a real review','input_fingerprint':fingerprint(self.root),'verdict':'pass','checks':[{'criterion':c,'verdict':'pass','reason':'Synthetic fixture checks definition against provided excerpt.'} for c in CRITERIA],'issues':[]}
        self.save_review()
    def save_review(self): (self.root/'review.json').write_text(json.dumps(self.review))
    def test_natural_short_answer_without_sections_passes(self): self.assertEqual(self.errors(),[])
    def test_default_init_is_two_file_workflow(self): self.assertEqual(self.data['mode'],'answer');self.assertFalse((self.root/'research_brief.yaml').exists())
    def test_high_stakes_routes_to_reviewed(self):
        p=Path(self.tmp.name)/'high';self.assertEqual(initialize(p,'移民选择',stakes='high'),'reviewed')
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
        self.data['gaps']=[{'issue':'关键定义冲突','question_ids':['Q1'],'critical':True,'status':'open','resolution':'','next_path':'原始手册'}];self.assertTrue(self.errors())
    def test_undisclosed_historical_example_blocks(self): self.data['purpose']='historical_example';self.assertTrue(self.errors())
    def test_missing_answer_coverage_blocks(self): self.data['questions'][0]['report_excerpt']='不存在';self.assertTrue(self.errors())
    def test_new_unregistered_citation_blocks(self):
        with (self.root/'final_report.md').open('a') as f:f.write('[新来源](https://other.org/source)')
        self.assertTrue(self.errors())
    def test_review_required(self): self.data['mode']='reviewed';self.assertTrue(self.errors())
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
    def test_reviewed_fact_missing_source_kind_fails(self):
        self.reviewed();del self.data['sources'][0]['source_kind'];self.assertTrue(self.errors())
    def test_reviewed_fact_missing_evidence_locator_fails(self):
        self.reviewed();del self.data['sources'][0]['evidence_locator'];self.assertTrue(self.errors())
    def test_reviewed_fact_without_snapshot_fails(self):
        self.data['mode']='reviewed';self.save()
        self.review={'reviewer_id':'independent-agent','provenance':'synthetic test fixture, not a real review','input_fingerprint':fingerprint(self.root),'verdict':'pass','checks':[{'criterion':c,'verdict':'pass','reason':'Synthetic fixture checks definition against provided excerpt.'} for c in CRITERIA],'issues':[]}
        self.save_review();self.assertTrue(any('snapshot' in x for x in self.errors()))
    def test_answer_source_valid_without_snapshot(self):
        self.assertNotIn('snapshot_path',self.data['sources'][0]);self.assertEqual(self.errors(),[])
    def test_reviewed_snapshot_change_invalidates_delivery(self):
        self.reviewed();(self.root/'source.txt').write_text('changed');self.assertTrue(self.errors())
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

class CompatibilityTests(unittest.TestCase):
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
