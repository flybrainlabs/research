#!/usr/bin/env python3
"""Compare durable cooperative calibration with uninterrupted execution.

Requires retained complete-model streams and their frozen preregistration. No
chain writes, source-data deletion or private authorization updates occur.
"""
import argparse, json, subprocess, time, sys
from pathlib import Path

def main(a):
    a.output.mkdir(parents=True,exist_ok=False)
    common=[sys.executable,str(a.tool),'--historical-inventory',str(a.historical_inventory),'--groups','1','--template','overlapping-readouts-v1']
    for name in ['cache','model','goal','binary']:common+=['--'+name,str(getattr(a,name))]
    results={}
    for name,yielding in [('uninterrupted',False),('yielded',True)]:
        out=a.output/name;times=[];codes=[]
        for turn in range(65):
            start=time.monotonic();run=subprocess.run(common+['--output',str(out)]+(['--yield-after-kernels','1'] if yielding else []),text=True,capture_output=True)
            times.append(time.monotonic()-start);codes.append(run.returncode);(a.output/f'{name}-{turn}.log').write_text(run.stdout+run.stderr)
            if run.returncode!=75:break
        if run.returncode!=0:raise RuntimeError(f'{name} failed; see retained log {turn}, exit {run.returncode}')
        results[name]={'slices':len(times),'totalSeconds':sum(times),'maxSliceSeconds':max(times),'exitCodes':codes}
    files=['summary.json','preregistration.json','group-1/calibration.json','group-1/specification.json'];equal={name:json.loads((a.output/'uninterrupted'/name).read_text())==json.loads((a.output/'yielded'/name).read_text()) for name in files}
    results.update(passed=all(equal.values()),equal=equal,scope='Complete-model streams; checkpoint/restart equivalence. Cached streams are reused. This does not establish new native-kernel scheduling or live throughput.',publicChainTransactions=0)
    (a.output/'report.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results));assert results['passed']
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['tool','historical-inventory','cache','model','goal','binary','output']:p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
