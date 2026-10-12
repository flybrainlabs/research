#!/usr/bin/env python3
"""Independent NumPy reference for lif-point-v0-dev; never imports or calls the Rust core.

Uses the full frozen CSR and the same specification. Integer incoming sums are
commutative only after proving the conservative bound fits i64. Not a biological calibration.
"""
import argparse, hashlib, json, struct, time
from pathlib import Path
import numpy as np


def file_hash(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.digest()


def task(c,k):
    n=len(c['targets'])*len(c['stimuli'])*c['repeats']
    if not 0<=k<n:raise ValueError('Task out of range')
    target=c['targets'][k//(len(c['stimuli'])*c['repeats'])]
    si=(k//c['repeats'])%len(c['stimuli']);repeat=k%c['repeats'];s=c['stimuli'][si]
    parts=[b'FlyPoW/task-id/v1\0']+[bytes(c[a]) for a in ['campaign_id','source_root','registry_root','graph_root','model_root','experiment_root','public_seed']]
    parts.append(struct.pack('<IIIQQIIIIqI',c['model_neuron_count'],c['simulation_steps'],c['time_step_us'],k,target['body_id'],target['model_index'],si,s['start_step'],s['end_step'],s['current'],repeat))
    task_id=hashlib.sha256(b''.join(parts)).digest()
    seed=struct.unpack('<Q',hashlib.sha256(b'FlyPoW/task-seed/v1\0'+bytes(c['public_seed'])+task_id).digest()[:8])[0]
    return target,s,seed,task_id


def validate_science(catalog):
    """Recognize the frozen definitions, independently of Rust and browser JS."""
    c=catalog['campaign'];steps=c['simulation_steps'];definition=catalog.get('profile_definition')
    if c['time_step_us']!=1000 or c['repeats']!=4:raise ValueError('Unknown scientific configuration')
    starts=[0,4,8,12] if not definition else [0,steps//8,steps//2,steps-1]
    durations=[1,2,4,8] if not definition else [1,steps//32,steps//8,steps//4]
    expected=sorted([dict(start_step=s,end_step=s+d,current=i) for s in starts for d in durations if s+d<=steps for i in [50,100,150,200]],key=lambda x:(x['start_step'],x['end_step'],x['current']))
    if c['stimuli']!=expected:raise ValueError('Unknown stimulus catalog')
    if not definition:
        if steps!=32:raise ValueError('Missing duration definition')
        experiment=b'FlyPoW/experiment/lif-rectangular-v0-dev\0'+bytes(c['model_root'])+struct.pack('<III',32,1000,0)+b''.join(struct.pack('<IIq',s['start_step'],s['end_step'],s['current']) for s in expected)
        identities=[hashlib.sha256(b'FlyPoW/aipg10/local-catalog-v0/NO-PAYMENT').digest(),hashlib.sha256(experiment).digest(),hashlib.sha256(b'FlyPoW/LOCAL-DEVELOPMENT-SEED-ONLY/v0').digest()]
    else:
        if steps not in [128,256,512]:raise ValueError('Unknown duration')
        d=dict(schema='flypow-duration-profile-v1',profile_id=f'duration{steps}-v1-dev',question='Sensitivity to rectangular stimulus timing, strength, duration and public seed; late response and persistent cascades in a longer observation window',parameter_version='lif-point-v0-dev',observe_start=0,steps=steps,time_step_us=1000,
               source_root=bytes(c['source_root']).hex(),registry_root=bytes(c['registry_root']).hex(),graph_root=bytes(c['graph_root']).hex(),model_root=bytes(c['model_root']).hex(),neuron_count=c['model_neuron_count'],
               parameters=dict(leak_divisor=8,threshold=100,reset=0,membrane_limit=1000000,refractory_steps=2,synaptic_unit=1,synaptic_delay_steps=1,background_probability_u16=256,background_current=10),
               targets=c['targets'],stimuli=expected,repeats=4,resources=dict(max_archive_bytes=134217728,max_trace_bytes=16777216,max_trace_cells=64,max_trace_edges=256),payment=False,rewards=False)
        if definition!=d:raise ValueError('Unknown duration parameters')
        raw=json.dumps(d,sort_keys=True,separators=(',',':')).encode()
        identities=[hashlib.sha256(b'FlyPoW/duration-campaign/v1\0'+raw).digest(),hashlib.sha256(b'FlyPoW/duration-experiment/v1\0'+raw).digest(),hashlib.sha256(b'FlyPoW/duration-public-seed/v1\0'+struct.pack('<I',steps)).digest()]
    if any(bytes(c[key])!=value for key,value in zip(['campaign_id','experiment_root','public_seed'],identities)):raise ValueError('Scientific identity mismatch')


def run(graph_path,model_path,catalog_path,k,archive,context=None):
    started=time.monotonic();catalog=context['catalog'] if context else json.loads(Path(catalog_path).read_text());c=catalog['campaign']
    if not context:
        if catalog['state']!='UNCALIBRATED_DEV_ONLY_NO_PAYMENT':raise ValueError('Unknown scientific configuration')
        validate_science(catalog)
    if file_hash(graph_path)!=bytes(catalog['graph_data_sha256']) or file_hash(model_path)!=bytes(catalog['model_data_sha256']):raise ValueError('Input hash mismatch')
    target,stim,seed,task_id=context["task"] if context else task(c,k)
    g=np.memmap(graph_path,dtype=np.uint8,mode='r');m=Path(model_path).read_bytes()
    if bytes(g[:8])!=b'FBGR1\0\0\0' or m[:8]!=b'FBMD1\0\0\0':raise ValueError('Input format')
    n=struct.unpack_from('<I',g,8)[0];edge_count=struct.unpack_from('<Q',g,12)[0]
    if n!=c['model_neuron_count'] or struct.unpack_from('<I',m,8)[0]!=n or m[12:44]!=file_hash(graph_path):raise ValueError('Model identity')
    ids=np.ndarray((n,),dtype='<u8',buffer=g,offset=52);offsets=np.ndarray((n+1,),dtype='<u8',buffer=g,offset=52+8*n)
    edges=np.ndarray((edge_count,2),dtype='<u4',buffer=g,offset=52+8*n+8*(n+1))
    if len(g)!=52+8*n+8*(n+1)+8*edge_count or int(ids[target['model_index']])!=target['body_id'] or bytes(g[20:52])!=bytes(c['registry_root']):raise ValueError('Graph/target mismatch')
    if int(offsets[0])!=0 or int(offsets[-1])!=edge_count or np.any(offsets[1:]<offsets[:-1]) or np.any(ids[1:]<=ids[:-1]):raise ValueError('Invalid graph order')
    if np.any(edges[:,0]>=n) or np.any(edges[:,1]==0):raise ValueError('Invalid edge')
    # A bound on ALL weights bounds every incoming sum independently of scheduling order.
    if int(edges[:,1].sum(dtype=np.uint64))+10+stim['current']>=np.iinfo(np.int64).max//2:raise ValueError('No i64 safety proof')
    signs=np.frombuffer(m,dtype=np.int8,count=n,offset=44);vnc=np.frombuffer(m,dtype=np.uint8,count=n,offset=44+n).astype(bool)
    masks=np.frombuffer(m,dtype='<u2',count=n,offset=44+2*n)
    if np.any((signs!=1)&(signs!=-1)) or np.any(masks!=vnc):raise ValueError('Unknown development metadata')
    # Independent vectorized scatter. Every integer intermediate of this sum
    # is exactly representable in binary64: the sum of ALL absolute weights is
    # proven below 2**53. Physiology remains signed i64. Fall back to the original
    # integer CSR loop when this stronger proof is unavailable.
    exact_scatter=int(edges[:,1].sum(dtype=np.uint64))<2**53
    if exact_scatter:
        edge_sources=np.repeat(np.arange(n,dtype=np.int32),np.diff(offsets).astype(np.int64))
        signed_weights=edges[:,1].astype(np.int64)*signs[edge_sources]
    steps=c['simulation_steps'];index=target['model_index']
    if n*((steps+31)//32)>np.iinfo(np.int32).max:raise ValueError('Summary overflow')
    mem=[np.zeros(n,dtype=np.int64),np.zeros(n,dtype=np.int64)];ref=[np.zeros(n,dtype=np.uint8),np.zeros(n,dtype=np.uint8)];incoming=[np.zeros(n,dtype=np.int64),np.zeros(n,dtype=np.int64)]
    active=[np.zeros(n,dtype=bool),np.zeros(n,dtype=bool)];counts=[np.zeros(n,dtype=np.int32),np.zeros(n,dtype=np.int32)];first=np.full(n,-1,dtype=np.int32);events=[[],[]];glob=[0]*8;roi=[0]*16;bins=[0]*32
    for step in range(steps):
        with np.errstate(over='ignore'):
            x=np.uint64(seed)^ids^np.uint64((step*0xd6e8feb86659fd93)&((1<<64)-1));x=x+np.uint64(0x9e3779b97f4a7c15);x=(x^(x>>np.uint64(30)))*np.uint64(0xbf58476d1ce4e5b9);x=(x^(x>>np.uint64(27)))*np.uint64(0x94d049bb133111eb);x=x^(x>>np.uint64(31))
        bg=np.where((x&np.uint64(65535))<256,10,0).astype(np.int64);fired=[]
        for arm in range(2):
            free=ref[arm]==0;ref[arm][~free]-=1
            drive=incoming[arm]+bg
            if arm and stim['start_step']<=step<stim['end_step']:drive[index]+=stim['current']
            mem[arm]=np.clip(mem[arm]-mem[arm]//8+drive,-1000000,1000000);mem[arm][~free]=0
            spikes=free&(mem[arm]>=100);fired.append(spikes);mem[arm][spikes]=0;ref[arm][spikes]=2
            ix=np.flatnonzero(spikes);active[arm]|=spikes;counts[arm]+=spikes
            glob[arm]+=len(ix);glob[4+arm]+=int(spikes[index]);glob[6+arm]+=int(np.count_nonzero(spikes&vnc))
            events[arm].append(np.column_stack((np.full(len(ix),step,dtype=np.uint32),ix)).astype('<u4').tobytes())
        different=fired[0]!=fired[1];first[(first<0)&different]=step
        bins[((step+1)*32-1)//steps]+=int(np.count_nonzero(fired[1]))-int(np.count_nonzero(fired[0]))
        roi[0]+=int(np.count_nonzero(fired[1]&vnc))-int(np.count_nonzero(fired[0]&vnc))
        next_in=[np.zeros(n,dtype=np.int64),np.zeros(n,dtype=np.int64)]
        if exact_scatter:
            for arm in range(2):
                if np.any(fired[arm]):
                    selected=fired[arm][edge_sources]
                    next_in[arm]=np.bincount(edges[selected,0],weights=signed_weights[selected],minlength=n).astype(np.int64)
        else:
            for source in np.flatnonzero(fired[0]|fired[1]):
                a,b=int(offsets[source]),int(offsets[source+1]);row=edges[a:b]
                if len(row)>1 and np.any(row[1:,0]<=row[:-1,0]):raise ValueError('Duplicate edge/order')
                targets=row[:,0];w=row[:,1].astype(np.int64)*int(signs[source])
                for arm in range(2):
                    if fired[arm][source]:next_in[arm][targets]+=w
        incoming=next_in
    glob[2]=int(np.count_nonzero(active[0]));glob[3]=int(np.count_nonzero(active[1]));delta=counts[1]-counts[0]
    changed=sorted(np.flatnonzero(first>=0),key=lambda i:(-abs(int(delta[i])),int(ids[i])))[:8]
    top=b''.join(struct.pack('<QiI',int(ids[i]),int(delta[i]),int(first[i])) for i in changed).ljust(128,b'\0')
    header=b'FBRP1\0\0\0'+struct.pack('<III B3x',n,index,steps,len(changed))+struct.pack('<8Q',*glob)+struct.pack('<16q',*roi)+struct.pack('<32i',*bins)+top+struct.pack('<II',glob[0],glob[1])
    result=header+b''.join(events[0])+b''.join(events[1]);actual=Path(archive).read_bytes()
    if result!=actual:raise ValueError('Independent full-network response differs byte for byte')
    return dict(independent_implementation='numpy-reference-v0',task_id=task_id.hex(),neuron_count=n,edge_count=edge_count,bytes=len(result),sha256=hashlib.sha256(result).hexdigest(),seconds=round(time.monotonic()-started,3))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('graph');p.add_argument('model');p.add_argument('catalog');p.add_argument('index',type=int);p.add_argument('archive');a=p.parse_args();print(json.dumps(run(a.graph,a.model,a.catalog,a.index,a.archive),indent=2))
