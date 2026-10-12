#!/usr/bin/env python3
"""Reproduce separate, unpaid duration experiments. Never changes the old catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')

def generate(a):
    output=Path(a.output);base=json.loads((output/'research-config.json').read_text())
    entries=[dict(id='quick32',label='Quick experiment · 32 steps',steps=32,config_path='/assets/data/research-config.json',catalog_path='/assets/data/task-catalog-dev.json',enabled=True)]
    for steps in (128,256,512):
        with tempfile.TemporaryDirectory(prefix='flypow-profile-') as temp:
            new=Path(temp)/'generated'
            subprocess.run([a.generator,a.graph,a.model,a.model_config,str(new),str(steps)],check=True)
            raw=(new/'catalog.json').read_bytes();catalog=json.loads(raw);definition=catalog['profile_definition'];profile=definition['profile_id'];destination=output/'research-profiles'/profile
            destination.mkdir(parents=True,exist_ok=True);(destination/'catalog.json').write_bytes(raw)
            write(destination/'definition.json',definition)
            cfg={**base,'profile_id':profile,'campaign':profile,'steps':steps,'observe_start':0,'parameter_version':'lif-point-v0-dev','task_catalog_sha256':hashlib.sha256(raw).hexdigest(),
                 'catalog_path':f'/assets/data/research-profiles/{profile}/catalog.json','campaign_id_sha256':bytes(catalog['campaign']['campaign_id']).hex(),
                 'experiment_root_sha256':bytes(catalog['campaign']['experiment_root']).hex(),'task_manifest_root':bytes(catalog['task_manifest_root']).hex(),
                 'profile_definition_sha256':hashlib.sha256(canonical(definition)).hexdigest(),'max_archive_bytes':134217728,'stimulus_count':len(catalog['campaign']['stimuli'])}
            write(destination/'config.json',cfg)
            rows=[json.loads(line) for line in (new/'tasks.jsonl').read_text().splitlines()]
            for row in rows:row['simulation_seed_hex']=f"{row['task']['simulation_seed']:016x}"
            write(destination/'vectors.json',{'schema':'flypow-duration-vectors-v1','profile_id':profile,'task_manifest_root':cfg['task_manifest_root'],'samples':[rows[i] for i in (0,1,124,255,512,len(rows)-1)]})
            entries.append(dict(id=profile,label=f'Duration research · {steps} steps',steps=steps,config_path=f'/assets/data/research-profiles/{profile}/config.json',catalog_path=cfg['catalog_path'],enabled=False))
    for entry in entries:
        entry['config_sha256']=hashlib.sha256((output/entry['config_path'].removeprefix('/assets/data/')).read_bytes()).hexdigest()
    write(output/'research-profiles.json',{'schema':'flypow-research-profiles-v1','default_profile':'quick32','profiles':entries,'activation':'Full-model acceptance and measured resource report required before enabling a duration profile.'})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('graph','model','model-config','generator'):p.add_argument('--'+name,required=True)
    p.add_argument('--output',default='web/data');generate(p.parse_args())
