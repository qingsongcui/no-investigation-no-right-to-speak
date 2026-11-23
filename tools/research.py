#!/usr/bin/env python3
"""v3 adaptive research: init, next, check, fingerprint, event, metrics. Standard library only.
Checks structure/provenance; does not certify truth or semantic entailment.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

CRITERIA = ['directness', 'evidence', 'reasoning', 'constraints', 'readability', 'uncertainty']
WORKFLOW_VERSION = '3.2'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def digest(data):
    return hashlib.sha256(data).hexdigest()

def fingerprint(root):
    # Only the reviewed inputs; telemetry and review output cannot invalidate themselves.
    return digest(b'research.json\0' + (root/'research.json').read_bytes() +
                  b'\0final_report.md\0' + (root/'final_report.md').read_bytes())

def schema_errors(value, spec, path='$'):
    """Validate the subset used by research.schema.json; no third-party dependency."""
    errors = []
    types = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
             'integer': int, 'number': (int, float)}
    kind = spec.get('type')
    if kind and (not isinstance(value, types[kind]) or (kind in {'integer','number'} and isinstance(value,bool))):
        return [f'{path}: expected {kind}']
    if 'enum' in spec and value not in spec['enum']:
        errors.append(f'{path}: invalid value {value!r}')
    if isinstance(value, str):
        if len(value.strip()) < spec.get('minLength', 0): errors.append(f'{path}: empty value')
        if 'pattern' in spec and not re.search(spec['pattern'], value): errors.append(f'{path}: invalid format')
    if isinstance(value, dict):
        for key in spec.get('required', []):
            if key not in value: errors.append(f'{path}: missing {key}')
        props = spec.get('properties', {})
        for key, item in value.items():
            if key in props: errors += schema_errors(item, props[key], path+'.'+key)
            elif spec.get('additionalProperties') is False: errors.append(f'{path}: unknown field {key}')
    if isinstance(value, list):
        if len(value) < spec.get('minItems', 0): errors.append(f'{path}: too few items')
        if spec.get('uniqueItems') and len({json.dumps(x,sort_keys=True) for x in value}) != len(value): errors.append(f'{path}: duplicate items')
        for i, item in enumerate(value): errors += schema_errors(item, spec.get('items',{}), f'{path}[{i}]')
    return errors

def needs_probe(data):
    return data['workflow_version'] == '3.2' and (
        'probes' in data or (data['purpose'] == 'live' and data['mode'] == 'reviewed')
    )


def next_steps(data):
    probes = data.get('probes', [])
    tasks = []
    needs_framing = needs_probe(data) and not probes
    if needs_framing:
        tasks.append({'type': 'probe', 'question': data['question']})
    for probe in probes:
        if 'result' not in probe:
            tasks.append(dict(probe, type='probe'))
    for gap in data['gaps']:
        if gap['critical'] and gap['status'] == 'open':
            tasks.append({'type': 'gap', 'issue': gap['issue'],
                          'question_ids': gap['question_ids'], 'next_path': gap['next_path']})
    if not tasks:
        for question in data['questions']:
            if question['status'] == 'open' and not question['finding_ids']:
                tasks.append({'type': 'question', 'id': question['id'], 'question': question['text']})
    stage = 'frame' if needs_framing else ('investigate' if tasks else 'draft')
    return {'stage': stage, 'tasks': tasks}


def validate_probes(data, questions, findings, final):
    errors = []
    citations = {}
    probes = data.get('probes', [])
    attempts = {probe['id']: set() for probe in probes}
    if len(attempts) != len(probes):
        errors.append('probes: duplicate IDs')
    attempted = set()
    for entry in data['searches']:
        probe_id = entry.get('probe_id')
        if probe_id is None:
            continue
        if probe_id not in attempts:
            errors.append('search references unknown probe: ' + probe_id)
            continue
        attempted.add(probe_id)
        attempts[probe_id].update(entry['source_ids'])

    for probe in probes:
        probe_id = probe['id']
        question_id = probe['question_id']
        question = questions.get(question_id)
        if question is None:
            errors.append(probe_id + ': probe references unknown question')
        if probe['initial'].strip() == probe['alternative'].strip():
            errors.append(probe_id + ': probe needs a distinct competing explanation or decision')

        result = probe.get('result')
        if result is None:
            continue
        result_sources = set(result['source_ids'])
        if probe_id not in attempted:
            errors.append(probe_id + ': completed probe requires a linked search or access attempt')
        if not result_sources.issubset(attempts[probe_id]):
            errors.append(probe_id + ': probe cites sources outside its linked attempts')
        related_findings = []
        for finding_id in result['finding_ids']:
            finding = findings.get(finding_id)
            if finding is None or question_id not in finding['question_ids']:
                errors.append(probe_id + ': probe result must link to a finding on the same question: ' + finding_id)
            else:
                related_findings.append(finding)

        if result['outcome'] == 'bounded':
            gap_issue = result.get('gap_issue')
            matched_gap = any(
                gap['issue'] == gap_issue and question_id in gap['question_ids']
                and gap['critical'] and gap['status'] in {'bounded', 'access_required'}
                and gap['resolution'].strip() and gap['next_path'].strip()
                for gap in data['gaps']
            )
            if not matched_gap:
                errors.append(probe_id + ': bounded probe requires a same-question critical gap with an attempted resolution and a next path')
            if final and question and question['status'] not in {'bounded', 'unknown'}:
                errors.append(probe_id + ': bounded probe requires a bounded or unknown answer')
        else:
            related_sources = {source_id for finding in related_findings if finding['kind'] != 'unknown'
                               for source_id in finding['source_ids']}
            cited_sources = result_sources & related_sources
            if cited_sources:
                citations[probe_id] = cited_sources
            else:
                errors.append(probe_id + ': completed probe needs evidence from the probe in a resulting finding')

    if final:
        pending = next_steps(data)
        if pending['stage'] == 'frame':
            errors.append('This investigation needs a probe that can change the answer')
        for task in pending['tasks']:
            if task['type'] == 'probe' and 'id' in task:
                errors.append(task['id'] + ': probe still needs investigation')
            elif task['type'] == 'gap':
                errors.append('Unresolved critical gap: ' + task['issue'])
    return errors, citations


def validate(root, final=True, *, data=None):
    errors, warnings = [], []
    try:
        if data is None:
            data = read(root/'research.json')
        schema = read(Path(__file__).resolve().parents[1]/'schemas/research.schema.json')
        errors += schema_errors(data, schema)
        if errors: return errors, warnings
        if (data['stakes']=='high' or data['causal']) and data['mode']!='reviewed':
            errors.append('High stakes or causal research requires reviewed mode')
        def index(rows, label):
            ids=[r['id'] for r in rows]
            if len(ids)!=len(set(ids)): errors.append(f'{label}: duplicate IDs')
            return {r['id']:r for r in rows}
        questions=index(data['questions'],'questions')
        sources=index(data['sources'],'sources')
        findings=index(data['findings'],'findings')
        for source in sources.values():
            parsed=urlparse(source['url'])
            if parsed.scheme not in {'http','https'} or not parsed.netloc: errors.append(source['id']+': invalid source URL')
            try: datetime.fromisoformat(source['accessed_at'].replace('Z','+00:00'))
            except ValueError: errors.append(source['id']+': invalid accessed_at')
            if source.get('snapshot_path'):
                p=(root/source['snapshot_path']).resolve()
                if not p.is_relative_to(root.resolve()): errors.append(source['id']+': snapshot outside investigation')
                elif not p.is_file() or digest(p.read_bytes())!=source.get('snapshot_sha256'):
                    errors.append(source['id']+': snapshot missing or changed')
        for f in findings.values():
            if not set(f['question_ids']).issubset(questions): errors.append(f['id']+': unknown question')
            if not set(f['source_ids']).issubset(sources): errors.append(f['id']+': unknown source')
            if f['kind'] in {'fact','causal'} and not f['source_ids']: errors.append(f['id']+': fact/causal conclusion requires source')
            if f['kind'] in {'inference','recommendation','causal'} and not f['premises']: errors.append(f['id']+': reasoning requires premises')
            if f['kind']=='causal':
                if not data['causal']: errors.append(f['id']+': causal finding requires causal routing')
                design=data.get('causal_design',{})
                for key in ['unit','exposure','outcome','strategy','confounders','limitations']:
                    if not design.get(key): errors.append('causal_design: missing '+key)
            if f['kind']=='unknown' and not f['limitation']: errors.append(f['id']+': unknown requires explanation')
        for q in questions.values():
            if not set(q['finding_ids']).issubset(findings): errors.append(q['id']+': unknown finding')
            for fid in q['finding_ids']:
                if fid in findings and q['id'] not in findings[fid]['question_ids']: errors.append(q['id']+': finding mapping is not reciprocal')
        for f in findings.values():
            for qid in f['question_ids']:
                if qid in questions and f['id'] not in questions[qid]['finding_ids']: errors.append(f['id']+': question mapping is not reciprocal')
        for search in data['searches']:
            if not set(search['source_ids']).issubset(sources): errors.append('search references unknown source')
        for gap in data['gaps']:
            if not set(gap['question_ids']).issubset(questions): errors.append('gap references unknown question')
            if gap['status']!='open' and not gap['resolution']: errors.append('Closed/bounded gap needs resolution')
        probe_errors, probe_citations = validate_probes(data, questions, findings, final)
        errors += probe_errors
        if not final: return errors,warnings
        if not data['scope'].strip(): errors.append('Record the research scope before delivery')
        if data['stop']['reason']=='answered' and (any(q['status'] in {'open','unknown','bounded'} for q in questions.values()) or any(g['critical'] and g['status']!='resolved' for g in data['gaps'])):
            errors.append('Cannot mark answered while questions or critical gaps remain bounded/unknown')
        if not data['stop']['reason'] or not data['stop']['explanation']: errors.append('Record why further research stops')
        if not data['findings']: errors.append('No findings, including explicitly unknown answers')
        if data['purpose']=='live' and not data['searches']: errors.append('Live research requires actual search records')
        report=(root/'final_report.md').read_text(encoding='utf-8')
        if not report.strip(): errors.append('Empty answer')
        if data['purpose']=='historical_example' and '未重新核验' not in report:
            errors.append('Historical example must disclose 未重新核验')
        for q in questions.values():
            if q['status']=='open' or not q['answer'] or not q['finding_ids']: errors.append(q['id']+': unanswered question')
            if not q['report_excerpt'] or q['report_excerpt'] not in report: errors.append(q['id']+': answer missing from report')
        for f in findings.values():
            if not f['report_excerpt'].strip() or f['report_excerpt'] not in report: errors.append(f['id']+': finding missing from report')
        report_links = set(re.findall(r'\]\((https?://[^\s)]+)\)', report))
        known_links = {s['url'] for s in sources.values()}
        for url in sorted(report_links - known_links):
            errors.append('Unregistered citation: ' + url)
        for probe_id, source_ids in probe_citations.items():
            if not any(sources[s]['url'] in report_links for s in source_ids if s in sources):
                errors.append(probe_id + ': report must cite evidence from the completed probe')
        for f in findings.values():
            if f['source_ids'] and not any(sources[s]['url'] in report for s in f['source_ids'] if s in sources):
                errors.append(f['id']+': no reader-visible citation')
        if re.search(r'(?<!\w)[CES]-\d{2,}(?!\w)|C_entry|Transition Mechanism|主链一句|证据压缩|comparison_universe_status',report):
            warnings.append('Internal terminology may be leaking into the answer; edit in context')
        if len(report)>12000: warnings.append('Long answer: check whether each section changes understanding or action')
        if data['mode']=='reviewed':
            review=read(root/'review.json')
            review_schema=read(Path(__file__).resolve().parents[1]/'schemas/review.schema.json')
            rev_errors=schema_errors(review, review_schema)
            errors+=rev_errors
            if not rev_errors:
                if review['reviewer_id']==data['author_id']: errors.append('Author cannot independently review own answer')
                if review['input_fingerprint']!=fingerprint(root): errors.append('Review is stale; inputs changed')
                if review['verdict']!='pass': errors.append('Independent review requires revision')
                if set(c['criterion'] for c in review['checks'])!=set(CRITERIA) or len(review['checks'])!=len(CRITERIA): errors.append('Review must cover six quality criteria exactly once')
                completed_probes = {p['id'] for p in data.get('probes', []) if 'result' in p}
                for c in review['checks']:
                    if c['verdict']!='pass': errors.append('Review failed: '+c['criterion'])
                    if c['criterion'] == 'reasoning' and needs_probe(data) and c.get('probe_id') not in completed_probes:
                        errors.append('Independent reasoning review must identify an actual completed probe')
                if any(x['severity']=='blocking' for x in review['issues']): errors.append('Blocking review issues remain')
        else: warnings.append('No independent review: structural checks do not certify answer quality')
    except (OSError,ValueError,TypeError,KeyError) as exc:
        errors.append(str(exc))
    return errors,warnings

def initialize(root, question, stakes='medium', causal=False, mode=None, author_id='root', *, deep=False):
    selected=mode or ('reviewed' if stakes=='high' or causal else 'answer')
    if selected=='answer' and (stakes=='high' or causal): raise ValueError('Cannot downgrade high stakes/causal work to answer mode')
    if root.exists() and any(root.iterdir()): raise ValueError('Refusing to initialize a nonempty directory')
    root.mkdir(parents=True,exist_ok=True)
    data={'workflow_version':WORKFLOW_VERSION,'mode':selected,'purpose':'live','stakes':stakes,'causal':causal,
          'author_id':author_id,'question':question,'scope':'','constraints':[],
          'questions':[{'id':'Q1','text':question,'answer':'','status':'open','finding_ids':[],'report_excerpt':''}],
          'sources':[],'findings':[],'gaps':[],'searches':[], 'stop':{'reason':'','explanation':''}}
    if selected == 'reviewed' or deep:
        data['probes'] = []
    (root/'research.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return selected

def metrics(root):
    path=root/'.events.jsonl'
    rows=[json.loads(s) for s in path.read_text().splitlines() if s.strip()] if path.exists() else []
    totals={}
    for row in rows: totals[row['stage']]=totals.get(row['stage'],0)+row['elapsed_seconds']
    result={'timing':'recorded' if rows else 'unmeasured','stage_seconds':totals,
            'recorded_work_seconds':sum(totals.values()) if rows else None,
            'note':'Durations are recorded by the operator; parallel work sums are not wall-clock latency.'}
    if (root/'research.json').exists():
        data=read(root/'research.json')
        result.update(mode=data['mode'],search_count=len(data['searches']),source_count=len(data['sources']))
    if (root/'final_report.md').exists(): result['answer_characters']=len((root/'final_report.md').read_text())
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init');p.add_argument('root',type=Path);p.add_argument('--question',required=True)
    p.add_argument('--stakes',choices=['low','medium','high'],default='medium');p.add_argument('--causal',action='store_true')
    p.add_argument('--mode',choices=['answer','reviewed']);p.add_argument('--author-id',default='root')
    p.add_argument('--deep', action='store_true', help='Track a critical probe within the selected mode')
    for name in ['next','check','fingerprint','metrics']:
        p=sub.add_parser(name);p.add_argument('root',type=Path)
        if name=='check': p.add_argument('--draft',action='store_true')
    p=sub.add_parser('event');p.add_argument('root',type=Path);p.add_argument('--stage',required=True)
    p.add_argument('--seconds',type=float,required=True);p.add_argument('--note',default='')
    args=parser.parse_args()
    try:
        if args.command=='init': print(initialize(args.root,args.question,args.stakes,args.causal,args.mode,args.author_id,deep=args.deep))
        elif args.command=='check':
            errors,warnings=validate(args.root,not args.draft)
            for w in warnings: print('[WARN]',w)
            for e in errors: print('[FAIL]',e)
            print('[FAIL]' if errors else '[PASS] Structural/provenance checks only; truth requires source review')
            return int(bool(errors))
        elif args.command == 'next':
            data = read(args.root/'research.json')
            errors, _ = validate(args.root, final=False, data=data)
            if errors:
                print(json.dumps({'stage': 'fix_record', 'errors': errors}, ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(next_steps(data), ensure_ascii=False, indent=2))
        elif args.command=='fingerprint': print(fingerprint(args.root))
        elif args.command=='metrics': print(json.dumps(metrics(args.root),ensure_ascii=False,indent=2))
        else:
            if not args.root.is_dir() or not 0<=args.seconds<float('inf'): raise ValueError('Invalid directory or elapsed time')
            with (args.root/'.events.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'elapsed_seconds':args.seconds,'note':args.note},ensure_ascii=False)+'\n')
    except (OSError,ValueError) as exc:
        print('[FAIL]',exc);return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
