#!/usr/bin/env python3
"""Build exact-body display assets for the four frozen CSR observation subnets.

Uses official MaleCNS SWC morphology, never type representatives as substitutes.
Display decimation preserves actual sampled segments; it is not cable topology.
"""
import argparse, concurrent.futures, hashlib, json, mmap, struct
from pathlib import Path
from prepare_atlas import ROOT, fetch, parse_swc, SWC_URL

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def encode(v):return (json.dumps(v,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def build(a):
    cfg=json.loads((ROOT/'web/data/research-profiles/duration256-v1-dev/config.json').read_text())
    assert sha(a.graph)==cfg['graph_sha256'] and sha(a.registry)==cfg['registry_sha256']
    dest=ROOT/'web/data/mining-anatomy';dest.mkdir(parents=True,exist_ok=True)
    with a.graph.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as g:
        n=cfg['neuron_count'];bodies=struct.unpack_from('<'+str(n)+'Q',g,52);indices={str(b):i for i,b in enumerate(bodies)}
        offset=52+n*8;edge_start=offset+(n+1)*8
        def outgoing(i):return struct.unpack_from('<QQ',g,offset+i*8)
        subsets=[];all_cells=set()
        for body in cfg['target_body_ids']:
            target=indices[str(body)];selected=[target];seen={target};at=0
            while at<len(selected) and len(selected)<64:
                for edge in range(*outgoing(selected[at])):
                    to=struct.unpack_from('<I',g,edge_start+edge*8)[0]
                    if to not in seen:seen.add(to);selected.append(to)
                    if len(selected)==64:break
                at+=1
            all_cells.update(selected);subsets.append({'target_body_id':str(body),'target_index':target,'default_indices':selected[:32],'maximum_indices':selected})
    # Reuse only assets whose recorded body matches exactly.
    available={}
    for c in json.loads((ROOT/'web/data/pilot-cells.json').read_text())['cells']:available[c['body_id']]=ROOT/'web'/c['geometry'].removeprefix('/assets/')
    atlas=json.loads((ROOT/'web/data/atlas.json').read_text())
    for c in atlas['entries']:available.setdefault(c['representative_body'],ROOT/'web'/c['geometry'].removeprefix('/assets/'))
    def one(i):
        body=str(bodies[i]);path=dest/(body+'.json');source=SWC_URL.format(body)
        try:
            if body in available:
                raw=json.loads(available[body].read_text());assert str(raw['body_id'])==body and raw['source']==source
            else:
                swc=fetch(source);raw=parse_swc(swc.decode());raw.update(body_id=body,source=source,source_sha256=hashlib.sha256(swc).hexdigest(),license='CC-BY-4.0')
            # First original endpoint is a real SWC location, not a borrowed soma.
            p=raw['positions'];h=raw['source_extent']/2;c=raw['source_center'];anchor=[p[0]*h+c[0],p[2]*h+c[1],-p[1]*h+c[2]]
            stride=max(1,((len(p)//6)+1199)//1200);sampled=[]
            for at in range(0,len(p),stride*6):sampled.extend(p[at:at+6])
            geo={**raw,'positions':sampled,'display_edges':len(sampled)//6,'display_decimation':f'Every {stride}th actual SWC edge; original coordinate normalization retained; no branch voltage or derived cable topology'}
            data=encode(geo);path.write_bytes(data)
            return {'body_id':body,'model_index':i,'geometry':'/assets/data/mining-anatomy/'+path.name,'geometry_sha256':hashlib.sha256(data).hexdigest(),'source':source,'source_sha256':raw['source_sha256'],'anchor_voxels':anchor,'anchor_kind':'exact SWC sampled endpoint; not claimed soma','geometry_bytes':len(data),'display_edges':len(sampled)//6,'original_edges':len(p)//6,'status':'exact-skeleton'}
        except Exception as e:
            return {'body_id':body,'model_index':i,'source':source,'status':'unlocated','limitation':str(e)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        cells=list(pool.map(one,sorted(all_cells)))
    context=ROOT/'web/data/atlas-context.json'
    index={'schema':'flypow-mining-anatomy-v1','dataset':'male-cns:v1.0','registryRoot':cfg['registry_sha256'],'graphRoot':cfg['graph_sha256'],'units':'8 nm voxels','context':{'path':'/assets/data/atlas-context.json','sha256':sha(context)},'selection':'Same CSR BFS in propagation-trace.mjs; union of four 64-cell neighborhoods. Default 32 cells / 128 edges, maximum 64 / 256.','subnets':subsets,'cells':cells,'coverage':{'requested':len(cells),'exact_skeletons':sum(c['status']=='exact-skeleton' for c in cells),'unlocated':sum(c['status']=='unlocated' for c in cells)},'license':'CC-BY-4.0','attribution':'HHMI Janelia FlyEM, Cambridge and Google Research','paths':'3D model connections between exact cells; no official pairwise synapse anchors or reconstructed axon route claimed'}
    (ROOT/'web/data/mining-anatomy.json').write_bytes(encode(index))
    digest=sha(ROOT/'web/data/mining-anatomy.json')
    (ROOT/'web/mining-anatomy-index.mjs').write_text('// Generated by tools/prepare_mining_anatomy.py. Exact release index digest.\nexport const MINING_ANATOMY_INDEX_SHA256 = '+repr(digest)+';\n')
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps({'coverage':index['coverage'],'index_sha256':digest,'geometry_bytes':sum(c.get('geometry_bytes',0) for c in cells),'subnets':subsets},indent=2)+'\n');print(json.dumps(index['coverage']),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--graph',type=Path,default=ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin');p.add_argument('--registry',type=Path,default=ROOT/'data/prepared/registry-male-cns-v1.0/neuron-registry-v1.bin');p.add_argument('--workers',type=int,choices=range(1,5),default=3);p.add_argument('--report',type=Path,default=ROOT/'data/prepared/mining-3d-anatomy-report.json');build(p.parse_args())
