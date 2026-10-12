#!/usr/bin/env python3
"""Evaluate authorized observation imports, never invent observation accuracy.

Optional --graph/--model/--goal/--trial executes the existing frozen native
model for each row, emits complete archives and uses the declared window
readout. Alternative parameter versions need separately frozen model reports.
"""
import argparse,json,hashlib,math,subprocess,statistics,csv
from pathlib import Path

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def evaluate(d, *, verified_source=False, verified_predictions=False, verified_spec=None):
 if d.get('schema')!='flybrain-observation-import-v1':raise ValueError('Observation import version')
 source=d.get('source',{});model=d.get('model',{})
 for key in ['url','license','version','sha256','authorization']:
  if not source.get(key):raise ValueError('Missing reviewed observation source: '+key)
 for key in ['graphRoot','modelRoot','parameterProfileHash']:
  if len(model.get(key,''))!=64:raise ValueError('Frozen model root')
 if not d.get('predictionRule'):raise ValueError('Preregistered prediction rule')
 if len(source['sha256'])!=64 or any(c not in '0123456789abcdef' for c in source['sha256']):raise ValueError('Observation checksum')
 rows=d.get('rows',[]);ids=set();split_groups={};groups={'calibration':[],'heldout':[]}
 for r in rows:
  if r.get('id') in ids or r.get('split') not in groups:raise ValueError('Duplicate identity or split')
  ids.add(r['id'])
  group=r.get('splitGroup',r['id'])
  if group in split_groups and split_groups[group]!=r['split']:raise ValueError('Calibration/heldout group leakage')
  split_groups[group]=r['split']
  if not r.get('metric') or len(r.get('predictionFileSha256',''))!=64:raise ValueError('Prediction evidence and comparable observable required')
  for key in ['observed','predicted','baseline']:
   if not isinstance(r.get(key),(int,float)) or not math.isfinite(r[key]):raise ValueError('Finite actual measurements required')
  groups[r['split']].append(r)
 metrics={}
 for split,rs in groups.items():
  metrics[split]=None if not rs else {'n':len(rs),'mae':sum(abs(r['predicted']-r['observed']) for r in rs)/len(rs),'rmse':math.sqrt(sum((r['predicted']-r['observed'])**2 for r in rs)/len(rs)),'baselineMAE':sum(abs(r['baseline']-r['observed']) for r in rs)/len(rs),'noResponseCount':sum(r['predicted']==0 for r in rs)}
 sensitivity=[]
 for v in d.get('sensitivityReports',[]):
  if v.get('parameter') not in ['background','transmitter-sign','threshold','delay','intensity'] or len(v.get('parameterRoot',''))!=64 or not v.get('reportSha256'):raise ValueError('Versioned sensitivity evidence required')
  sensitivity.append(v)
 verified=verified_source and verified_predictions and verified_spec is not None and bool(groups['heldout'])
 return {'schema':'flybrain-model-evaluation-report-v1','source':source,'model':model,'taskId':d.get('taskId'),'sourceFileVerified':verified_source,'predictionArtifactsVerified':verified_predictions,'evaluationSpec':verified_spec,'predictionRule':d['predictionRule'],'metrics':metrics,'sensitivity':sensitivity,'externalObservationSupported':verified,'status':'evaluated-authorized-observations' if verified else 'observation-review-or-heldout-required','scope':'specific-model-task-observable-only','limitations':d.get('limitations',[]),'failedOrInapplicable':d.get('failedOrInapplicable',[])}
def verify_observation_rows(d, path):
 if sha(path)!=d['source']['sha256']:raise ValueError('Observation source checksum mismatch')
 mapping=d.get('observationMapping',{})
 if mapping.get('format')=='csv':
  with Path(path).open(newline='') as f:source_rows=list(csv.DictReader(f))
 elif mapping.get('format')=='json-array':
  source_rows=json.loads(Path(path).read_text())
  if not isinstance(source_rows,list):raise ValueError('Observation JSON array required')
 else:raise ValueError('Reviewed source row/field mapping required')
 fields=mapping.get('fields',{})
 if not all(fields.get(k) for k in ['id','observed','observable','unit','splitGroup']):raise ValueError('Observation mapping fields required')
 indexed={}
 for row in source_rows:
  key=str(row[fields['id']])
  if key in indexed:raise ValueError('Duplicate source observation ID')
  indexed[key]=row
 spec=d.get('evaluationSpec')
 if not isinstance(spec,dict) or spec.get('schema')!='flybrain-evaluation-spec-v1':raise ValueError('Frozen evaluation spec required')
 for k in ['observable','observationUnit','predictionUnit','predictionRule','split','model','baselineRule']:
  if not spec.get(k):raise ValueError('Evaluation spec field: '+k)
 if spec['predictionRule']!='native-full-events-target-net-v1' or spec['observable']!='target-net-spikes' or spec['predictionUnit']!='spikes':raise ValueError('Supported native observable/rule/units required')
 if spec['model']!=d['model'] or spec['predictionRule']!=d['predictionRule']:raise ValueError('Frozen evaluation model/rule mismatch')
 raw=json.dumps(spec,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
 if hashlib.sha256(raw).hexdigest()!=d.get('evaluationSpecSha256'):raise ValueError('Evaluation spec digest mismatch')
 if spec['observationUnit']!=spec['predictionUnit']:raise ValueError('Explicit reviewed observable conversion required; units cannot be inferred')
 for row in d['rows']:
  source=indexed.get(str(row['id']))
  if source is None:raise ValueError('Observation ID has no source row')
  value=float(source[fields['observed']])
  if not math.isfinite(value) or value!=row['observed'] or source[fields['observable']]!=spec['observable'] or source[fields['unit']]!=spec['observationUnit']:raise ValueError('Actual source field/observable/unit mismatch')
  if str(source[fields['splitGroup']])!=str(row.get('splitGroup',row['id'])) or spec['split'].get(str(row['id']))!=row['split']:raise ValueError('Frozen source group/split mismatch')
 if spec['baselineRule']=='zero':baseline=0
 elif spec['baselineRule']=='calibration-mean':
  values=[r['observed'] for r in d['rows'] if r['split']=='calibration']
  if not values:raise ValueError('Calibration-only baseline needs calibration observations')
  baseline=sum(values)/len(values)
 else:raise ValueError('Supported frozen baseline rule required')
 for r in d['rows']:r['baseline']=baseline
 return spec
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--observations',type=Path)
 for name in ['graph','model','goal','trial']:p.add_argument('--'+name,type=Path)
 a=p.parse_args();d=json.loads(a.input.read_text());d.pop('_sourceFileVerified',None);d.pop('_predictionFileVerified',None);source_verified=False;prediction_verified=False;spec=None
 if a.observations:
  spec=verify_observation_rows(d,a.observations);source_verified=True
 args=[a.graph,a.model,a.goal,a.trial]
 if any(args) and not all(args):p.error('Provide all four execution inputs')
 if all(args):
  goal=json.loads(a.goal.read_text())
  from target_protocol_v2 import identity
  if d.get('taskId')!=identity('goal-id',goal):raise ValueError('Actual frozen task identity mismatch')
  for field,path in [('graphRoot',a.graph),('modelDataRoot',a.model)]:
   if sha(path)!=goal[field]:raise ValueError('Frozen execution file mismatch')
  for field in ['graphRoot','modelRoot','parameterProfileHash']:
   if d['model'][field]!=goal[field]:raise ValueError('Imported/actual model identity mismatch')
  run_dir=a.output.parent/(a.output.stem+'-archives');run_dir.mkdir(parents=True,exist_ok=True)
  for index,r in enumerate(d['rows']):
   f=run_dir/f'input-{index}.json';f.write_text(json.dumps(r['input']));out=run_dir/f'trial-{index}.bin'
   command=[str(a.trial),str(a.graph),str(a.model),str(a.goal),str(f),r['seedHex'],str(out)]+(['--verify'] if out.exists() else [])
   result=json.loads(subprocess.check_output(command,text=True));r['predicted']=result['metrics']['windows'][(spec or {}).get('windowIndex',r.get('window',0))]['targetNet'];r['predictionFileSha256']=result['resultRoot'];r['predictionFile']=str(out);
   if sha(out)!=r['predictionFileSha256']:raise ValueError('Actual prediction archive checksum mismatch')
  prediction_verified=True
 report=evaluate(d,verified_source=source_verified,verified_predictions=prediction_verified,verified_spec=spec);report['importSha256']=sha(a.input);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'heldoutCount':(report['metrics']['heldout'] or {}).get('n',0)}))
if __name__=='__main__':main()
