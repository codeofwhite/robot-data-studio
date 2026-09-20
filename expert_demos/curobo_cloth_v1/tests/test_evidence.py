import unittest,sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate import grasp_metrics
from render_replay import exact_frames
from profiles import configuration
from collision_model import pad_spheres
from scene_adapter import verify_scene_sources,cloth_mapping,sha
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from safety import check_adjacent_contact_configuration,approved_adjacent_pairs,Halted
from runner import scene_grasp_goal,validate_scene_hover_plan
from publish import matched_scene_configuration,verify_scene_pair
from robot import Robot
from ipc_state_sync import finite_difference
from types import SimpleNamespace
class EvidenceTests(unittest.TestCase):
    def test_original_l_table_preparation_includes_regrasp_opening(self):
        from unittest.mock import patch
        import runner
        def bind(out,cfg,scene,robot):
            cfg['task_spec']={'id':'l_table_transfer_flatten'}
            cfg['scene_binding']={'scene':{'asset_id':'SCN-test','version':1}}
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'run'
            args=['runner.py','--scene','l_table_transfer_mild','--task','l_table_transfer_flatten',
                  '--visual-demo-profile','--prepare-only','--output',str(out)]
            with patch.object(sys,'argv',args),patch.object(runner,'bind_scene',side_effect=bind),patch.object(runner,'prepare'):
                runner.main()
            cfg=json.loads((out/'config.json').read_text())
            self.assertEqual(cfg['approach_finger_position_m'],.035)
            self.assertEqual(cfg['dt'],.01)
            self.assertEqual(cfg['assisted_grasp']['strength_rate'],625.)
    def test_l_table_empty_corner_and_both_slabs(self):
        from table_geometry import on_table_xy,table_vertex_penetration,segment_hits_table
        cfg={'tables':[{'position':[0,.4,.755],'half_extents':[.7,.3,.025]},
                       {'position':[.4,-.3,.755],'half_extents':[.3,.4,.025]}]}
        vertices=np.array([[-.2,-.2,.755],[0,.4,.775],[.4,-.3,.775]])
        np.testing.assert_array_equal(on_table_xy(vertices,cfg),[False,True,True])
        self.assertEqual(table_vertex_penetration(vertices[:1],cfg),0.)
        self.assertAlmostEqual(table_vertex_penetration(vertices[1:],cfg),.005)
        self.assertFalse(segment_hits_table([-.2,-.2,.9],[-.2,-.2,.7],cfg))
        self.assertTrue(segment_hits_table([.4,-.3,.9],[.4,-.3,.7],cfg))
        self.assertTrue(segment_hits_table([0,.4,.9],[0,.4,.7],cfg))
    def test_flat_cloth_on_wrong_table_is_not_transferred(self):
        from l_table_task import task_metrics
        cfg={'table_height':.78,'task_spec':{'target_region_xy_m':[[.11,-.69],[.69,.09]]}}
        topology={'flat_area_m2':.12}
        good=np.array([[x,y,.783] for y in [-.35,.05] for x in [.21,.51]])
        result=task_metrics(good,topology,cfg)
        self.assertEqual(result['target_vertex_fraction'],1.)
        self.assertAlmostEqual(result['projected_area_fraction'],1.)
        self.assertEqual(task_metrics(good+[-.5,.6,0],topology,cfg)['target_vertex_fraction'],0.)
    def test_destination_requires_cloth_at_the_table_surface(self):
        from l_table_task import task_metrics
        cfg={'table_height':.78,'task_spec':{'target_region_xy_m':[[.11,-.69],[.69,.09]]}}
        topology={'flat_area_m2':.12}
        good=np.array([[x,y,.783] for y in [-.35,.05] for x in [.21,.51]])
        self.assertEqual(task_metrics(good,topology,cfg)['target_surface_vertex_fraction'],1.)
        for dz in [-.1,.1]:
            result=task_metrics(good+[0,0,dz],topology,cfg)
            self.assertEqual(result['target_vertex_fraction'],1.)
            self.assertEqual(result['target_surface_vertex_fraction'],0.)
    def test_hover_from_different_mount_or_diagnostic_rejected(self):
        cfg={'bases':[[-.72,.12,.802]],'yaws':[0.],'scene_binding':{'scene':{'asset_id':'original','version':1},'collision_meshes':{'table':{'sha256':'same'}}}}
        plan={'success':True,'grasp_seed':{},'metadata':{'scene':cfg['scene_binding']['scene'],'collision_mesh_sha256':{'table':'same'},
            'world':{'mesh':{'table':{'pose':[.72,-.12,-.802,1.,0,0,0]}}}}}
        validate_scene_hover_plan(plan,cfg)
        plan['metadata']['world']['mesh']['table']['pose'][1]=.03
        with self.assertRaisesRegex(ValueError,'different robot base'):validate_scene_hover_plan(plan,cfg)
        plan['diagnostic_only']=True
        with self.assertRaisesRegex(ValueError,'Diagnostic plans'):validate_scene_hover_plan(plan,cfg)
    def test_scene_gate_rejects_crashed_or_lifting_no_close_control(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'positive';n=Path(folder)/'negative'
            for r,negative in [(p,False),(n,True)]:
                r.mkdir();(r/'config.json').write_text(json.dumps({'scene_binding':{'snapshot_root':str(r/'scene_source')},'negative_control':negative}))
            (p/'evaluation.json').write_text(json.dumps({'success':True,'gates':{'no_halt':True}}))
            e={'success':False,'gates':{'grasp_phases_complete':False,'no_halt':False,'physical_lift':False,'loaded_gripper_gap':False}}
            (n/'evaluation.json').write_text(json.dumps(e))
            with self.assertRaisesRegex(ValueError,'finish without a halt'):verify_scene_pair(p,n)
            e['gates'].update(grasp_phases_complete=True,no_halt=True,physical_lift=True)
            (n/'evaluation.json').write_text(json.dumps(e))
            with self.assertRaisesRegex(ValueError,'reject physical grasp/lift'):verify_scene_pair(p,n)
            e['gates'].update(physical_lift=False,cloth_health=False)
            (n/'evaluation.json').write_text(json.dumps(e))
            with self.assertRaisesRegex(ValueError,'unrelated failed gates'):verify_scene_pair(p,n)
    def test_two_arm_states_remain_separate_and_missing_target_rejected(self):
        def arm(value):
            hand=SimpleNamespace(get_quat=lambda:np.array([1.,0,0,0]),get_pos=lambda:np.array([value,0.,1.]))
            return SimpleNamespace(get_link=lambda name:hand,get_qpos=lambda:np.full(9,value),
                get_dofs_velocity=lambda:np.full(9,value+.1),get_dofs_control_force=lambda:np.full(9,value+.2))
        robot=Robot.__new__(Robot);robot.cfg={'tcp_offset':[0,0,.1]};robot.arms=[arm(.1),arm(.2)];robot.halted=None
        states=robot.state()
        np.testing.assert_allclose(states[0]['joints'],.1);np.testing.assert_allclose(states[1]['joints'],.2)
        np.testing.assert_allclose(states[1]['joint_velocity'],.3)
        with self.assertRaisesRegex(ValueError,'Every configured arm'):robot.tick([np.zeros(9)])
        with self.assertRaisesRegex(ValueError,'Every configured arm'):robot.tick([np.zeros(9),np.full(9,np.nan)])
        previous=np.zeros((2,9));current=np.stack([np.full(9,.004),np.full(9,.008)])
        np.testing.assert_allclose(finite_difference(current,previous,.004),np.stack([np.ones(9),np.full(9,2.)]))
    def test_matched_scene_normalizes_only_run_paths(self):
        def cfg(root):
            return {'scene_binding':{'snapshot_root':root+'/scene_source','scene':{'asset_id':'SCN-original','version':1},
                'collision_meshes':{'part_sha256':{root+'/part.obj':'same-digest'}}},'negative_control':False,'max_tcp_speed':.08}
        left=cfg('/tmp/positive');right=cfg('/tmp/negative');right['negative_control']=True
        self.assertEqual(matched_scene_configuration(left),matched_scene_configuration(right))
        right['max_tcp_speed']=.09
        self.assertNotEqual(matched_scene_configuration(left),matched_scene_configuration(right))
        right['max_tcp_speed']=.08;right['scene_binding']['scene']['version']=2
        self.assertNotEqual(matched_scene_configuration(left),matched_scene_configuration(right))
    def test_scene_grasp_uses_current_material_vertex(self):
        rest=np.array([[x*.03,y*.03,0.] for y in range(3) for x in range(3)])
        current=rest+[-.3,-.5,.7]
        cfg={'table':{'position':[0,0,.75],'half_extents':[.9,.48,.03]},'table_height':.78,
            'scene_grasp_seed':{'vertex_index':3,'quaternion_wxyz':[1,0,0,0],'approach_offset_m':[0,-.06,0]}}
        result=scene_grasp_goal(current,{'physical_grid':[3,3],'rest_vertices':rest.tolist()},cfg)
        np.testing.assert_array_equal(result['position'],current[3]);self.assertEqual(len(result['neighbours']),4)
        cfg['scene_grasp_seed']['tcp_contact_offset_world_m']=[0,0,.003]
        result=scene_grasp_goal(current,{'physical_grid':[3,3],'rest_vertices':rest.tolist()},cfg)
        np.testing.assert_allclose(result['position'],current[3]+[0,0,.003])
        np.testing.assert_array_equal(result['material_position'],current[3])
        cfg['scene_grasp_seed']['vertex_index']=4
        with self.assertRaisesRegex(ValueError,'material boundary'):scene_grasp_goal(current,{'physical_grid':[3,3],'rest_vertices':rest.tolist()},cfg)
    def fixed_scene_audit(self,arms):
        names=sorted({'floor','table','cloth'}|{a+'/'+n for a in arms for n in ['link'+str(i) for i in range(8)]+['left_finger','right_finger']})
        bodies={n:{'element_id':i,'geometry_contact_ids':[i],'geometry_slot_ids':[i]} for i,n in enumerate(names)}
        fixed={'floor','table'}|{a+'/link0' for a in arms};pairs={'|'.join(sorted((a,b))) for a in fixed for b in fixed if a!=b}
        adjacent=approved_adjacent_pairs(arms);models={}
        for i,a in enumerate(names):
            for b in names[i:]:
                key=a+'|'+b;ref={'friction':.6,'resistance':1.,'config':{}}
                models[key]={'element_ids':[bodies[a]['element_id'],bodies[b]['element_id']],'enabled':key not in adjacent|pairs,**ref,'reference':dict(ref)}
        return {'robot_names':arms,'configured_robot_names':arms,'bodies':bodies,'original_scene':True,'fixed_base_robots':arms,
            'fixed_foundation_pairs':list(pairs),'native_adjacent_pairs':list(adjacent),'native_adjacent_collision_enabled':False,'actual_pair_models':models}
    def test_dual_fixed_assembly_and_all_moving_contacts(self):
        audit=self.fixed_scene_audit(['left','right']);check_adjacent_contact_configuration(audit)
        key='left/left_finger|table';audit['actual_pair_models'][key]['enabled']=False
        with self.assertRaisesRegex(Halted,'Unapproved IPC contact mask'):check_adjacent_contact_configuration(audit)
    def test_cannot_disguise_moving_link_as_fixed_foundation(self):
        audit=self.fixed_scene_audit(['arm']);audit['fixed_foundation_pairs'].append('arm/link1|floor')
        with self.assertRaisesRegex(Halted,'moving body'):check_adjacent_contact_configuration(audit)
    def test_changed_scene_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'scene.usda';p.write_text('source scene')
            binding={'snapshot_root':folder,'source_sha256':{'scene.usda':sha(p)}}
            self.assertTrue(verify_scene_sources(binding));p.write_text('different scene')
            with self.assertRaisesRegex(ValueError,'dependency changed'):verify_scene_sources(binding)
    def test_cloth_mapping_preserves_source_nodes_and_material_area(self):
        from pxr import Usd,UsdGeom,Vt,Sdf
        s=Usd.Stage.CreateInMemory();m=UsdGeom.Mesh.Define(s,'/Cloth')
        points=np.array([[x,y,.8+.03*x] for y in np.linspace(0,.4,5) for x in np.linspace(0,.6,7)],np.float32)
        m.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
        UsdGeom.PrimvarsAPI(m).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'vertex').Set(Vt.Vec2fArray.FromNumpy(points[:,:2]))
        t=cloth_mapping(s,{'prim':'/Cloth','size_m':[.6,.4]},stride=2)
        current=np.asarray(t['initial_vertices']);mapped=np.sum(current[np.asarray(t['visual_indices'])]*np.asarray(t['visual_weights'])[:,:,None],axis=1)
        np.testing.assert_array_equal(mapped[t['source_vertex_ids']],current)
        np.testing.assert_allclose(mapped,points,atol=1e-7)
        self.assertAlmostEqual(t['flat_area_m2'],.24)
        json.dumps(t,allow_nan=False)
    def test_missing_video_tick_rejected(self):
        with self.assertRaises(ValueError):exact_frames([0,5,10,20,30,50,55,60],60,.004,10)
    def test_video_uses_next_action(self):
        rows=exact_frames(np.arange(0,101,5),100,.004,10)
        self.assertEqual([r['applied_command_row_tick'] for r in rows],[1,26,51,76])
        self.assertEqual(rows[-1]['simulation_time_s'],rows[-1]['video_time_s'])
    def test_incomplete_terminal_action_chunk_is_not_exported(self):
        rows=exact_frames(np.arange(0,106,5),105,.004,10)
        self.assertEqual(rows[-1]['tick'],75)
    def test_pad_cover_contains_box_boundary(self):
        spheres=pad_spheres(1);centres=np.asarray([s['center'] for s in spheres]);r=np.asarray([s['radius'] for s in spheres])
        points=np.array([[x,y,z] for x in np.linspace(-.0085,.0085,13) for y in np.linspace(0,.008,9) for z in np.linspace(.0355,.0535,13)])
        self.assertTrue((np.min(np.linalg.norm(points[:,None]-centres[None],axis=2)-r[None],axis=1)<=1e-12).all())
    def test_material_mass_units(self):
        c=configuration();self.assertAlmostEqual(c['cloth']['rho'],200.)
        self.assertAlmostEqual(c['nominal_mass_kg'],.012288)
    def test_no_close_control_fails_even_when_cloth_rises(self):
        ticks=np.arange(0,501,5);v=np.zeros((len(ticks),4,3));q=np.zeros((len(ticks),1,9));q[:,:,7:]=.04
        v[(ticks>=100)&(ticks<=250),:,2]=.02
        events=[{'name':n,'tick':t,'neighbours':[0,1,2]} for n,t in [('before_close',0),('after_close',25),('held',250),('before_release',250),('after_release',250),('terminal_hold',500)]]
        m,g=grasp_metrics({'tick':ticks,'cloth_vertices':v,'qpos':q},events,.004)
        json.dumps({'metrics':m,'gates':g},allow_nan=False)
        self.assertFalse(g['loaded_gripper_gap'])
        self.assertFalse(all(g.values()))
    def test_missing_phase_cannot_pass(self):
        self.assertFalse(all(grasp_metrics({},[],.004)[1].values()))
if __name__=='__main__':unittest.main()
