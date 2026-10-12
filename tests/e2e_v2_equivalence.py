#!/usr/bin/env python3
"""One genuine full WASM replay of an existing signed scientific trial.

Uses the persistent OPFS model; does not submit a claim or repeat calibration.
The reference artifact already passed native and independent NumPy comparison.
"""
import argparse,hashlib,json,time,traceback,urllib.request
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from browser_cache import retained_profile,close_test_browser
from e2e_official_download import BrowserNetwork

def main(a):
 report_path=Path(a.report).resolve();report_path.parent.mkdir(parents=True,exist_ok=True);source=json.loads(Path('data/prepared/goal-v2-competition/report.json').read_text());trial=source['manifest']['trials'][0];output=report_path.parent/(trial['trialId']+'-wasm.bin')
 prior=json.loads(report_path.read_text()) if report_path.exists() else {}
 if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest()==trial['resultRoot'] and prior.get('passed') and prior.get('wasm',{}).get('metrics')==trial['metrics'] and prior.get('wasm',{}).get('trialId')==trial['trialId']:
  print('Retained verified WASM artifact reused; no redundant simulation',flush=True);return
 network=json.load(urllib.request.urlopen(a.url+'/assets/data/target-network-v2.json'))
 assert network.get('enabled') and network.get('authorityId')==source['round']['pre']['authorityId'] and network.get('networkId')==source['round']['pre']['networkId'],'Historical replay requires the preview to use the acceptance authority public configuration; keep the same browser origin and restore primary preview afterwards.'
 report={'schema':'flypow-v2-wasm-native-numpy-equivalence','cacheReused':True,'officialDownloads':0,'submittedClaim':False,'referenceTrialId':trial['trialId']}
 with retained_profile() as profile:
  options=webdriver.ChromeOptions();options.binary_location='/usr/bin/chromium'
  for flag in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--no-proxy-server','--renderer-process-limit=1','--user-data-dir='+profile,'--window-size=1200,900']:options.add_argument(flag)
  options.add_experimental_option('prefs',{'download.default_directory':str(report_path.parent),'download.prompt_for_download':False});options.set_capability('goog:loggingPrefs',{'browser':'ALL'});d=webdriver.Chrome(options=options);d.set_script_timeout(300);network=BrowserNetwork(d);wait=WebDriverWait(d,180)
  try:
   d.get(a.url+'/mining/');wait.until(lambda _:d.execute_script('return window.flypowWorkspace'));assert not d.execute_script('return flypowWorkspace.snapshot().running');d.execute_cdp_cmd('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(report_path.parent)});report['browserVersion']=d.capabilities['browserVersion']
   result=d.execute_async_script('''const done=arguments[0];(async()=>{const {ModelRuntime}=await import('/assets/preparation-controller.mjs'),{trialTask}=await import('/assets/target-protocol-v2.mjs');const config=await(await fetch('/assets/data/research-profiles/duration256-v1-dev/config.json')).json(),runtime=window.replayRuntime=new ModelRuntime(()=>{},'equivalence-worker');await runtime.request('restore',{config},'ready');return {ready:runtime.ready};})().then(done,e=>done({error:e.message}));''');assert result.get('ready'),result;print('Existing full-model OPFS restored for one cross-implementation trial',flush=True)
   result=d.execute_async_script('''const round=arguments[0],input=arguments[1],name=arguments[2],done=arguments[3];(async()=>{const {trialTask}=await import('/assets/target-protocol-v2.mjs'),config=await(await fetch('/assets/data/research-profiles/duration256-v1-dev/config.json')).json(),task=await trialTask(round,input,0),r=await replayRuntime.request('run',{task,config,round,sessionId:crypto.randomUUID(),executionId:crypto.randomUUID()},'result');const url=URL.createObjectURL(r.archive instanceof Blob?r.archive:new Blob([r.archive])),a=document.createElement('a');a.href=url;a.download=name;a.click();const summary={resultRoot:r.resultHash,bytes:r.responseBytes,metrics:r.goalMetrics,recordSchema:r.record.schema,trialId:r.task.trialId,seed:r.task.seed.toString(16).padStart(16,'0'),computation:r.computation,memory:r.memoryReport};replayRuntime.release();return summary;})().then(done,e=>done({error:e.message}));''',source['round'],source['manifest']['input'],output.name)
   assert 'error' not in result,result;assert result['resultRoot']==trial['resultRoot'];assert result['metrics']==trial['metrics'];assert result['trialId']==trial['trialId'];assert result['recordSchema']=='flypow-target-response-record-v2';WebDriverWait(d,60).until(lambda _:output.is_file() and output.stat().st_size==trial['bytes']);assert hashlib.sha256(output.read_bytes()).hexdigest()==trial['resultRoot'];report['wasm']=result;report['archive']=str(output);report['numpyEvidence']='data/prepared/goal-v2-numpy-report.json';report['nativeEvidence']='data/prepared/goal-v2-competition/report.json';report['network']={'officialRequests':network.requests,'officialBytes':network.data_received_bytes};assert not network.requests;report['browserErrors']=[x for x in d.get_log('browser') if x['level']=='SEVERE'];assert not report['browserErrors'];report['passed']=True;print('Full V2 scientific bytes/metrics match WASM, native and independent NumPy',flush=True)
  except Exception as e:report['failure']=str(e);report['traceback']=traceback.format_exc();raise
  finally:report_path.write_text(json.dumps(report,indent=2)+'\n');network.close();close_test_browser(d)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8084');p.add_argument('--report',default='data/prepared/goal-v2-equivalence/report.json');main(p.parse_args())
