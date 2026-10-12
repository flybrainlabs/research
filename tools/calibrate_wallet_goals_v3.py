#!/usr/bin/env python3
"""Prospectively calibrate four independent wallet-mining acceptance populations.

Exclude every historical goal population. Preserve all prior task identities and
kernel caches. Select the first two eligible preregistered groups for a finite
Devnet plan; cached kernel reuse is calibration evidence, not new mining.
"""
import copy, json, mmap, struct, subprocess, time, os
from pathlib import Path
from calibrate_target_v2 import save, wilson
from target_protocol_v2 import canonical, identity, sha, evaluate
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/prepared/wallet-mining-v3-20261012/calibration'
CACHE=ROOT/'data/prepared/live-current-v3/calibration-20261011'

def main():
 DEST.mkdir(parents=True,exist_ok=True)
 base=json.loads((ROOT/'web/data/target-mining-v2/brief/goal.json').read_text())
 old=json.loads((CACHE/'preregistration.json').read_text())
 historical=[json.loads(path.read_text()) for path in sorted((ROOT/'web/data/target-mining-v2').glob('*/goal.json')) if not path.parent.name.startswith('wallet-v3-')]
 if len(historical)<27:raise RuntimeError('Complete historical goal set required')
 excluded={m['modelIndex'] for g in historical for key in ['responseSet','stimulusSet','offTargetSet'] for m in g[key]}
 with (ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin').open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as b:
  n=base['neuronCount'];ids=struct.unpack_from('<'+'Q'*n,b,52);offset=52+8*n;edge=offset+8*(n+1);weights={}
  for m in base['stimulusSet']:
   start,end=struct.unpack_from('<QQ',b,offset+8*m['modelIndex'])
   for j in range(start,end):
    cell,weight=struct.unpack_from('<II',b,edge+8*j)
    if cell not in excluded:weights[cell]=weights.get(cell,0)+weight
  cells=sorted(weights,key=lambda cell:(-weights[cell],cell))[:4*12]
  if len(cells)!=4*12:raise RuntimeError('Insufficient distinct downstream cells')
  goals=[]
  for i in range(4):
   g=copy.deepcopy(base);g['responseSet']=sorted([dict(bodyId=str(ids[j]),modelIndex=j) for j in cells[i*12:(i+1)*12]],key=lambda m:m['modelIndex']);g['responseSetRoot']=identity('member-set',g['responseSet']);g['calibrationHash']='0'*64
   g['description']=f'Devnet wallet acceptance population {i+1}: 12 prospectively selected downstream cells outside every historical G/S/O population, with two fixed windows and O32 selectivity.'
   g['windows']=[dict(startOffset=0,endOffset=16,minTargetNet=24,minPositiveCells=6,maxOffTarget=32,selectivityNumerator=1,selectivityDenominator=1),dict(startOffset=16,endOffset=48,minTargetNet=64,minPositiveCells=6,maxOffTarget=104,selectivityNumerator=1,selectivityDenominator=1)]
   goals.append(g)
 prereg=dict(schema='flybrainlabs-wallet-goals-preregistration-v3',goals=goals,training=old['training'],heldOut=old['heldOut'],seeds=old['challengeSeeds'],knownSolutionsForced=False,selection='4 disjoint populations of 12 cells sorted by anatomical outgoing stimulus weight, excluding all historical G/S/O populations; first two eligible groups selected only after preregistered calibration',historicalGoalHashes=[sha(canonical(g)) for g in historical],excludedModelIndices=sorted(excluded),kernelReuse='Full-event kernels with identical model, input and seed; independently reevaluate new G predicates, augment missing backgrounds only',familyPolicy='Cold start; admit only measured R2/R4 and overlapping pass-rate intervals, never inherit old samples')
 prior=DEST/'preregistration.json'
 if prior.exists() and json.loads(prior.read_text())!=prereg:raise RuntimeError('Preregistration changed')
 save(prior,prereg);measurements=[[] for _ in goals];seeds=prereg['seeds'];save(DEST/'kernel-goal.json',goals[0])
 for k,x in enumerate(prereg['training']+prereg['heldOut']):
  save(DEST/f'input-{k}.json',x);trials=[[] for _ in goals];failed=[False]*len(goals)
  for j,seed in enumerate(seeds):
   output=CACHE/f'sample-{k}-{j}.bin';meta=CACHE/f'sample-{k}-{j}.json';reused=meta.exists()
   if not reused:
    output=DEST/f'sample-{k}-{j}.bin';meta=DEST/f'sample-{k}-{j}.json'
    if not meta.exists():
     if output.exists():raise RuntimeError('Unindexed output retained; inspect')
     cmd=[str(ROOT/'target/release/target_trial'),str(ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin'),str(ROOT/'data/prepared/registry-male-cns-v1.0/model-v0.bin'),str(DEST/'kernel-goal.json'),str(DEST/f'input-{k}.json'),seed,str(output)]
     start=time.monotonic()
     with (DEST/f'sample-{k}-{j}.stdout').open('w') as out,(DEST/f'sample-{k}-{j}.stderr').open('w') as err:
      process=subprocess.Popen(cmd,stdout=out,stderr=err);_,status,usage=os.wait4(process.pid,0);process.returncode=os.waitstatus_to_exitcode(status)
     if process.returncode:raise RuntimeError((DEST/f'sample-{k}-{j}.stderr').read_text())
     m=json.loads((DEST/f'sample-{k}-{j}.stdout').read_text());m['process']=dict(wallMilliseconds=round((time.monotonic()-start)*1000),maximumRSSKiB=usage.ru_maxrss);save(meta,m)
   m=json.loads(meta.read_text());blob=output.read_bytes()
   if m['resultRoot']!=sha(blob) or m['bytes']!=len(blob) or m['seedHex']!=seed:raise RuntimeError('Complete kernel identity mismatch')
   for i,g in enumerate(goals):
    if not failed[i]:
     metrics=evaluate(g,x,blob);trials[i].append({**m,'metrics':metrics,'sharedScientificArchive':True,'reusedKernel':reused});failed[i]=not metrics['passed']
   print(json.dumps(dict(sample=k,background=j,reused=reused,stillPassing=sum(not f for f in failed))),flush=True)
   if all(failed):break
  for i in range(len(goals)):measurements[i].append(dict(input=x,partition='training' if k<12 else 'heldOut',trials=trials[i],earlyStopAfterCompleteAB=failed[i],knownSolution=False))
  save(DEST/'progress.json',dict(completedInputs=k+1))
 eligible=[]
 for i,g in enumerate(goals):
  samples=measurements[i];report=dict(schema='flypow-target-calibration-v2',developmentOnly=True,scientificDefinitionHash=identity('calibration-science',{k:v for k,v in g.items() if k!='calibrationHash'}),sampler={k:prereg[k] for k in ['training','heldOut','knownSolutionsForced','selection']},seeds=seeds,samples=samples,levels=[],preregistrationHash=sha(canonical(prereg)),limits=['Complete native event archives checked by independent Python/NumPy predicate evaluator','New disjoint downstream populations outside every historical G/S/O population; kernel/input reuse is explicitly disclosed','Fixed O32 scope, finite held-out sample, development only; not biological validation or a discovered new solution'])
  reference=None
  for r in [2,4,8,16]:
   done=[s for s in samples if len(s['trials'])>=r or s['earlyStopAfterCompleteAB']];passing=[s for s in done if len(s['trials'])>=r and all(t['metrics']['passed'] for t in s['trials'][:r])];held=[s for s in done if s['partition']=='heldOut'];heldpass=[s for s in passing if s['partition']=='heldOut'];cost=sum(sum(t['elapsedMs'] for t in s['trials'][:r]) for s in done)/len(done) if done else None;p=len(passing)/len(done) if done else 0;work=cost/p if p else None
   if r==2:reference=work
   effective=r==2 or len(passing)<report['levels'][0]['successes'];enabled=r<=4 and len(done)==20 and len(heldpass)>0 and 0<p<.9 and effective
   report['levels'].append(dict(profileId=f'wallet-new-downstream-{i+1}-r{r}-dev-20261012',requiredBackgrounds=r,sampleCount=len(done),successes=len(passing),heldOutCount=len(held),heldOutSuccesses=len(heldpass),passRatePartsPerMillion=round(p*1000000),wilson95PartsPerMillion=[round(v*1000000) for v in wilson(len(passing),len(done))],averageReferenceMilliseconds=round(cost) if cost else None,estimatedWorkMilliseconds=round(work) if work else None,difficultyMicros=round(work/reference*1000000) if work and reference else None,challengeEffective=effective,enabled=enabled,reason='preregistered-complete-event-calibration' if enabled else 'insufficient-real-evidence',maxCandidateBytes=g['maxCandidateBytes']))
  report['activationAllowed']=any(l['enabled'] for l in report['levels']);goal={**g,'calibrationHash':sha(canonical(report))};save(DEST/f'group-{i+1}/calibration.json',report);save(DEST/f'group-{i+1}/goal.json',goal)
  if report['activationAllowed']:
   public=ROOT/f'web/data/target-mining-v2/wallet-v3-group-{i+1}-20261012';save(public/'goal.json',goal);save(public/'calibration.json',report);eligible.append(dict(name=public.name,goalId=identity('goal-id',goal),levels=report['levels']))
 save(DEST/'eligible.json',eligible);print(json.dumps(dict(eligibleGoals=len(eligible),officialDownloads=0)),flush=True)
if __name__=='__main__':main()
