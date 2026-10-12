#!/usr/bin/env python3
"""Publish a reviewed, authorized evaluation summary into the static evidence
registry. No observations, customer fields or arbitrary paths are published.
"""
import argparse,hashlib,json,math,subprocess,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def prepare(report,approval,source,*,reproduction_verified=False):
 if report.get('schema')!='flybrain-model-evaluation-report-v1' or approval.get('publicationPolicy')!='public-model-evaluation-v1' or not approval.get('authorized'):raise ValueError('Explicit reviewed public policy required')
 if sha(source)!=report['source']['sha256'] or approval.get('sourceSha256')!=report['source']['sha256'] or not report.get('sourceFileVerified'):raise ValueError('Reviewed observation checksum mismatch')
 for key in ['graphRoot','modelRoot','parameterProfileHash']:
  value=report['model'].get(key,'')
  if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Frozen model identity')
 task=report.get('taskId')
 if not task or len(task)!=64:raise ValueError('Specific registered task identity required')
 for group in report['metrics'].values():
  if group:
   if not isinstance(group['n'],int) or group['n']<=0 or any(not math.isfinite(group[k]) or group[k]<0 for k in ['mae','rmse','baselineMAE']):raise ValueError('Evaluation metric bounds')
 if report.get('externalObservationSupported') and not reproduction_verified:raise ValueError('Actual observation mapping and native prediction reproduction required; report booleans are not evidence')
 if report.get('externalObservationSupported') and (not report['metrics'].get('heldout') or not approval.get('heldoutReviewComplete')):raise ValueError('Heldout review required')
 source_info={k:report['source'][k] for k in ['url','license','version','sha256']}
 if not source_info['url'].startswith('https://'):raise ValueError('Accessible HTTPS provenance required')
 return dict(schema='flybrain-public-model-evaluation-v1',taskId=task,model=report['model'],source=source_info,predictionRule=report['predictionRule'],metrics=report['metrics'],externalObservationSupported=report.get('externalObservationSupported',False),sensitivity=report.get('sensitivity',[]),limitations=report.get('limitations',[]),reviewedAt=approval['reviewedAt'],scope='specific-model-task-observable-only')
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ['evaluation-input','graph','model','goal','trial']:p.add_argument('--'+key,type=Path)
 for key in ['report','approval','observations']:p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();report=json.loads(a.report.read_text());verified=False
 if report.get('externalObservationSupported'):
  if not all([a.evaluation_input,a.graph,a.model,a.goal,a.trial]):raise ValueError('Provide the original evaluation input and all frozen native execution files')
  directory=ROOT/'data/prepared/model-evaluation-recheck';directory.mkdir(parents=True,exist_ok=True)
  output=directory/(sha(a.evaluation_input)+'.json')
  subprocess.run([sys.executable,str(ROOT/'tools/evaluate_model.py'),'--input',str(a.evaluation_input),'--observations',str(a.observations),'--output',str(output),'--graph',str(a.graph),'--model',str(a.model),'--goal',str(a.goal),'--trial',str(a.trial)],check=True)
  actual=json.loads(output.read_text())
  if not actual.get('externalObservationSupported') or any(actual.get(k)!=report.get(k) for k in ['source','model','taskId','metrics','evaluationSpec','predictionRule']):raise ValueError('Actual reproduced evaluation differs from the proposed report')
  verified=True
 summary=prepare(report,json.loads(a.approval.read_text()),a.observations,reproduction_verified=verified)
 # Preserve frozen task definitions. Publication refers to an existing GoalId.
 registered=[json.loads(path.read_text()) for path in (ROOT/'web/data/target-mining-v2').glob('*/goal.json')]
 from target_protocol_v2 import identity
 if not any(identity('goal-id',g)==summary['taskId'] and all(g[k]==summary['model'][k] for k in ['graphRoot','modelRoot','parameterProfileHash']) for g in registered):raise ValueError('Registered model/task mismatch')
 raw=json.dumps(summary,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)+'\n';digest=hashlib.sha256(raw.encode()).hexdigest()
 directory=ROOT/'web/data/model-evaluations';directory.mkdir(exist_ok=True);destination=directory/(digest+'.json')
 if destination.exists() and destination.read_text()!=raw:raise ValueError('Immutable evaluation collision')
 destination.write_text(raw)
 index_path=ROOT/'web/data/model-evaluations-v1.json';index=json.loads(index_path.read_text());entry=dict(id=digest,url='/assets/data/model-evaluations/'+digest+'.json',taskId=summary['taskId'],modelRoot=summary['model']['modelRoot'],externalObservationSupported=summary['externalObservationSupported'],reviewedAt=summary['reviewedAt'])
 if not any(r['id']==digest for r in index['items']):index['items'].append(entry)
 index_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'evaluationId':digest,'publicSummaryPrepared':True,'deployAndSyncRequired':True}))
if __name__=='__main__':main()
