"""Fault checks use explicit synthetic numbers; not biological evidence."""
import unittest,sys,copy,tempfile,hashlib,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evaluate_model import evaluate,verify_observation_rows
from publish_model_evaluation import prepare
class EvaluationBoundaries(unittest.TestCase):
 def fixture(self):
  return dict(schema='flybrain-observation-import-v1',source=dict(url='https://example.invalid/unit',license='isolated-fixture',version='fixture-v1',sha256='a'*64,authorization='unit fixture only'),model=dict(graphRoot='b'*64,modelRoot='c'*64,parameterProfileHash='d'*64),predictionRule='isolated declared observable',externalObservationVerified=True,rows=[dict(id='cal',split='calibration',metric='fixture-only',observed=2,predicted=0,baseline=1,predictionFileSha256='e'*64),dict(id='held',split='heldout',metric='fixture-only',observed=3,predicted=2,baseline=0,predictionFileSha256='f'*64)])
 def test_metrics_and_missing_source_verification(self):
  r=evaluate(self.fixture());self.assertEqual(r['metrics']['heldout']['mae'],1);self.assertFalse(r['externalObservationSupported']);self.assertEqual(r['metrics']['calibration']['noResponseCount'],1)
 def test_split_leak_and_invalid_measurement(self):
  d=self.fixture();d['rows'][0]['splitGroup']='one-observation';d['rows'][1]['splitGroup']='one-observation'
  with self.assertRaisesRegex(ValueError,'leakage'):evaluate(d)
  d=self.fixture();d['rows'][1]['predicted']=float('nan')
  with self.assertRaisesRegex(ValueError,'Finite'):evaluate(d)
 def test_forged_flags_and_publication_cannot_claim_native_evidence(self):
  d=self.fixture();d.update(_sourceFileVerified=True,_predictionFileVerified=True)
  r=evaluate(d);self.assertFalse(r['externalObservationSupported'])
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'observations.json';source.write_text('[]');digest=hashlib.sha256(source.read_bytes()).hexdigest()
   r['source']['sha256']=digest;r['sourceFileVerified']=True;r['externalObservationSupported']=True;r['taskId']='a'*64
   approval=dict(publicationPolicy='public-model-evaluation-v1',authorized=True,sourceSha256=digest,heldoutReviewComplete=True,reviewedAt='fixture')
   with self.assertRaisesRegex(ValueError,'native prediction reproduction'):prepare(r,approval,source)
   d['source']['sha256']='0'*64
   with self.assertRaisesRegex(ValueError,'checksum'):verify_observation_rows(d,source)
 def test_real_source_mapping_rejects_hand_entered_values_and_replaces_baseline(self):
  d=self.fixture();d['predictionRule']='native-full-events-target-net-v1'
  for row in d['rows']:row['metric']='target-net-spikes';row['splitGroup']=row['id'];row['baseline']=999
  spec=dict(schema='flybrain-evaluation-spec-v1',observable='target-net-spikes',observationUnit='spikes',predictionUnit='spikes',predictionRule=d['predictionRule'],model=d['model'],split={r['id']:r['split'] for r in d['rows']},baselineRule='calibration-mean')
  d['evaluationSpec']=spec;d['evaluationSpecSha256']=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  d['observationMapping']=dict(format='json-array',fields={k:k for k in ['id','observed','observable','unit','splitGroup']})
  with tempfile.TemporaryDirectory() as folder:
   source=Path(folder)/'rows.json';source.write_text(json.dumps([dict(id=r['id'],observed=r['observed'],observable='target-net-spikes',unit='spikes',splitGroup=r['id']) for r in d['rows']]))
   d['source']['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();verify_observation_rows(d,source)
   self.assertEqual([r['baseline'] for r in d['rows']],[2,2]);d['rows'][1]['observed']=100
   with self.assertRaisesRegex(ValueError,'source field'):verify_observation_rows(d,source)
if __name__=='__main__':unittest.main()
