#!/usr/bin/env python3
"""Frozen new science, independent seeds, shared complete-model archives.

Two disjoint downstream populations are separate scientific questions. Reuse
the identical full A/B experiment bytes, never display samples. No downloads.
"""
import argparse,copy,hashlib,json,os,subprocess,time
from pathlib import Path
from calibrate_target_v2 import save,wilson
from target_protocol_v2 import canonical,identity,sha,inputs,evaluate
ROOT=Path(__file__).resolve().parents[1]
def main(a):
 dest=ROOT/a.output;dest.mkdir(parents=True,exist_ok=True)
 original=json.loads((ROOT/'web/data/target-mining-v2/brief/goal.json').read_text());goals=[]
 for j in range(2):
  g=copy.deepcopy(original);g['responseSet']=original['responseSet'][j*12:(j+1)*12];g['responseSetRoot']=identity('member-set',g['responseSet']);g['calibrationHash']='0'*64
  g['description']=f'寻找单步低成本刺激，使固定下游响应组{j+1}的12个细胞在两个停止后窗口产生选择性响应，并限制32个固定非目标细胞的响应。'
  g['windows']=[dict(startOffset=0,endOffset=16,minTargetNet=24,minPositiveCells=6,maxOffTarget=32,selectivityNumerator=1,selectivityDenominator=1),dict(startOffset=16,endOffset=48,minTargetNet=64,minPositiveCells=6,maxOffTarget=104,selectivityNumerator=1,selectivityDenominator=1)]
  goals.append(g)
 space=inputs(goals[0]);chosen=sorted(space,key=lambda x:identity('live-goal-preregistered-input-order-20261011',x))[:20]
 seeds=[hashlib.sha256(b'FlyPoW/live-goal-independent-challenge-20261011\0'+j.to_bytes(4,'little')).digest()[:8].hex() for j in range(4)]
 prereg=dict(schema='flypow-live-goal-preregistration-v1',goals=goals,training=chosen[:12],heldOut=chosen[12:],challengeSeeds=seeds,knownSolutionsForced=False,selection='Fixed SHA256 order before running; no parameter changes after outcomes',earlyStop='Only after complete A/B fails both fixed goals; per-goal costs use its first complete failed background')
 prior=dest/'preregistration.json'
 if prior.exists() and json.loads(prior.read_text())!=prereg:raise RuntimeError('Frozen preregistration differs; use a new version')
 save(prior,prereg);measurements=[[],[]];goalpath=dest/'kernel-goal.json';save(goalpath,goals[0])
 for k,x in enumerate(chosen):
  inputpath=dest/f'input-{k}.json';save(inputpath,x);trials=[[],[]];failed=[False,False]
  for j,seed in enumerate(seeds):
   output=dest/f'sample-{k}-{j}.bin';meta=dest/f'sample-{k}-{j}.json'
   if not meta.exists():
    if output.exists():raise RuntimeError('Unindexed scientific output retained; inspect before retry')
    cmd=[str(ROOT/'target/release/target_trial'),str(ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin'),str(ROOT/'data/prepared/registry-male-cns-v1.0/model-v0.bin'),str(goalpath),str(inputpath),seed,str(output)]
    started=time.monotonic()
    with (dest/f'sample-{k}-{j}.stdout').open('w') as stdout,(dest/f'sample-{k}-{j}.stderr').open('w') as stderr:
     p=subprocess.Popen(cmd,stdout=stdout,stderr=stderr);_,status,usage=os.wait4(p.pid,0);p.returncode=os.waitstatus_to_exitcode(status)
    if p.returncode:raise RuntimeError((dest/f'sample-{k}-{j}.stderr').read_text())
    measured=json.loads((dest/f'sample-{k}-{j}.stdout').read_text());measured['process']=dict(wallMilliseconds=round((time.monotonic()-started)*1000),maximumRSSKiB=usage.ru_maxrss,userMilliseconds=round(usage.ru_utime*1000),systemMilliseconds=round(usage.ru_stime*1000));save(meta,measured)
   m=json.loads(meta.read_text());blob=output.read_bytes()
   if m['resultRoot']!=sha(blob) or m['bytes']!=len(blob) or m['seedHex']!=seed or m['metrics']!=evaluate(goals[0],x,blob):raise AssertionError('Native / independent evaluator or cached artifact mismatch')
   for n,g in enumerate(goals):
    if failed[n]:continue
    metrics=evaluate(g,x,blob);trial={**m,'metrics':metrics,'sharedScientificArchive':True};trials[n].append(trial);failed[n]=not metrics['passed']
   print(json.dumps(dict(sample=k,background=j,passed=[t[-1]['metrics']['passed'] for t in trials],elapsedMs=m['elapsedMs'])),flush=True)
   if all(failed):break
  for n in range(2):measurements[n].append(dict(input=x,partition='training' if k<12 else 'heldOut',trials=trials[n],earlyStopAfterCompleteAB=failed[n],knownSolution=False))
  save(dest/'progress.json',dict(samples=measurements,completedInputs=k+1,preregistrationHash=sha(canonical(prereg))))
 for n,g in enumerate(goals):
  samples=measurements[n];report=dict(schema='flypow-target-calibration-v2',developmentOnly=True,scientificDefinitionHash=identity('calibration-science',{k:v for k,v in g.items() if k!='calibrationHash'}),sampler={k:prereg[k] for k in ['training','heldOut','knownSolutionsForced','selection']},seeds=seeds,samples=samples,levels=[],preregistrationHash=sha(canonical(prereg)),limits=['Two CPU native process measurements; not physical GPU/Android data','Fixed 32-cell off-target coverage; not whole-brain selectivity','Finite independent held-out calibration, not formal scientific approval','Shared kernel archives are evidence for two distinct predicates; not two discoveries'])
  reference=None
  for r in [2,4,8,16]:
   done=[s for s in samples if len(s['trials'])>=r or s['earlyStopAfterCompleteAB']];passing=[s for s in done if len(s['trials'])>=r and all(t['metrics']['passed'] for t in s['trials'][:r])];held=[s for s in done if s['partition']=='heldOut'];heldpassing=[s for s in passing if s['partition']=='heldOut'];cost=sum(sum(t['elapsedMs'] for t in s['trials'][:r]) for s in done)/len(done) if done else None;p=len(passing)/len(done) if done else 0;work=cost/p if p else None
   if r==2:reference=work
   effective=r==2 or len(passing)<report['levels'][0]['successes'];enabled=r<=4 and len(done)==20 and len(heldpassing)>0 and 0<p<.9 and effective
   report['levels'].append(dict(profileId=f'downstream-group-{n+1}-r{r}-dev-20261011',requiredBackgrounds=r,sampleCount=len(done),successes=len(passing),heldOutCount=len(held),heldOutSuccesses=len(heldpassing),passRatePartsPerMillion=round(p*1000000),wilson95PartsPerMillion=[round(v*1000000) for v in wilson(len(passing),len(done))],averageReferenceMilliseconds=round(cost) if cost else None,estimatedWorkMilliseconds=round(work) if work else None,difficultyMicros=round(work/reference*1000000) if work and reference else None,challengeEffective=effective,enabled=enabled,reason='frozen-independent-dev-calibration' if enabled else 'unmeasured-or-no-held-out-success-or-correlated-challenge',maxCandidateBytes=g['maxCandidateBytes']))
  report['activationAllowed']=any(l['enabled'] for l in report['levels']);goal={**g,'calibrationHash':sha(canonical(report))};public=ROOT/f'web/data/target-mining-v2/live-group-{n+1}-20261011';save(public/'calibration.json',report);save(public/'goal.json',goal);save(dest/f'group-{n+1}-report.json',report)
  print(json.dumps(dict(goal=n+1,enabled=[l['requiredBackgrounds'] for l in report['levels'] if l['enabled']])),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='data/prepared/live-current-v3/calibration-20261011');main(p.parse_args())
