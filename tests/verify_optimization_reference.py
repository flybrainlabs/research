#!/usr/bin/env python3
"""Run independent NumPy and complete native verification on full-model samples."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import os

def main(a):
    base=Path(a.benchmarks);report={'schema':'flypow-optimization-independent-v1','memory_scope':'per-child maximum resident set size from Linux wait4 rusage, KiB; includes interpreter and mapped inputs','samples':[]}
    while True:
        try:measured=json.loads((base/'report.json').read_text())
        except (FileNotFoundError,json.JSONDecodeError):measured={'samples':[]}
        if len(measured['samples'])==20:break
        time.sleep(1)
    graph='data/prepared/registry-male-cns-v1.0/graph-v1.bin';model='data/prepared/registry-male-cns-v1.0/model-v0.bin'
    for s in measured['samples']:
        if s['round']!=0 or s.get('resourceFailure'):continue
        catalog='web/data/task-catalog-dev.json' if s['profile']=='quick32' else f"web/data/research-profiles/{s['profile']}/catalog.json"
        sample={'profile':s['profile'],'k':s['k'],'resultHash':s['resultHash']}
        for kind,command in [('numpy',[a.python,'tools/reference_sim.py',graph,model,catalog,str(s['k']),s['archivePath']]),('native',['target/release/verify_response',graph,model,catalog,str(s['k']),s['archivePath']])]:
            metrics=base/f"{s['profile']}-{s['k']}-{kind}-process.json"
            stdout=metrics.with_suffix('.stdout');stderr=metrics.with_suffix('.stderr');at=time.monotonic()
            with stdout.open('w') as output,stderr.open('w') as errors:
                child=subprocess.Popen(command,stdout=output,stderr=errors);_,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
            if child.returncode:raise AssertionError(f'{kind}: {stderr.read_text()}')
            process={'wallSeconds':time.monotonic()-at,'maximumRSSKiB':usage.ru_maxrss,'userSeconds':usage.ru_utime,'systemSeconds':usage.ru_stime};metrics.write_text(json.dumps(process)+'\n')
            sample[kind]={'seconds':process['wallSeconds'],'process':process,'verification':json.loads(stdout.read_text()) if kind=='numpy' else stdout.read_text().strip()}
            print(json.dumps({'profile':s['profile'],'k':s['k'],'verifier':kind,'seconds':sample[kind]['seconds']}),flush=True)
        report['samples'].append(sample);Path(a.report).write_text(json.dumps(report,indent=2)+'\n')
    report['success']=True;Path(a.report).write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--benchmarks',default='data/prepared/optimization-benchmarks');p.add_argument('--python',default='/workspace/.flypow-tools/bin/python');p.add_argument('--report',default='data/prepared/optimization-reference-report.json');main(p.parse_args())
