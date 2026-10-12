#!/usr/bin/env python3
"""Bind frozen real measurements to a new, cold-start supply family."""
import json
from pathlib import Path
from target_protocol_v2 import canonical, identity, sha, validate_family
ROOT=Path(__file__).resolve().parents[1]

def main():
    evidence=[]
    for n in range(1,25):
        d=ROOT/f'web/data/target-mining-v2/product-group-{n}-20261011'
        g,c=[json.loads((d/name).read_text()) for name in ['goal.json','calibration.json']]
        if sha(canonical(c))!=g['calibrationHash']:raise ValueError('Calibration hash differs')
        definition={k:v for k,v in g.items() if k!='calibrationHash'}
        if c['scientificDefinitionHash']!=identity('calibration-science',definition):raise ValueError('Scientific definition differs')
        if not c['activationAllowed']:continue
        evidence.append((n,g,c))
    if len(evidence)<16:raise ValueError('Insufficient genuinely new goal supply')
    _,reference,cal=evidence[0];members=[]
    for n,g,c in evidence:
        if c['preregistrationHash']!=cal['preregistrationHash']:raise ValueError('Preregisration differs')
        members.append(dict(goalId=identity('goal-id',g),calibrationHash=g['calibrationHash'],normalizationNumerator=cal['levels'][0]['estimatedWorkMilliseconds'],normalizationDenominator=c['levels'][0]['estimatedWorkMilliseconds']))
    levels=[dict(requiredBackgrounds=l['requiredBackgrounds'],difficultyMicros=l['difficultyMicros']) for l in cal['levels'] if l['enabled'] and all(any(m['requiredBackgrounds']==l['requiredBackgrounds'] and m['enabled'] and m['challengeEffective'] and m['heldOutSuccesses']>0 and m['sampleCount']>=16 and m['difficultyMicros']*4<=l['difficultyMicros']*5 and l['difficultyMicros']*4<=m['difficultyMicros']*5 for m in c['levels']) for _,_,c in evidence)]
    intervals=[c['levels'][0]['wilson95PartsPerMillion'] for _,_,c in evidence]
    if max(x[0] for x in intervals)>min(x[1] for x in intervals):raise ValueError('Pass-rate intervals do not overlap')
    family=dict(schema='flypow-comparable-difficulty-family-v1',revision=1,**{k:reference[k] for k in ['graphRoot','modelRoot','parameterProfileHash','evaluatorVersion']},referenceGoalId=members[0]['goalId'],preregistrationHash=cal['preregistrationHash'],normalizationVersion='reference-work-r2-ratio-v1',members=members,levels=levels,limits=['24 disjoint new 12-cell downstream populations, outside all previous response/stimulus/off-target sets; predicates preregistered before outcomes.','Complete event kernels reuse the same model and inputs; independent predicates and new populations are not new biological discoveries or proof of independent goals.','Finite real training/held-out evidence: 20 inputs per goal. R2/R4 effective; R8/R16 disabled.','Cold-start family: never import old winner samples. Difficulty feedback still needs 16 real comparable successful rounds.','Solved goals are never renamed or repeated. Future supply requires a new calibrated, signed plan.'])
    validate_family(family)
    base=ROOT/'web/data/target-mining-v2'
    (base/'product-family-20261011.json').write_bytes(canonical(family)+b'\n')
    public=dict(schema='flybrain-calibrated-supply-v1',familyId=identity('comparable-difficulty-family',family),goals=[dict(goalId=m['goalId'],calibrationHash=m['calibrationHash'],path=f'/assets/data/target-mining-v2/product-group-{n}-20261011/goal.json') for (n,_,_),m in zip(evidence,members)],levels=levels,distinctGoals=len(evidence),officialDownloads=0,realSuccessfulNetworkRounds=0,minComparableSuccessfulRounds=16,payment=False,rewards=False)
    (base/'product-supply-20261011.json').write_bytes(canonical(public)+b'\n')
    draft=dict(schema='flypow-target-plan-revision-v1',source='preregistered-disjoint-downstream-product-20261011',append=[dict(goal=g,calibration=c) for _,g,c in evidence],families=[family])
    dest=ROOT/'data/prepared/mining-product-20261011'
    (dest/'future-plan-draft.json').write_bytes(canonical(draft)+b'\n')
    print(json.dumps(dict(distinctGoals=len(evidence),familyId=public['familyId'],levels=levels,officialDownloads=0)))
if __name__=='__main__':main()
