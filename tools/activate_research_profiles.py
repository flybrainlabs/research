#!/usr/bin/env python3
"""Enable locally measured development profiles, preserving their frozen bytes."""
import argparse
import hashlib
import json
from pathlib import Path

def main(a):
    paths=[a.benchmarks,a.reference,a.browser];reports=[json.loads(p.read_text()) for p in paths]
    measured,reference,browser=reports
    if not reference.get('success') or not browser.get('success'):raise ValueError('Require completed reference and browser acceptance')
    index=json.loads(a.index.read_text())
    for steps in [128,256]:
        profile=f'duration{steps}-v1-dev'
        for k in [0,124,200]:
            trials=[s for s in measured['samples'] if s['profile']==profile and s['k']==k]
            checked=[s for s in reference['samples'] if s['profile']==profile and s['k']==k]
            if len(trials)!=2 or len(checked)!=1 or trials[0]['resultHash']!=trials[1]['resultHash'] or checked[0]['resultHash']!=trials[0]['resultHash']:raise ValueError('Missing exact full-model verification')
            if trials[0]['archiveBytes']>134217728:raise ValueError('Archive exceeds published resource cap')
        browser_case=next((s for s in browser.get('profile_results',[]) if s['profile']==profile and s['k']==124),None)
        expected=next(s['resultHash'] for s in measured['samples'] if s['profile']==profile and s['k']==124)
        if not browser_case or browser_case.get('resultRoot')!=expected:raise ValueError('Require an actual browser result for each enabled profile')
        entry=next(p for p in index['profiles'] if p['id']==profile);entry['enabled']=True
    index['default_profile']='duration128-v1-dev';index['activation_evidence']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    index['activation']='128/256 enabled after full-model native/WASM/reference and browser acceptance; 512 remains a benchmark candidate.'
    a.index.write_text(json.dumps(index,sort_keys=True,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--benchmarks',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--browser',type=Path,required=True);p.add_argument('--index',type=Path,default=Path('web/data/research-profiles.json'));main(p.parse_args())
