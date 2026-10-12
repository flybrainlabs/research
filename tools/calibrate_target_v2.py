#!/usr/bin/env python3
"""Resumable real full MaleCNS calibration; uses cached model, no downloads.

Training and held-out sampler are frozen before running. Output hashes/metrics,
native costs, rusage, all-pass early stop and known-solution reuse are recorded.
"""
import argparse,hashlib,json,math,mmap,os,struct,subprocess,time
from pathlib import Path
from target_protocol_v2 import PARAMETERS,canonical,sha,identity,inputs,evaluate
ROOT=Path(__file__).resolve().parents[1]
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.partial');tmp.write_bytes(canonical(x)+b'\n');tmp.replace(p)
def wilson(k,n):
    if not n:return [0,1]
    z=1.959963984540054;p=k/n;d=1+z*z/n;mid=(p+z*z/(2*n))/d;radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [round(mid-radius,6),round(mid+radius,6)]
def draft(profile='broad'):
    cfg=json.loads((ROOT/'web/data/research-profiles/duration256-v1-dev/config.json').read_text());cat=json.loads((ROOT/'web/data/research-profiles/duration256-v1-dev/catalog.json').read_text())['campaign']
    with (ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin').open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as g:
        n=cfg['neuron_count'];ids=struct.unpack_from('<'+'Q'*n,g,52);index={b:i for i,b in enumerate(ids)};off=52+8*n;edge=off+8*(n+1);S=sorted(index[b] for b in cfg['target_body_ids']);G=set()
        for i in S:
            a,b=struct.unpack_from('<QQ',g,off+8*i);rows=[struct.unpack_from('<II',g,edge+8*j) for j in range(a,b)]
            for target,_ in sorted(rows,key=lambda v:(-v[1],v[0])):
                if target not in S:G.add(target)
                if len([x for x in G if x not in S])>=24:break
            if len(G)>=24:break
        G=sorted(G)[:24];excluded=set(S)|set(G)
        O=sorted(sorted((i for i in range(n) if i not in excluded),key=lambda i:hashlib.sha256(b'FlyPoW/fixed-O/v2\0'+struct.pack('<Q',ids[i])).digest())[:32])
        members=lambda values:[dict(bodyId=str(ids[i]),modelIndex=i) for i in values]
        S,G,O=members(S),members(G),members(O)
    domain=dict(starts=[0,32,96],durations=[1,8,32],currents=[50,100,150,200]) if profile=='broad' else dict(starts=[0,32,96],durations=[1],currents=[25,50,75,100,125,150])
    windows=[dict(startOffset=0,endOffset=16,minTargetNet=16,minPositiveCells=6,maxOffTarget=128,selectivityNumerator=2,selectivityDenominator=1),dict(startOffset=16,endOffset=48,minTargetNet=32,minPositiveCells=6,maxOffTarget=256,selectivityNumerator=2,selectivityDenominator=1)]
    return dict(schema='flypow-goal-v2',family='evoked-selective-response-v1',description=('在固定四种允许刺激细胞中搜索矩形输入，使固定24个下游细胞在停止刺激后两个窗口产生诱发响应；检查32个固定非目标细胞的响应与输入成本。' if profile=='broad' else '搜索成本不超过150模型单位的单步刺激，使固定24个下游细胞在刺激停止后两个窗口持续响应，并满足32个固定非目标细胞的响应约束。'),dataset='male-cns:v1.0',sourceRoot=bytes(cat['source_root']).hex(),registryRoot=cfg['registry_sha256'],graphRoot=cfg['graph_sha256'],modelRoot=cfg['model_root_sha256'],modelDataRoot=cfg['model_sha256'],parameterProfileHash=identity('parameter-profile',PARAMETERS),parameterVersion='lif-point-v0-dev',neuronCount=n,steps=256,timeStepUs=1000,stimulusSet=S,responseSet=G,offTargetSet=O,stimulusSetRoot=identity('member-set',S),responseSetRoot=identity('member-set',G),offTargetSetRoot=identity('member-set',O),offTargetCoverage='固定32个按bodyId哈希抽样的非目标细胞；局部评估，不代表全脑选择性。',inputDomain=domain,inputDomainHash=identity('input-domain',domain),generatorVersion='rect-domain-v1',evaluatorVersion='full-events-selective-v1',windows=windows,maxStimulusCost=6400 if profile=='broad' else 150,maxTrialBytes=134217728,maxCandidateBytes=268435456,calibrationHash='0'*64)
def main(a):
    dest=ROOT/a.output;dest.mkdir(parents=True,exist_ok=True);goal=draft(a.profile)
    if (dest/'goal-draft.json').exists() and json.loads((dest/'goal-draft.json').read_text())!=goal:raise RuntimeError('Frozen scientific definition differs; use a new calibration directory')
    save(dest/'goal-draft.json',goal);space=inputs(goal)
    ordered=sorted(space,key=lambda x:identity('calibration-sampler' if a.profile=='broad' else 'calibration-sampler-brief',x));known=dict(stimulatedBodyId='16789',startStep=32,endStep=64,current=200) if a.profile=='broad' else dict(stimulatedBodyId='16789',startStep=32,endStep=33,current=150)
    chosen=[known]+[x for x in ordered if x!=known][:a.samples-1]
    split=max(1,a.samples*3//5);sampler=dict(version='sha256-fixed-domain-sampler-v1',training=chosen[:split],heldOut=chosen[split:],domainSize=len(space),noPostSelection=True)
    if (dest/'sampler.json').exists() and json.loads((dest/'sampler.json').read_text())!=sampler:raise RuntimeError('Frozen sampler differs; use a new calibration directory')
    save(dest/'sampler.json',sampler);measurements=[];seeds=[hashlib.sha256(b'FlyPoW/calibration-background/v2\0'+struct.pack('<I',j)).digest()[:8].hex() for j in range(4)]
    # Hex denotes the u64 numeric value, so both native and independent code agree.
    for k,x in enumerate(chosen):
        xp=dest/f'input-{k}.json';save(xp,x);trials=[]
        for j,seed in enumerate(seeds):
            output=dest/f'sample-{k}-{j}.bin';meta=dest/f'sample-{k}-{j}.json'
            if not meta.exists():
                if output.exists():raise RuntimeError(f'Unindexed result retained: {output}; verify rather than overwrite')
                cmd=[str(ROOT/'target/release/target_trial'),str(ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin'),str(ROOT/'data/prepared/registry-male-cns-v1.0/model-v0.bin'),str(dest/'goal-draft.json'),str(xp),seed,str(output)]
                started=time.monotonic()
                with (dest/f'sample-{k}-{j}.stdout').open('w') as out,(dest/f'sample-{k}-{j}.stderr').open('w') as err:
                    p=subprocess.Popen(cmd,stdout=out,stderr=err);_,status,usage=os.wait4(p.pid,0);p.returncode=os.waitstatus_to_exitcode(status)
                if p.returncode:raise RuntimeError((dest/f'sample-{k}-{j}.stderr').read_text())
                measured=json.loads((dest/f'sample-{k}-{j}.stdout').read_text());independent=evaluate(goal,x,output.read_bytes())
                if measured['metrics']!=independent:raise AssertionError('Independent full-event evaluator disagreement')
                measured['process']=dict(wallMilliseconds=round((time.monotonic()-started)*1000),maximumRSSKiB=usage.ru_maxrss,userMilliseconds=round(usage.ru_utime*1000),systemMilliseconds=round(usage.ru_stime*1000));save(meta,measured)
            m=json.loads(meta.read_text())
            blob=output.read_bytes()
            if m['seedHex']!=seed or len(blob)!=m['bytes'] or sha(blob)!=m['resultRoot'] or evaluate(goal,x,blob)!=m['metrics']:raise RuntimeError('Cached calibration artifact/seed/science disagreement')
            trials.append(m);print(json.dumps(dict(sample=k,background=j,passed=m['metrics']['passed'],ms=m['elapsedMs'])),flush=True)
            if not m['metrics']['passed']:break
        measurements.append(dict(input=x,partition='training' if k<split else 'heldOut',trials=trials,earlyStopAfterCompleteAB=not trials[-1]['metrics']['passed']))
        save(dest/'progress.json',dict(samples=measurements,sampler=sampler))
    report=dict(schema='flypow-target-calibration-v2',developmentOnly=True,scientificDefinitionHash=identity('calibration-science',{k:v for k,v in goal.items() if k!='calibrationHash'}),sampler=sampler,seeds=seeds,samples=measurements,levels=[],baselineSilent=all(t['metrics']['baselineSpikes']==0 for s in measurements for t in s['trials']),hardware=dict(cpuQuota='2 CPUs',memoryCgroupBytes=2147483648,renderer='not involved; native CPU',memoryScope='wait4 per native process maximum RSS, KiB'),limits=['有限固定O集合，仅评估声明范围，不代表全脑选择性','背景可高度相关，R不是精确统计置信度或密码学工作量','已知解可跨轮有效，身份绑定不证明重新消耗CPU','本次独立验证集为预先冻结的小样本，不是正式科学冻结'])
    ref_work=None
    for r in [2,4,8,16]:
        done=[s for s in measurements if len(s['trials'])>=r or s['earlyStopAfterCompleteAB']];success=sum(len(s['trials'])>=r and all(t['metrics']['passed'] for t in s['trials'][:r]) for s in done);held=[s for s in done if s['partition']=='heldOut'];hold_success=sum(len(s['trials'])>=r and all(t['metrics']['passed'] for t in s['trials'][:r]) for s in held)
        costs=[sum(t['elapsedMs'] for t in s['trials'][:r]) for s in done];p=success/len(done) if done else 0;cost=sum(costs)/len(costs) if costs else None;work=cost/p if p else None
        if r==2:ref_work=work
        # R4 evidence must actually narrow the success set. Larger unmeasured
        # tiers cannot be enabled by multiplying a nominal repetition count.
        effective=r==2 or success<report['levels'][0]['successes'];enabled=r<=4 and len(done)==len(measurements) and hold_success>0 and 0<p<.9 and effective and all(sum(t['bytes'] for t in s['trials'][:r])<=goal['maxCandidateBytes'] for s in done)
        report['levels'].append(dict(profileId=f'selective-r{r}-dev',requiredBackgrounds=r,sampleCount=len(done),successes=success,heldOutCount=len(held),heldOutSuccesses=hold_success,passRatePartsPerMillion=round(p*1000000),wilson95PartsPerMillion=[round(x*1000000) for x in wilson(success,len(done))],averageReferenceMilliseconds=round(cost) if cost else None,estimatedWorkMilliseconds=round(work) if work else None,difficultyMicros=round(work/ref_work*1000000) if work and ref_work else None,challengeEffective=effective,enabled=enabled,reason='calibrated-limited-dev' if enabled else 'unmeasured-or-no-independent-success-or-correlated-challenge',maxCandidateBytes=goal['maxCandidateBytes']))
    report['activationAllowed']=any(l['enabled'] for l in report['levels']);save(dest/'calibration.json',report);cal_hash=sha(canonical(report));goal['calibrationHash']=cal_hash;save(dest/'goal.json',goal)
    public=ROOT/'web/data/target-mining-v2'/a.profile;public.mkdir(parents=True,exist_ok=True);save(public/'goal.json',goal);save(public/'calibration.json',report)
    print(json.dumps(dict(activationAllowed=report['activationAllowed'],calibrationHash=cal_hash,enabled=[l['profileId'] for l in report['levels'] if l['enabled']])),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='data/prepared/goal-v2-calibration');p.add_argument('--samples',type=int,default=20);p.add_argument('--profile',choices=['broad','brief'],default='broad');main(p.parse_args())
