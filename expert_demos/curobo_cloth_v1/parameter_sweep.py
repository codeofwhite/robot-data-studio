"""Generate candidates. Never equate a configuration with a verified demonstration."""
import argparse,json,hashlib
from pathlib import Path
from profiles import MATERIALS,INITIALS,configuration,ROOT
def candidates():
    tasks=json.loads((ROOT/'tasks.json').read_text())['tasks'];rows=[]
    for task in tasks:
        for material in MATERIALS:
            for initial in INITIALS:
                rows.append({'id':f"{task['id']}-{material}-{initial}",'task':task['id'],'material':material,'initial':initial,
                   'profile':task['profile'],'required_repetitions':3,'attempts':0,'successful_runs':0,
                   'status':'candidate' if task['recipe'] else 'blocked_recipe_or_profile',
                   'criteria':task['criteria'],'config':configuration(material,initial)})
    return rows
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows=candidates()
    probes=[]
    for param,values in {'gsm':[80,120,320],'thickness':[.0004,.0006,.0012],'E':[30000,60000,150000],
                         'bending':[.004,.01,.02],'cloth_friction':[.35,.6,.75],
                         'table_friction':[.35,.6,.8],'gripper_friction':[.35,.6,.8]}.items():
        for value in values:
            probes.append({'parameter':param,'value':value,'baseline':'medium-nominal',
              'status':'not_run','mass_rule':'hold gsm fixed when changing thickness; density is derived',
              'numerical_controls':{'dt_s':.004,'grid_n':25},'visual_parameters_independent':True})
    payload={'schema_version':1,'candidate_count':len(rows),'requested_runs':len(rows)*3,
      'gate':'No batch before positive grasp + no-close negative control + replay/traceability checks pass for current code/config.',
      'candidates':rows,'single_variable_probes':probes,'review_status':'SELF_REVIEWED_PROVISIONAL'}
    (out/'candidates.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    print(json.dumps({'candidates':len(rows),'single_variable_probes':len(probes),'successful_runs':0}))
if __name__=='__main__':main()
