"""Independent, end-only evaluation of recorded states. No success override flags."""
import argparse,json,hashlib,sys,importlib.util
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
VERSION='2.1-friction-surface-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def folding_assistance_gates(cfg,topology,trace,attachments):
    spec=cfg['task_spec'];cap=spec['max_assisted_nodes']
    gates=dict(local_assistance_only=bool(trace) and all(
        len(r['vertex_ids'])<=cap and len(r['aim_positions_world_m'])==len(r['vertex_ids']) for r in trace),
        pinch_acquisition_local=bool(attachments) and all(e['max_initial_tcp_distance_m']<=.035 for e in attachments))
    if cfg['task_id']!='folded_transfer':return gates
    if spec.get('transfer_grasp_mode')!='adjacent_paired_patch':
        gates['paired_layers_held']=any(e.get('pinch_kind')=='paired_layers' and len(e['vertex_ids'])==2 for e in attachments)
        return gates
    nx,ny=topology['physical_grid']
    def corresponding_adjacent(ids):
        if len(ids)!=4 or any(type(i) is not int for i in ids) or len(set(ids))!=4:return False
        rows=sorted({i//nx for i in ids})
        return (len(rows)==2 and 0<=rows[0]<rows[1]<ny and rows[1]==rows[0]+1
                and set(ids)=={r*nx+c for r in rows for c in (0,nx-1)})
    patches=[e for e in attachments if e.get('pinch_kind')=='paired_layer_patch']
    gates['paired_layers_held']=bool(patches)
    gates['transfer_patch_topology_valid']=(cap==4 and bool(patches)
        and all(corresponding_adjacent(e['vertex_ids']) for e in patches)
        and all(len(e['vertex_ids'])==1 or e in patches for e in attachments))
    def local_patch(e):
        # Rigid hand-local offsets retain pairwise world distances; recompute
        # diameter independently instead of accepting the controller's summary.
        points=np.asarray(e.get('hand_local_offsets_m',[]),dtype=float)
        return bool(points.shape==(4,3) and np.isfinite(points).all()
            and np.linalg.norm(points[:,None]-points[None,:],axis=2).max()<=.04
            and e['max_initial_tcp_distance_m']<=.032)
    gates['transfer_patch_geometry_local']=bool(patches) and all(local_patch(e) for e in patches)
    # Every active trace must match the attachment in effect at that tick.
    # Single-point A-table folds remain permitted, never an unrecorded patch.
    active=None;index=0;ordered=sorted(attachments,key=lambda e:e['tick']);consistent=bool(trace)
    for row in trace:
        while index<len(ordered) and ordered[index]['tick']<row['tick']:
            active=ordered[index]['vertex_ids'];index+=1
        ids=row['vertex_ids']
        if ids:consistent=consistent and ids==active and (len(ids)==1 or corresponding_adjacent(ids))
    gates['transfer_patch_trace_valid']=bool(consistent)
    return gates

def plan_evidence(plans,events,allow_probes=False,allow_empty=False):
    """Separate recorded, unexecuted reachability probes from motion plans."""
    probes=[e for e in events if e['name']=='corner_approach_probe']
    probe_ids={e.get('planner_id') for e in probes}
    executed={e.get('planner_id') for e in events if e['name']=='planned_waypoint'}
    valid=(not probes or allow_probes) and len(probe_ids)==len(probes) and not (probe_ids&executed)
    for event in probes:
        plan=plans.get(event.get('planner_id'))
        valid=valid and plan is not None
        if plan is not None:
            valid=valid and event.get('success') is bool(plan['result'].get('success'))
            valid=valid and event.get('status')==plan['result'].get('status')
            valid=valid and event.get('goal')==plan['request'].get('tcp_world')
    motions={k:v for k,v in plans.items() if k not in probe_ids}
    gates={'curobo_probe_records_valid':bool(valid),
           'curobo_plans_valid':bool(all(p['result'].get('success') is True for p in motions.values())
                                    and (motions or allow_empty) and executed.issubset(motions))}
    metrics={'planner_queries':len(plans),'motion_plan_queries':len(motions),
             'reachability_probe_queries':len(probes),
             'rejected_reachability_probes':sum(e.get('success') is False for e in probes)}
    return gates,metrics
def grasp_metrics(data,events,dt):
    e={x['name']:x for x in events}
    required=['before_close','after_close','held','before_release','after_release','terminal_hold']
    if any(k not in e for k in required):return {},{'grasp_phases_complete':False}
    ticks=np.asarray(data['tick']);v=data['cloth_vertices'];q=data['qpos'][:,0]
    def ix(name):
        found=np.flatnonzero(ticks==e[name]['tick'])
        if len(found)!=1:raise ValueError('Event is not tied to exactly one recorded snapshot: '+name)
        return found[0]
    neighbours=np.asarray(e['before_close']['neighbours'],dtype=int)
    if neighbours.ndim!=1 or len(neighbours)<3 or len(set(neighbours.tolist()))!=len(neighbours):raise ValueError('Invalid material neighbourhood')
    before=ix('before_close');held=ix('held');br=ix('before_release');end=ix('terminal_hold')
    hold_indices=np.flatnonzero((ticks>=ticks[held]-round(.5/dt))&(ticks<=ticks[held]))
    release_indices=np.flatnonzero((ticks>=e['after_release']['tick'])&(ticks<=ticks[end]))
    local_before=float(np.median(v[before,neighbours,2]))
    hold_lifts=np.median(v[hold_indices][:,neighbours,2],axis=1)-local_before
    lift=float(hold_lifts.min());drop=float(np.median(v[br,neighbours,2]-v[end,neighbours,2]))
    gap=float(q[held,7:].sum())
    gates={'grasp_phases_complete':True,'physical_lift':lift>=.008,'held_for_half_second':len(hold_indices)>1 and ticks[hold_indices[0]]<=ticks[held]-.5/dt+5,
       'loaded_gripper_gap':.0002<=gap<=.03,'release_drop':drop>=.005,
       'released':bool((q[release_indices,7:]>=.035).all()),
       'release_persistence':(ticks[end]-e['after_release']['tick'])*dt>=1.-1e-8}
    return {'minimum_local_hold_lift_m':lift,'local_release_drop_m':drop,'held_finger_gap_m':gap,'neighbour_count':len(neighbours)},{k:bool(v) for k,v in gates.items()}
def evaluate(run):
    run=Path(run);cfg=json.loads((run/'config.json').read_text());summary=json.loads((run/'run_summary.json').read_text())
    gates={'no_halt':summary.get('halted') is None};metrics={};reason=None
    if not (run/'trajectory.npz').exists():
        return {'status':'failed','available':True,'success':False,'gates':dict(gates,trajectory_present=False),'metrics':metrics,'failed_gates':['trajectory_present'],'version':VERSION,'review_status':'SELF_REVIEWED_PROVISIONAL'}
    data=np.load(run/'trajectory.npz');events=json.loads((run/'events.json').read_text())
    ticks=data['tick'];gates['finite_trajectory']=all(np.isfinite(data[k]).all() for k in data.files)
    gates['monotonic_dense_snapshots']=bool(len(ticks)>1 and ticks[0]==0 and (np.diff(ticks)>0).all() and (np.diff(ticks)<=cfg['record_stride']).all())
    rows=[json.loads(x) for x in (run/'physics.jsonl').read_text().splitlines()]
    gates['every_physics_step_recorded']=[x['tick'] for x in rows]==list(range(1,int(ticks[-1])+1))
    gates['command_observation_alignment']=all(x['command_applied_from_tick']==x['tick']-1 for x in rows)
    gates['cloth_health']=bool(rows) and all(x['cloth_health']['max_edge_ratio']<=cfg['gates']['edge_ratio'] and x['cloth_health']['max_table_vertex_penetration_m']<=cfg['gates']['table_penetration_m'] for x in rows)
    audit=json.loads((run/'initial_geometry_audit.json').read_text())
    assisted=cfg.get('assisted_grasp',{}).get('enabled',False)
    if assisted:
        gates['assistance_disclosed']=summary.get('grasp_assistance')==cfg['assisted_grasp'] and summary['attached_cloth'] is True
        gates['no_runtime_cloth_teleport']=audit['pinned_vertices']==0 and audit['runtime_pose_setters']==0 and summary['runtime_cloth_setters']==0
    else:gates['no_pins_no_runtime_setters']=audit['pinned_vertices']==0 and audit['runtime_pose_setters']==0 and summary['runtime_cloth_setters']==0 and summary['attached_cloth'] is False
    gates['fk_verified']=(run/'fk_audit.json').exists()
    plans={int(p.stem):json.loads(p.read_text()) for p in sorted((run/'plans').glob('*.json'))}
    g,m=plan_evidence(plans,events,allow_probes=cfg.get('task_spec',{}).get('batch_id') in ('tabletop_v2','folding_v3','fixtures_v4'),allow_empty=cfg['task_id']=='hold')
    gates.update(g);metrics.update(m);metrics['physics_ticks']=int(ticks[-1]);metrics['duration_s']=float(ticks[-1]*cfg['dt'])
    if cfg.get('grasp_probe_only'):
        gates['probe_sequence_complete']=any(e['name']=='contact_probe_complete' for e in events)
    elif cfg['task_id'] in ['corner_lift','smooth']:
        m,g=grasp_metrics(data,events,cfg['dt']);metrics.update(m);gates.update(g)
        if cfg['task_id']=='smooth':
            sys.path.insert(0,str(ROOT/'runtime'))
            spec=importlib.util.spec_from_file_location('_cloth_union_metrics',ROOT/'runtime/evaluate.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text());e={x['name']:x for x in events}
            if 'settled' not in e or 'after_release' not in e:gates['smooth_phases_complete']=False
            else:
                initial_ix=int(np.flatnonzero(ticks==e['settled']['tick'])[0]);initial=mod.metrics(data['cloth_vertices'][initial_ix],topology,cfg)
                indices=np.flatnonzero(ticks>=e['after_release']['tick']);selected=indices[np.unique(np.rint(np.linspace(0,len(indices)-1,6)).astype(int))]
                terminal=[mod.metrics(data['cloth_vertices'][i],topology,cfg) for i in selected]
                fine=mod.metrics(data['cloth_vertices'][-1],topology,cfg,4096)
                metrics.update(initial_coverage=initial['coverage'],final_coverage=terminal[-1]['coverage'],coverage_gain=terminal[-1]['coverage']-initial['coverage'])
                gates.update(coverage=all(m['coverage']>=.93 for m in terminal),coverage_gain=metrics['coverage_gain']>=.08,
                    height=all(m['height_q95_m']<=.015 for m in terminal),
                    on_table=all(m['on_table_xy_fraction']==1. for m in terminal),
                    metric_converged=abs(fine['coverage']-terminal[-1]['coverage'])<=.002)
            # Spreading intentionally lowers the held corner before release.
            # Release-drop is a lift-probe criterion, not a valid spreading criterion.
            gates.pop('release_drop',None)
    elif cfg['task_id']=='l_table_transfer_flatten':
        from l_table_task import task_metrics
        topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
        metrics['initial']=task_metrics(data['cloth_vertices'][0],topology,cfg)
        metrics['final']=task_metrics(data['cloth_vertices'][-1],topology,cfg)
        names=[e['name'] for e in events]
        required=['acquired','drag_complete','hanging_complete','transfer_complete','lay_down_complete','task_complete','terminal_hold']
        gates['task_stages_complete']=all(name in names for name in required)
        gates['task_stages_in_order']=gates['task_stages_complete'] and [names.index(n) for n in required]==sorted(names.index(n) for n in required)
        final=metrics['final']
        # These are coarse visual-demo diagnostics, not a contact-grasp benchmark.
        gates['cloth_on_destination']=final['target_surface_vertex_fraction']>=.90
        gates['visually_spread']=final['projected_area_fraction']>=.75 and final['height_p95_m']<=.03
        metrics['assessment_scope']='Friction-only demonstration with unchanged coarse task diagnostics; video review required.'
    elif cfg.get('task_spec',{}).get('batch_id') in ('tabletop_v2','fixtures_v4'):
        if cfg['task_spec']['batch_id']=='fixtures_v4':
            from fixtures_v4.metrics import task_result
        else:
            from tabletop_v2.metrics import task_result
        topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
        m,g=task_result(data,events,topology,cfg);metrics.update(m);gates.update(g)
    elif cfg.get('task_spec',{}).get('batch_id')=='folding_v3':
        from folding_v3.metrics import task_result
        topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
        m,g=task_result(data,events,topology,cfg);metrics.update(m);gates.update(g)
        attachments=[e for e in events if e['name']=='contact_grasp_verified']
        if cfg['task_id']=='unfold_half':
            nx,ny=topology['physical_grid']
            gates['upper_layer_grasped']=any(e.get('pinch_kind')=='upper_layer' and all(i%nx>nx//2 for i in e['vertex_ids']) for e in attachments)
    elif cfg['task_id']!='hold':reason='Evaluator not implemented for this task';gates['task_supported']=False
    from contact_grasp import evaluate_contact
    contact_audit=json.loads((run/'contact_audit.json').read_text())
    topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
    m,g=evaluate_contact(data,events,cfg,contact_audit,topology);metrics.update(m);gates.update(g)
    gates['ipc_friction_enabled']=contact_audit.get('ipc_friction_enabled') is True
    gates['constraint_audit_every_step']=bool(rows) and all(
        x['cloth_health'].get('constrained_vertices')==0 and x['cloth_health'].get('assisted_grasp_used') is False for x in rows)
    success=all(gates.values()) and reason is None
    hashes={name:sha(run/name) for name in ['config.json','trajectory.npz','physics.jsonl','events.json','source_manifest.json','run_summary.json']}
    hashes.update({str(p.relative_to(run)):sha(p) for p in sorted((run/'plans').glob('*.json'))})
    if assisted and (run/'grasp_constraints.jsonl').exists():hashes['grasp_constraints.jsonl']=sha(run/'grasp_constraints.jsonl')
    return {'status':'success' if success else 'failed','available':reason is None,'success':success,'unavailable_reason':reason,
        'version':VERSION,'evaluator_sha256':sha(__file__),'gates':gates,'failed_gates':[k for k,v in gates.items() if not v],
        'metrics':metrics,'input_sha256':hashes,'review_status':'SELF_REVIEWED_PROVISIONAL','assisted_grasp':assisted,
        'pure_contact_grasp_verified':bool(gates.get('physical_acquisitions_verified') and gates.get('no_cloth_constraints') and gates.get('constraint_audit_every_step') and not cfg['negative_control']),
        'expert_eligible':bool(success and not cfg.get('grasp_probe_only')),
        'limitations':('Local kinematic grasp assistance; success does not establish friction-only gripping. ' if assisted else '')+'Synthetic FEM material, one full articulated Franka. No real-robot or cross-material generalization claim.'}
def main():
    p=argparse.ArgumentParser();p.add_argument('run');a=p.parse_args()
    sources={'evaluate.py':Path(__file__),'contact_grasp.py':ROOT/'contact_grasp.py','l_table_task.py':ROOT/'l_table_task.py',
             'runtime/evaluate.py':ROOT/'runtime/evaluate.py','runtime/table_geometry.py':ROOT/'runtime/table_geometry.py'}
    if json.loads((Path(a.run)/'config.json').read_text()).get('task_spec',{}).get('batch_id')=='tabletop_v2':
        for source in (ROOT/'tabletop_v2').glob('*.py'):
            sources['tabletop_v2/'+source.name]=source
    if json.loads((Path(a.run)/'config.json').read_text()).get('task_spec',{}).get('batch_id')=='folding_v3':
        for source in (ROOT/'folding_v3').glob('*.py'):
            sources['folding_v3/'+source.name]=source
    if json.loads((Path(a.run)/'config.json').read_text()).get('task_spec',{}).get('batch_id')=='fixtures_v4':
        for source in (ROOT/'fixtures_v4').glob('*.py'):
            sources['fixtures_v4/'+source.name]=source
    hashes={name:sha(source) for name,source in sources.items()}
    bundle=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    archive=Path(a.run)/'evaluation_code'/bundle[:12]
    for name,source in sources.items():
        dest=archive/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if sha(dest)!=hashes[name]:raise ValueError('Archived evaluator source changed: '+name)
        else:dest.write_bytes(source.read_bytes())
    r=evaluate(a.run)
    r.update(evaluator_bundle_sha256=bundle,evaluator_source_root=str(archive.resolve()),evaluator_source_sha256=hashes)
    (Path(a.run)/'evaluation.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
