#!/usr/bin/env python3
"""Independent full NumPy V2 replay using the frozen V1 scientific kernel spec."""
import argparse,json
from pathlib import Path
from target_protocol_v2 import PARAMETERS,identity,inputs
from reference_sim import run

def replay(graph,model,goal_path,input_path,seed_hex,archive):
    g=json.loads(Path(goal_path).read_text());x=json.loads(Path(input_path).read_text())
    if g['parameterProfileHash']!=identity('parameter-profile',PARAMETERS) or g['steps']!=256 or x not in inputs(g) or len(seed_hex)!=16:raise ValueError('Frozen V2 configuration')
    target=next(m for m in g['stimulusSet'] if m['bodyId']==x['stimulatedBodyId'])
    context={'catalog':{'campaign':dict(model_neuron_count=g['neuronCount'],registry_root=list(bytes.fromhex(g['registryRoot'])),simulation_steps=g['steps']),'graph_data_sha256':list(bytes.fromhex(g['graphRoot'])),'model_data_sha256':list(bytes.fromhex(g['modelDataRoot']))},'task':(dict(model_index=target['modelIndex'],body_id=int(target['bodyId'])),dict(start_step=x['startStep'],end_step=x['endStep'],current=x['current']),int(seed_hex,16),bytes.fromhex(identity('reference-input',dict(input=x,goal=g,seedHex=seed_hex))))}
    result=run(graph,model,None,None,archive,context=context);result['protocol_version']=2;return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['graph','model','goal','input','seed','archive']:p.add_argument(name)
    a=p.parse_args();print(json.dumps(replay(a.graph,a.model,a.goal,a.input,a.seed,a.archive),indent=2))
