#!/usr/bin/env python3
"""Preserve original SWC forests and connected-chain LOD. No healing/MST.

Reuses official source cache. No syn-partners download is needed for morphology
guided display; source and target parts are NEVER joined by a made-up segment.
"""
import argparse,hashlib,json,math
from collections import Counter
from pathlib import Path
from prepare_atlas import ROOT,SWC_URL,fetch
def encode(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()
def distance_segment(p,a,b):
    ab=[b[i]-a[i] for i in range(3)];den=sum(x*x for x in ab);u=max(0,min(1,sum((p[i]-a[i])*ab[i] for i in range(3))/den)) if den else 0
    return math.sqrt(sum((p[i]-a[i]-u*ab[i])**2 for i in range(3)))
def simplify(chain,xyz,error):
    if not error:return chain[:]
    keep={0,len(chain)-1};todo=[(0,len(chain)-1)]
    while todo:
        a,b=todo.pop();farthest=None;maximum=error
        for i in range(a+1,b):
            d=distance_segment(xyz[chain[i]],xyz[chain[a]],xyz[chain[b]])
            if d>maximum:maximum=d;farthest=i
        if farthest is not None:keep.add(farthest);todo.extend([(a,farthest),(farthest,b)])
    return [chain[i] for i in sorted(keep)]
def parse(text,body,index,url,source_hash):
    raw={}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        row=line.split()
        if len(row)!=7:raise ValueError('SWC row width')
        node=int(row[0]);parent=int(row[6]);typ=int(row[1]);xyz=list(map(float,row[2:5]));radius=float(row[5])
        if node<=0 or node in raw or not all(math.isfinite(v) for v in xyz+[radius]) or radius<0:raise ValueError('SWC node identity/coordinate/radius')
        raw[node]=(typ,xyz,radius,parent)
    if len(raw)<2 or len(raw)>300000:raise ValueError('SWC node count')
    ids=sorted(raw);lookup={n:i for i,n in enumerate(ids)};parents=[];children=[[] for _ in ids];roots=[]
    for i,node in enumerate(ids):
        parent=raw[node][3]
        if parent<0:parents.append(-1);roots.append(i)
        else:
            if parent not in lookup or parent==node:raise ValueError('SWC missing/self parent')
            p=lookup[parent];parents.append(p);children[p].append(i)
    component=[-1]*len(ids);order=[]
    for c,r in enumerate(roots):
        pending=[r]
        while pending:
            i=pending.pop()
            if component[i]>=0:raise ValueError('SWC cycle')
            component[i]=c;order.append(i);pending.extend(reversed(children[i]))
    if len(order)!=len(ids):raise ValueError('SWC cycle/no reachable root')
    xyz=[raw[n][1] for n in ids];chains=[]
    for i in order:
        if parents[i]<0 or len(children[i])!=1:
            for child in children[i]:
                chain=[i,child]
                while len(children[chain[-1]])==1:chain.append(children[chain[-1]][0])
                chains.append(chain)
    # Every original parent edge appears once; no disconnected line sampling.
    covered={(a,b) for chain in chains for a,b in zip(chain,chain[1:])}
    if covered!={(p,i) for i,p in enumerate(parents) if p>=0}:raise ValueError('chain coverage')
    topology=dict(nodeIds=ids,parentIndices=parents,xyz=xyz,nodeTypes=[raw[n][0] for n in ids],radii=[raw[n][2] for n in ids],roots=roots,componentIds=component)
    lods=[]
    for error in [0,16,64]:
        paths=[]
        for c in chains:
            display=simplify(c,xyz,error);arc=[0.]
            for a,b in zip(display,display[1:]):arc.append(arc[-1]+math.dist(xyz[a],xyz[b]))
            paths.append(dict(originalNodeIndices=c,displayNodeIndices=display,arcLengths=arc,componentId=component[c[0]]))
        lods.append(dict(errorVoxels=error,chains=paths))
    return dict(schema='flypow-morphology-topology-v2',dataset='male-cns:v1.0',bodyId=str(body),modelIndex=index,source=url,sourceSha256=source_hash,coordinateSpace='MaleCNS native SWC',units='8 nm voxels',axisMapping='x,-z,y; shared Atlas brain frame',topologyHash=digest(topology),**topology,lods=lods,displayOrigin=roots[0],originMeaning='SWC root for display only; not a measured soma/axon/synapse',synapseMappedPairs=0,license='CC-BY-4.0')
def main(a):
    path=ROOT/'web/data/mining-anatomy.json';index=json.loads(path.read_text());dest=ROOT/'web/data/mining-topology';dest.mkdir(exist_ok=True);report={'schema':'flypow-propagation-topology-report-v2','cells':[],'synapseMappedPairs':0,'mode':'morphology-guided','synPartnersStartupBytes':0}
    for cell in index['cells']:
        url=SWC_URL.format(cell['body_id']);cached=ROOT/'data/runtime/atlas-import'/(hashlib.sha256(url.encode()).hexdigest()+'.bin')
        if a.offline and not cached.exists():raise RuntimeError('Missing raw SWC cache: '+cell['body_id'])
        raw=fetch(url);source_hash=hashlib.sha256(raw).hexdigest()
        if source_hash!=cell['source_sha256']:raise ValueError('Original SWC differs from released source hash: '+cell['body_id'])
        geo=parse(raw.decode(),cell['body_id'],cell['model_index'],url,source_hash);data=encode(geo);out=dest/(cell['body_id']+'.json');out.write_bytes(data)
        cell.update(topology='/assets/data/mining-topology/'+out.name,topology_sha256=hashlib.sha256(data).hexdigest(),topology_bytes=len(data),topology_hash=geo['topologyHash'],components=len(geo['roots']))
        degree=Counter(geo['parentIndices']);report['cells'].append(dict(bodyId=cell['body_id'],nodes=len(geo['nodeIds']),components=len(geo['roots']),branchPoints=sum(count>1 for node,count in degree.items() if node>=0),chains=len(geo['lods'][0]['chains']),bytes=len(data)))
    index['schema']='flypow-mining-anatomy-v2';index['paths']='morphology-guided: original connected SWC paths; source fade and recorded target arrival; no cross-cell spatial segment without official synapse pairs';index['coverage']['topology_skeletons']=len(report['cells']);index['coverage']['synapse_mapped_pairs']=0;path.write_bytes(encode(index));h=hashlib.sha256(path.read_bytes()).hexdigest();(ROOT/'web/mining-anatomy-index.mjs').write_text('// Generated exact-body topology index.\nexport const MINING_ANATOMY_INDEX_SHA256 = '+repr(h)+';\n')
    report.update(totalBytes=sum(c['bytes'] for c in report['cells']),indexSha256=h,source='original official SWC cache; no positions inversion');out=ROOT/a.report;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(encode(report));print(json.dumps({k:v for k,v in report.items() if k!='cells'}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--offline',action='store_true');p.add_argument('--report',default='data/prepared/goal-v2-topology-report.json');main(p.parse_args())
