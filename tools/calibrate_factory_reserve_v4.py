#!/usr/bin/env python3
"""Prepare new readout goals off node; never approve, register, fund or mine them."""
import argparse, copy, gzip, hashlib, itertools, json, mmap, os, struct, subprocess, sys, tempfile, time, fcntl
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from target_protocol_v2 import canonical, identity, sha, evaluate
from calibrate_target_v2 import save, wilson

SCIENCE_KEYS=['graphRoot','modelRoot','parameterProfileHash','inputDomainHash','stimulusSetRoot','responseSetRoot','offTargetSetRoot','windows','evaluatorVersion','maxStimulusCost','steps','timeStepUs']

def require(ok,message):
    if not ok:raise ValueError(message)

def science(g):
    return identity('science-task-v1',{k:g[k] for k in SCIENCE_KEYS})

def checkpoint(path,value):
    temporary=path.with_name(path.name+'.next')
    with temporary.open('wb') as out:
        out.write(canonical(value));out.flush();os.fsync(out.fileno())
    os.replace(temporary,path)

def main(args):
    DEST=args.output.resolve();CACHE=args.cache.resolve();MODEL=args.model.resolve()
    if DEST==ROOT or DEST.is_relative_to(ROOT):raise ValueError('Keep calibration evidence outside the source workspace')
    if not 1<=args.groups<=64:raise ValueError('Between one and 64 candidate groups per generation')
    DEST.mkdir(parents=True,exist_ok=True)
    lock=(DEST/'generation.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    require(not (DEST/'summary.json').exists(),'Completed proposal retained; review instead of replacing it')
    inventory=json.loads(args.historical_inventory.read_text())
    require(inventory['count']==len(inventory['goals']) and inventory['count']>=39,'Include all 31 historical goals and the eight activated V4 goals')
    historical=[x['goal'] for x in inventory['goals']]
    excluded_keys=('responseSet','stimulusSet','offTargetSet') if args.template=='disjoint-readouts-v1' else ('stimulusSet','offTargetSet')
    excluded={m['modelIndex'] for g in historical for key in excluded_keys for m in g[key]}
    old=json.loads((CACHE/'preregistration.json').read_text())
    base=json.loads(args.goal.read_text())
    # Only readout sets/windows change; cached streams must share all simulation inputs.
    simulation_keys=['sourceRoot','registryRoot','graphRoot','modelRoot','modelDataRoot','parameterProfileHash','steps','timeStepUs','stimulusSet','inputDomain']
    require(all(base[k]==old['goals'][0][k] for k in simulation_keys),'Cached kernels use a different simulation definition')
    with (MODEL/'graph-v1.bin').open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as b:
        n=base['neuronCount'];ids=struct.unpack_from('<'+'Q'*n,b,52);offset=52+8*n;edge=offset+8*(n+1);weights={}
        for m in base['stimulusSet']:
            start,end=struct.unpack_from('<QQ',b,offset+8*m['modelIndex'])
            for j in range(start,end):
                cell,weight=struct.unpack_from('<II',b,edge+8*j)
                if cell not in excluded:weights[cell]=weights.get(cell,0)+weight
        ranked=sorted(weights,key=lambda cell:(-weights[cell],cell))
        if args.template=='disjoint-readouts-v1':
            groups=[ranked[i:i+12] for i in range(0,min(len(ranked)//12,args.groups)*12,12)]
        else:
            # Overlapping readouts are distinct development predicates. Anatomy,
            # enumeration order and the complete proposal are frozen before any
            # training or held-out outcome is evaluated.
            groups=itertools.combinations(ranked[:64],12)
        require(len(ranked)>=12,'The anatomical selection envelope is exhausted')
        goals=[]
        historical_science={science(x) for x in historical}
        for cells in groups:
            g=copy.deepcopy(base)
            g['responseSet']=sorted([dict(bodyId=str(ids[j]),modelIndex=j) for j in cells],key=lambda m:m['modelIndex'])
            g['responseSetRoot']=identity('member-set',g['responseSet']);g['calibrationHash']='0'*64
            g['description']=f'Reserved V4 development readout {len(goals)+1}, template {args.template}: 12 anatomically selected downstream cells; full A/B replay, two fixed windows and two public backgrounds. Overlapping readouts are correlated simulator tasks, not independent discoveries.'
            g['windows']=[dict(startOffset=0,endOffset=16,minTargetNet=24,minPositiveCells=6,maxOffTarget=32,selectivityNumerator=1,selectivityDenominator=1),dict(startOffset=16,endOffset=48,minTargetNet=64,minPositiveCells=6,maxOffTarget=104,selectivityNumerator=1,selectivityDenominator=1)]
            if science(g) in historical_science:continue
            goals.append(g)
            if len(goals)==args.groups:break
    require(bool(goals),'The anatomical selection envelope is exhausted')
    selection=('Disjoint groups of 12 ranked by anatomical outgoing stimulus weight after excluding every historical G/S/O population' if args.template=='disjoint-readouts-v1' else 'Lexicographic combinations of 12 from the first 64 cells ranked by anatomical outgoing stimulus weight, excluding historical stimulus/off-target populations and all previous scientific identities; readout overlap is disclosed')
    prereg=dict(schema='flybrainlabs-predefined-factory-goals-preregistration-v4',template=args.template,requestedGroups=args.groups,historicalInventoryHash=sha(canonical(inventory)),historicalScientificIdentities=sorted(science(x) for x in historical),excludedModelIndices=sorted(excluded),goals=goals,training=old['training'],heldOut=old['heldOut'],seeds=old['challengeSeeds'][:2],selection=selection+'; fixed rules, no outcome tuning',qualification='20 complete inputs or sound early failure, at least one held-out success and nontrivial pass rate; earliest eligible groups retained',kernelReuse='Existing identical complete-model simulation streams with independently evaluated new readouts; missing backgrounds computed locally only',knownSolutionsForced=False,approval=False,publicBudgetAtoms='0')
    if (DEST/'preregistration.json').exists():
        require(json.loads((DEST/'preregistration.json').read_text())==prereg,'Frozen preregistration changed')
    else:
        save(DEST/'preregistration.json',prereg)
    save(DEST/'excluded-scientific-identities.json',prereg['historicalScientificIdentities'])
    save(DEST/'kernel-goal.json',goals[0])
    progress_path=DEST/'progress.json';prereg_hash=sha(canonical(prereg));kernels_this_slice=0
    progress=json.loads(progress_path.read_text()) if progress_path.exists() else dict(preregistrationHash=prereg_hash,inputIndex=0,backgroundIndex=0,samples=[[] for _ in goals],trials=[[] for _ in goals],failed=[False]*len(goals),newRuns=0)
    require(progress['preregistrationHash']==prereg_hash and len(progress['samples'])==len(goals),'Frozen progress identity mismatch')
    samples=progress['samples'];new_runs=progress['newRuns'];inputs=prereg['training']+prereg['heldOut']
    for k in range(progress['inputIndex'],len(inputs)):
        x=inputs[k];save(DEST/f'input-{k}.json',x)
        trials=progress['trials'] if k==progress['inputIndex'] else [[] for _ in goals]
        failed=progress['failed'] if k==progress['inputIndex'] else [False]*len(goals)
        start_background=progress['backgroundIndex'] if k==progress['inputIndex'] else 0
        for j in range(start_background,len(prereg['seeds'])):
            seed=prereg['seeds'][j]
            if all(failed):break
            output=CACHE/f'sample-{k}-{j}.bin';meta=CACHE/f'sample-{k}-{j}.json';reused=output.exists() and meta.exists()
            if reused:
                m=json.loads(meta.read_text());blob=output.read_bytes()
            elif (DEST/f'new-sample-{k}-{j}.json').exists():
                m=json.loads((DEST/f'new-sample-{k}-{j}.json').read_text())
                with gzip.open(DEST/f'new-sample-{k}-{j}.bin.gz','rb') as z:blob=z.read()
            else:
                # A newly generated stream is compressed and verified before its temporary file is released.
                with tempfile.TemporaryDirectory(prefix='factory-v4-kernel-') as tmp:
                    out=Path(tmp)/'trial.bin';start=time.monotonic()
                    cmd=[str(args.binary),str(MODEL/'graph-v1.bin'),str(MODEL/'model-v0.bin'),str(DEST/'kernel-goal.json'),str(DEST/f'input-{k}.json'),seed,str(out)]
                    run=subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=args.kernel_timeout_seconds);m=json.loads(run.stdout);blob=out.read_bytes();new_runs+=1
                    compressed=DEST/f'new-sample-{k}-{j}.bin.gz'
                    with gzip.open(compressed,'wb',compresslevel=1) as z:z.write(blob)
                    with gzip.open(compressed,'rb') as z:require(sha(z.read())==sha(blob),'Compressed scientific archive differs')
                    save(DEST/f'new-sample-{k}-{j}.json',{**m,'localWallSeconds':round(time.monotonic()-start),'retainedArchive':compressed.name})
            require(m['resultRoot']==sha(blob) and m['bytes']==len(blob) and m['seedHex']==seed and m['steps']==base['steps'],'Complete kernel identity mismatch')
            for i,g in enumerate(goals):
                if not failed[i]:
                    metrics=evaluate(g,x,blob);trials[i].append(dict(resultRoot=m['resultRoot'],bytes=m['bytes'],seedHex=seed,elapsedMs=m['elapsedMs'],metrics=metrics,reusedKernel=reused));failed[i]=not metrics['passed']
            print(json.dumps(dict(input=k,background=j,reusedKernel=reused,stillPassing=sum(not v for v in failed))),flush=True)
            checkpoint(progress_path,dict(preregistrationHash=prereg_hash,inputIndex=k,backgroundIndex=j+1,samples=samples,trials=trials,failed=failed,newRuns=new_runs))
            kernels_this_slice+=1
            if args.yield_after_kernels and kernels_this_slice>=args.yield_after_kernels:
                print(json.dumps(dict(status='cooperative-yield',input=k,background=j)),flush=True)
                return 75
        for i in range(len(goals)):
            samples[i].append(dict(input=x,partition='training' if k<len(prereg['training']) else 'heldOut',trials=trials[i],earlyStopAfterCompleteAB=failed[i]))
        checkpoint(progress_path,dict(preregistrationHash=prereg_hash,inputIndex=k+1,backgroundIndex=0,samples=samples,trials=[[] for _ in goals],failed=[False]*len(goals),newRuns=new_runs))
    eligible=[]
    for i,g in enumerate(goals):
        rows=samples[i];passed=[x for x in rows if len(x['trials'])==2 and all(t['metrics']['passed'] for t in x['trials'])];held=[x for x in rows if x['partition']=='heldOut'];heldpass=[x for x in passed if x['partition']=='heldOut'];enabled=len(rows)==20 and 0<len(passed)<18 and len(heldpass)>0
        report=dict(schema='flybrainlabs-factory-calibration-v4',developmentOnly=True,preregistrationHash=sha(canonical(prereg)),scientificIdentity=science(g),requiredBackgrounds=2,sampleCount=len(rows),successes=len(passed),heldOutCount=len(held),heldOutSuccesses=len(heldpass),wilson95PartsPerMillion=[round(v*1000000) for v in wilson(len(passed),len(rows))],enabled=enabled,samples=rows,kernelReuseDisclosed=True,independentBiologicalValidation=False,newMiningDiscovery=False)
        goal={**g,'calibrationHash':sha(canonical(report))};save(DEST/f'group-{i+1}/calibration.json',report);save(DEST/f'group-{i+1}/specification.json',dict(schema='flybrainlabs-scientific-task-v4',goal=goal,seeds=prereg['seeds']))
        if enabled:eligible.append(dict(group=i+1,scientificIdentity=science(goal),goalId=identity('goal-id',goal),calibrationHash=goal['calibrationHash'],specification=f'group-{i+1}/specification.json',sampleCount=len(rows),successes=len(passed),heldOutSuccesses=len(heldpass),requiredBackgrounds=2))
    summary=dict(schema='flybrainlabs-factory-catalog-proposal-v4',status='calibrated-reserve-not-registered-or-funded',template=args.template,historicalGoalsExcluded=len(historical),requestedGroups=args.groups,candidateGroups=len(goals),eligibleTasks=eligible,eligibleCount=len(eligible),newLocalKernelRuns=new_runs,publicTasksCreated=0,publicBudgetAtoms='0',approval=False,scientificScope='Development simulator readouts only; not biological accuracy or new mining discovery')
    save(DEST/'summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--historical-inventory',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--groups',type=int,default=16)
    parser.add_argument('--cache',type=Path,default=ROOT/'data/prepared/live-current-v3/calibration-20261011')
    parser.add_argument('--model',type=Path,default=ROOT/'data/prepared/registry-male-cns-v1.0')
    parser.add_argument('--binary',type=Path,default=ROOT/'target/release/target_trial')
    parser.add_argument('--goal',type=Path,default=ROOT/'web/data/target-mining-v2/brief/goal.json')
    parser.add_argument('--template',choices=['disjoint-readouts-v1','overlapping-readouts-v1'],default='disjoint-readouts-v1')
    parser.add_argument('--kernel-timeout-seconds',type=int,choices=range(30,601),default=120)
    parser.add_argument('--yield-after-kernels',type=int,choices=range(0,65),default=0)
    sys.exit(main(parser.parse_args()) or 0)
