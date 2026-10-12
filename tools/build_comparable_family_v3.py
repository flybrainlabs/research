#!/usr/bin/env python3
"""Build only from measured, frozen calibration; no fabricated success rounds."""
import json
from pathlib import Path
from target_protocol_v2 import identity,canonical,sha,validate_family
ROOT=Path(__file__).resolve().parents[1]
def main():
    evidence=[]
    for j in [1,2]:
        d=ROOT/f'web/data/target-mining-v2/live-group-{j}-20261011';evidence.append((json.loads((d/'goal.json').read_text()),json.loads((d/'calibration.json').read_text())))
    reference,cal=evidence[0];members=[]
    for g,c in evidence:
        if sha(canonical(c))!=g['calibrationHash'] or c['preregistrationHash']!=cal['preregistrationHash']:raise ValueError('frozen measurement binding')
        members.append(dict(goalId=identity('goal-id',g),calibrationHash=g['calibrationHash'],normalizationNumerator=cal['levels'][0]['estimatedWorkMilliseconds'],normalizationDenominator=c['levels'][0]['estimatedWorkMilliseconds']))
    levels=[dict(requiredBackgrounds=l['requiredBackgrounds'],difficultyMicros=l['difficultyMicros']) for l in cal['levels'] if l['enabled'] and all(any(m['requiredBackgrounds']==l['requiredBackgrounds'] and m['enabled'] for m in c['levels']) for _,c in evidence)]
    family=dict(schema='flypow-comparable-difficulty-family-v1',revision=1,**{k:reference[k] for k in ['graphRoot','modelRoot','parameterProfileHash','evaluatorVersion']},referenceGoalId=members[0]['goalId'],preregistrationHash=cal['preregistrationHash'],normalizationVersion='reference-work-r2-ratio-v1',members=members,levels=levels,limits=['Measured full A/B archives evaluate two disjoint 12-cell populations; shared kernel, input domain and O32 coverage.','Relative complete-AB early-stop cost within 25%; R2 Wilson intervals overlap. This is a finite development calibration, not proof of identical populations.','Two distinct scientific goals supply at most two solved rounds; 16 comparable successful rounds are still required for upward feedback.','Future goals require new frozen calibration and validated family revision; never cycle solved goals or rename known solutions.'])
    validate_family(family)
    out=ROOT/'web/data/target-mining-v2/comparable-family-20261011.json';out.write_bytes(canonical(family)+b'\n')
    plan=dict(schema='flypow-target-initial-plan-v1',revision=1,source='preregistered-live-goals-20261011',goals=[dict(goalId=m['goalId'],path=f'/assets/data/target-mining-v2/live-group-{j+1}-20261011/goal.json',calibrationHash=m['calibrationHash']) for j,m in enumerate(members)],familyId=identity('comparable-difficulty-family',family),solvedRoundSupply=2,minComparableSuccessfulRounds=16,knownSolutionsAreTestCandidates=True,payment=False,rewards=False)
    (ROOT/'web/data/target-mining-v2/plan-20261011.json').write_bytes(canonical(plan)+b'\n');print(json.dumps(dict(familyId=plan['familyId'],enabledBackgrounds=[l['requiredBackgrounds'] for l in levels],distinctGoals=2,actualSuccessfulNetworkRounds=0)))
if __name__=='__main__':main()
