#!/usr/bin/env python3
"""Build an explicitly public calibration reproduction package. Uses retained
model and complete kernel files; replays natively, never reads candidate salts.
"""
import argparse,json,hashlib,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from target_protocol_v2 import identity,evaluate

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 goal_path=ROOT/'web/data/target-mining-v2/product-group-1-20261011/goal.json';g=json.loads(goal_path.read_text());cal=json.loads(goal_path.with_name('calibration.json').read_text());sample=cal['samples'][0];trials=sample['trials'][:2];shutil.copyfile(goal_path,a.output/'goal.json');(a.output/'input.json').write_text(json.dumps(sample['input']))
 shutil.copyfile(ROOT/'data/prepared/registry-male-cns-v1.0/graph-v1.bin',a.output/'graph.bin');shutil.copyfile(ROOT/'data/prepared/registry-male-cns-v1.0/model-v0.bin',a.output/'model.bin');shutil.copyfile(ROOT/'target/release/target_trial',a.output/'target_trial');shutil.copyfile(ROOT/'crates/target-protocol/src/bin/target_trial.rs',a.output/'target_trial.rs')
 native=[]
 for j,t in enumerate(trials):
  output=a.output/f'trial-{j}.bin'
  if not output.exists():
   original=next((path for path in [ROOT/f'data/prepared/live-current-v3/calibration-20261011/sample-0-{j}.bin',ROOT/f'data/prepared/mining-product-20261011/calibration/sample-0-{j}.bin'] if path.exists()),None)
   if original and sha(original)==t['resultRoot']:shutil.copyfile(original,output)
  cmd=[str(ROOT/'target/release/target_trial'),str(a.output/'graph.bin'),str(a.output/'model.bin'),str(a.output/'goal.json'),str(a.output/'input.json'),t['seedHex'],str(output)]+(['--verify'] if output.exists() else [])
  r=json.loads(subprocess.check_output(cmd,text=True))
  if not r['replayVerified']:
   r=json.loads(subprocess.check_output(cmd+['--verify'],text=True))
  if r['resultRoot']!=t['resultRoot'] or r['metrics']!=evaluate(g,sample['input'],output.read_bytes()):raise RuntimeError('Public native/independent evaluator mismatch')
  native.append(r)
 (a.output/'native-replay.json').write_text(json.dumps(native,indent=2))
 (a.output/'reproduce.py').write_text('''#!/usr/bin/env python3
import json,hashlib,subprocess,os
from pathlib import Path
root=Path(__file__).resolve().parent
meta=json.loads((root/'reproduction.json').read_text())
for f in meta['files']:
 with (root/f['name']).open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
 if digest!=f['sha256']:raise ValueError('Checksum mismatch: '+f['name'])
os.chmod(root/'target_trial',0o755)
for t in meta['trials']:
 subprocess.run([str(root/'target_trial'),str(root/'graph.bin'),str(root/'model.bin'),str(root/'goal.json'),str(root/'input.json'),t['seedHex'],str(root/t['file']),'--verify'],check=True)
print('Complete frozen-model replay passed; no biological validation asserted.')
''')
 (a.output/'README.txt').write_text('flybrain public paired response calibration case\nLicense: CC-BY-4.0 for this output and compilation; tools MIT OR Apache-2.0. MaleCNS source licensing and attribution: https://male-cns.janelia.org/download/\nThis is the public product-group-1 sample, body87973, current150, one step, two complete backgrounds. A/B metrics are checked from complete events, with new native byte-for-byte replay. It is not a current round winner or an external biological observation.\nDownload all listed files into one directory. On x86_64 Linux with glibc >=2.34: python3 reproduce.py. Downloading the entire frozen graph is an explicit action. No private candidate salts or credentials are included.\n')
 def entry(path):return dict(name=path.name,sha256=sha(path),bytes=path.stat().st_size)
 files=[entry(f) for f in sorted(a.output.iterdir()) if f.is_file() and f.name not in ['publication.json','reproduction.json']]
 ts=[dict(file=f'trial-{j}.bin',seedHex=t['seedHex'],sha256=t['resultRoot']) for j,t in enumerate(trials)]
 reproduction=dict(schema='flybrain-reproduction-v1',modelRoots={k:g[k] for k in ['sourceRoot','registryRoot','graphRoot','modelRoot','modelDataRoot','parameterProfileHash']},goalId=identity('goal-id',g),input=sample['input'],trials=ts,files=files,command='python3 reproduce.py',environment='x86_64 Linux glibc>=2.34 Python>=3.11; frozen native integer LIF',source='public-goal-calibration-with-new-native-replay')
 (a.output/'reproduction.json').write_text(json.dumps(reproduction,indent=2));files.append(entry(a.output/'reproduction.json'))
 publication=dict(schema='flybrain-public-calibration-package-v1',publicationPolicy='public-calibration-v1',license='CC-BY-4.0',goalId=identity('goal-id',g),input=sample['input'],requiredBackgrounds=2,trials=ts,files=files)
 (a.output/'publication.json').write_text(json.dumps(publication,indent=2));print(json.dumps({'packageId':identity('public-package-v1',publication),'files':len(files),'bytes':sum(f['bytes'] for f in files),'nativeReplays':len(native),'externalObservation':False}))
if __name__=='__main__':main()
