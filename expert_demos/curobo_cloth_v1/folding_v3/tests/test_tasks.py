"""Behavioral checks: wrong layer/shape and rigid turnover must not pass eversion."""
import sys, unittest,json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
from folding_v3 import catalog
from folding_v3.build_scenes import rectangular_points,task_spec
from folding_v3.garment_assets import prepare_garment
from folding_v3.metrics import measure,fold_satisfactory,garment_measure,satisfactory,task_result
from folding_v3.actions import opening_target,acquisition_patch_diameter,Controller
from folding_v3.folded_transfer import folded_destination,probe_route_pose,transfer_grasp_candidates,transfer_patch_candidates,transfer_patch_alignment,execute as transfer_execute
from evaluate import folding_assistance_gates

def rectangle(angle):
    c=dict(catalog()['tasks']['towel_half_fold']['variants']['v001'],initial_fold_deg=angle)
    v=rectangular_points(c).reshape(61,81,3)[::4,::4].reshape(-1,3)
    # Last source row (60) is present: 21 x 16 mesh.
    faces=[]
    for y in range(15):
        for x in range(20):
            a=y*21+x;faces.extend([[a,a+1,a+22],[a,a+22,a+21]])
    top=dict(faces=faces,flat_area_m2=.12,physical_grid=[21,16])
    cfg=dict(table_height=.78,task_spec=task_spec('towel_half_fold','v001'))
    return v,top,cfg

class Tasks(unittest.TestCase):
    def test_patch_alignment_selects_corresponding_pair_and_skips_local_fold(self):
        v,top,_=rectangle(179)
        self.assertIsNone(transfer_patch_alignment(v,top))
        v[np.arange(len(v))%21>10,0]+=.025
        self.assertFalse(transfer_patch_candidates(v,top))
        selected=transfer_patch_alignment(v,top);moving=selected['moving_vertex'];stationary=selected['stationary_vertex']
        self.assertEqual(moving//21,stationary//21)
        self.assertEqual((moving%21,stationary%21),(20,0))
        ids=selected['vertex_ids'];pairs=[ids[:2],ids[2:]]
        self.assertAlmostEqual(np.linalg.norm(v[moving]-v[stationary]),max(np.linalg.norm(v[a]-v[b]) for a,b in pairs))
    def fold_controller_fixture(self,local=True):
        from types import SimpleNamespace
        v,top,cfg=rectangle(179);cfg.update(task_id='folded_transfer',task_spec=task_spec('folded_transfer','v003'))
        if not local:v[np.arange(len(v))%21>10,0]+=.025
        self.assertTrue(fold_satisfactory(measure(v,top,cfg)))
        c=Controller.__new__(Controller);c.cfg=cfg;c.scene=SimpleNamespace(topology=top,cloth_vertices=lambda:v)
        actions=[];events=[]
        c.align_pair=lambda moving,stationary:actions.append((moving,stationary))
        c.fold_pair=lambda moving,stationary,stage:actions.append((moving,stationary))
        c.mark=lambda name,**extra:events.append(dict(name=name,**extra))
        return c,actions,events
    def test_fold_uses_at_most_one_local_correction_before_completion(self):
        c,actions,events=self.fold_controller_fixture(local=False);calls=[]
        def selector(vertices,topology):
            calls.append(True);return transfer_patch_alignment(vertices,topology)
        c.fold(local_patch_selector=selector)
        self.assertEqual(len(calls),1);self.assertEqual(len(actions),3)
        self.assertEqual(events[-1]['name'],'fold_complete')
        correction=[e for e in events if e['name']=='transfer_patch_alignment_complete']
        self.assertEqual(len(correction),1)
        # The stubbed action did not change the cloth; the controller must not
        # retry indefinitely or label its unsuccessful correction as a grasp.
        self.assertGreater(correction[0]['after_patch_diameter_m'],.04)
        self.assertFalse(transfer_patch_candidates(c.scene.cloth_vertices(),c.scene.topology))
    def test_local_fold_and_legacy_calls_add_no_alignment(self):
        for local,selector in [(True,transfer_patch_alignment),(False,None)]:
            c,actions,events=self.fold_controller_fixture(local=local);c.fold(local_patch_selector=selector)
            self.assertEqual(len(actions),2)
            self.assertFalse(any(e['name'].startswith('transfer_patch_alignment') for e in events))
    def test_transfer_rejects_bad_post_correction_locality_and_fold(self):
        from unittest.mock import patch
        from safety import Halted
        for damage in ['locality','fold']:
            c,actions,events=self.fold_controller_fixture(local=False)
            if damage=='fold':c.scene.cloth_vertices()[20,0]+=.2
            # Exercise execute's actual post-fold gates without a robot. No
            # planner exists, so passing a rejected state downstream is an error.
            c.fold=lambda **kwargs:None
            with patch('folding_v3.folded_transfer.Controller',return_value=c):
                with self.assertRaisesRegex(Halted,'No aligned local patch' if damage=='locality' else 'Folding on A'):
                    transfer_execute(None,None,None)
    def patch_evidence(self,ids=None):
        v,top,_=rectangle(179);ids=ids or [147,167,168,188]
        cfg=dict(task_id='folded_transfer',task_spec=task_spec('folded_transfer','v003'))
        points=v[ids];offsets=points-points.mean(0)
        event=dict(name='assisted_grasp_attached',tick=10,vertex_ids=ids,pinch_kind='paired_layer_patch',
                   hand_local_offsets_m=offsets.tolist(),max_initial_tcp_distance_m=float(np.linalg.norm(offsets,axis=1).max()))
        trace=[dict(tick=11,vertex_ids=ids,aim_positions_world_m=points.tolist()),
               dict(tick=12,vertex_ids=[],aim_positions_world_m=[])]
        return v,top,cfg,event,trace
    def test_four_node_patch_valid_and_centered(self):
        v,top,cfg,event,trace=self.patch_evidence()
        self.assertEqual(transfer_patch_candidates(v,top)[0],(147,167,168,188))
        self.assertLess(acquisition_patch_diameter(event['vertex_ids'],v,cfg['task_spec']),.04)
        self.assertTrue(all(folding_assistance_gates(cfg,top,trace,[event]).values()))
        self.assertEqual(task_spec('folded_transfer','v002')['max_assisted_nodes'],2)
        self.assertEqual(task_spec('garment_inside_out','v004')['max_assisted_nodes'],1)
    def test_patch_rejects_wrong_layer_nonadjacent_and_duplicate_indices(self):
        for ids in [[147,148,168,169],[147,167,189,209],[147,167,168,168],[-21,-1,0,20]]:
            v,top,cfg,event,trace=self.patch_evidence(ids)
            gates=folding_assistance_gates(cfg,top,trace,[event])
            self.assertFalse(gates['transfer_patch_topology_valid'],ids)
    def test_patch_spacing_checked_before_any_robot_approach(self):
        v,top,cfg,event,trace=self.patch_evidence();v[188,2]+=.05
        self.assertNotIn((147,167,168,188),transfer_patch_candidates(v,top))
        controller=Controller.__new__(Controller);controller.cfg=cfg
        class Scene:
            def cloth_vertices(self):return v
        controller.scene=Scene()
        # No robot, recorder or planner exists in this fixture. Validation must
        # halt before any of them is touched, including retreat/open commands.
        from safety import Halted
        with self.assertRaisesRegex(Halted,'4 cm'):
            controller.acquire(patch_indices=event['vertex_ids'],kind='paired_layer_patch')
        event['hand_local_offsets_m'][-1][2]+=.05
        self.assertFalse(folding_assistance_gates(cfg,top,trace,[event])['transfer_patch_geometry_local'])
    def test_legacy_budget_and_undeclared_patch_rejected(self):
        v,top,cfg,event,trace=self.patch_evidence();cfg['task_spec']=task_spec('folded_transfer','v002')
        with self.assertRaisesRegex(ValueError,'many assisted nodes'):
            acquisition_patch_diameter(event['vertex_ids'],v,cfg['task_spec'])
        gates=folding_assistance_gates(cfg,top,trace,[event])
        self.assertFalse(gates['local_assistance_only']);self.assertFalse(gates['paired_layers_held'])
        event['vertex_ids']=event['vertex_ids'][:2];event['pinch_kind']='paired_layers'
        trace[0]['vertex_ids']=event['vertex_ids'];trace[0]['aim_positions_world_m']=trace[0]['aim_positions_world_m'][:2]
        self.assertTrue(all(folding_assistance_gates(cfg,top,trace,[event]).values()))
        cfg['task_spec']=task_spec('folded_transfer','v003')
        self.assertFalse(folding_assistance_gates(cfg,top,trace,[event])['paired_layers_held'])
    def test_patch_rejects_outside_capture_and_unrecorded_trace(self):
        _,top,cfg,event,trace=self.patch_evidence();event['max_initial_tcp_distance_m']=.033
        self.assertFalse(folding_assistance_gates(cfg,top,trace,[event])['transfer_patch_geometry_local'])
        event['max_initial_tcp_distance_m']=.02;trace[0]['vertex_ids']=[168,188,189,209]
        self.assertFalse(folding_assistance_gates(cfg,top,trace,[event])['transfer_patch_trace_valid'])
    def test_restored_final_fold_does_not_hide_in_transit_opening(self):
        flat,top,cfg=rectangle(0);folded,_,_=rectangle(179)
        cfg.update(task_id='folded_transfer',dt=.01,task_spec=task_spec('folded_transfer','v002'),
                   tables=[dict(id='A',position=[0,.4,.755],half_extents=[.7,.3,.025])])
        on_a=folded.copy();on_a[:,:2]+=np.array([-.2,.3])-on_a[:,:2].mean(0)
        in_air=on_a.copy();in_air[:,2]+=.3
        on_b=folded.copy();on_b[:,:2]+=np.array([.32,-.28])-on_b[:,:2].mean(0)
        data=dict(tick=np.array([50,100,130,150,200,220,240,300]),
                  cloth_vertices=np.array([flat,on_a,in_air,in_air,on_b,on_b,on_b,on_b]))
        events=[dict(name=name,tick=tick) for name,tick in
                [('task_start',50),('fold_complete',100),('transfer_complete',150),('terminal_hold',200)]]
        _,good=task_result(data,events,top,cfg)
        self.assertTrue(good['task_goal_reached'])
        self.assertTrue(good['fold_retained_during_transfer'])
        data['cloth_vertices'][2,20,2]+=.10
        _,opened=task_result(data,events,top,cfg)
        self.assertTrue(opened['task_goal_reached'])
        self.assertTrue(opened['released_goal_persists'])
        self.assertFalse(opened['fold_retained_during_transfer'])
    def test_transfer_prefers_balanced_local_pair_and_rejects_separated_layers(self):
        v,t,c=rectangle(179)
        candidates=transfer_grasp_candidates(v,t)
        self.assertIn(candidates[0][0]//21,[7,8])
        for row in [7,8]:v[row*21+20,2]+=.08
        candidates=transfer_grasp_candidates(v,t)
        self.assertEqual(set(candidates),{(0,20),(315,335)})
        for row in [0,15]:v[row*21+20,2]+=.08
        self.assertEqual(transfer_grasp_candidates(v,t),[])
    def test_route_probe_request_and_event_are_json_serializable(self):
        requests=[];events=[]
        class Planner:
            count=0
            def call(self,request):
                requests.append(json.loads(json.dumps(request)));self.count+=1
                return dict(success=True,status=None,q=[[0.]*7])
        class JsonRecorder:
            def mark(self,name,**values):events.append(json.loads(json.dumps(dict(name=name,**values))))
        probe_route_pose(Planner(),JsonRecorder(),np.zeros(7,np.float32),
                         [np.float32(.12),np.float32(-.18),.94],Rotation.identity(),np.int64(315))
        self.assertEqual(events[0]['goal'],requests[0]['tcp_world'])
        self.assertEqual(events[0]['vertex_index'],315)
        self.assertEqual(events[0]['planner_id'],1)
    def test_opening_retains_load_bearing_target(self):
        # Measured positions from the release failure: the loaded finger is
        # behind its existing1mm target. Opening must not lower that target.
        previous=np.array([.001,.001])
        for measured in [np.array([.0003479,.0008445]),np.array([.0002814,.0008645]),
                         np.array([.0002294,.0009175])]:
            command=opening_target(previous,measured,.035,.0004,.025,.01)
            self.assertTrue((command>=previous).all())
            self.assertLessEqual(float((command-previous).max()),.00025000001)
            previous=command
        free=opening_target(previous,previous,.035,.0004,.025,.01)
        self.assertTrue((free>previous).all())
    def test_fold_distinguishes_flat_and_folded(self):
        v,t,c=rectangle(0);flat=measure(v,t,c)
        self.assertGreater(flat['projected_area_fraction'],.98)
        self.assertLess(flat['layer_overlap_iou'],.02)
        self.assertFalse(fold_satisfactory(flat))
        v,t,c=rectangle(179);m=measure(v,t,c)
        self.assertGreater(m['layer_overlap_iou'],.96)
        self.assertTrue(fold_satisfactory(m))
        self.assertFalse(satisfactory(m,'unfold_half'))
    def test_one_aligned_corner_is_not_a_fold(self):
        v,t,c=rectangle(179);v[-1,0]+=.12
        self.assertFalse(fold_satisfactory(measure(v,t,c)))
    def test_quarter_fold_is_not_single_half_fold(self):
        v,t,c=rectangle(179);center=(v[:,0].min()+v[:,0].max())/2;side=v[:,0]>center
        v[side,0]=2*center-v[side,0];v[side,2]+=.0015
        m=measure(v,t,c)
        self.assertGreater(m['layer_overlap_iou'],.95)
        self.assertLess(max(m['paired_corner_errors_m']),.005)
        self.assertFalse(fold_satisfactory(m))
    def test_transfer_must_reach_designated_position(self):
        v,t,c=rectangle(179);c['task_spec']=task_spec('folded_transfer','v002')
        target=measure(v,t,c)['target_fold_center_xy_m']
        v[:,:2]+=np.asarray(target)-v[:,:2].mean(0)
        self.assertTrue(satisfactory(measure(v,t,c),'folded_transfer'))
        v[:,0]+=.10
        wrong=measure(v,t,c)
        self.assertGreater(wrong['target_surface_fraction'],.95)
        self.assertTrue(fold_satisfactory(wrong))
        self.assertFalse(satisfactory(wrong,'folded_transfer'))
    def test_destination_layout_preserves_folded_material_pairs(self):
        v,t,c=rectangle(179);c['task_spec']=task_spec('folded_transfer','v002')
        v[:,:2]=folded_destination(t,c['task_spec'])
        result=measure(v,t,c)
        self.assertTrue(satisfactory(result,'folded_transfer'))
        # The duplicated material rows have a4.76mm vertex-mean bias at the
        # fold line. Check the geometric area centroid independently instead.
        tri=v[np.asarray(t['faces']),:2]
        edge1=tri[:,1]-tri[:,0];edge2=tri[:,2]-tri[:,0]
        area=np.abs(edge1[:,0]*edge2[:,1]-edge1[:,1]*edge2[:,0])
        centroid=(tri.mean(1)*area[:,None]).sum(0)/area.sum()
        np.testing.assert_allclose(centroid,[.32,-.28],atol=1e-10)
        self.assertLess(max(result['paired_corner_errors_m']),1e-10)
    def test_rigid_turnover_is_not_eversion(self):
        cfg=catalog()['tasks']['garment_flip']['variants']['v001'];v,f,t=prepare_garment(cfg)
        initial=garment_measure(v,t);turned=Rotation.from_euler('x',180,degrees=True).apply(v-v.mean(0))+v.mean(0)
        final=garment_measure(turned,t)
        self.assertLess(final['front_normal_z'],-.8)
        for score in final['front_panel_normal_z'].values():self.assertLess(score,-.8)
        self.assertAlmostEqual(initial['orientation_volume_ratio'],final['orientation_volume_ratio'])
        for score in final['outward_panel_fraction'].values():self.assertGreater(score,.99)
    def test_inside_out_embedding_and_rigid_motion(self):
        cfg=catalog()['tasks']['garment_inside_out']['variants']['v001'];v,f,t=prepare_garment(cfg)
        rotated=Rotation.from_euler('xyz',[40,100,22],degrees=True).apply(v)+[.1,.2,.3]
        for vertices in [v,rotated]:
            m=garment_measure(vertices,t);self.assertLess(m['orientation_volume_ratio'],-.99)
            for score in m['outward_panel_fraction'].values():self.assertLess(score,.01)
        self.assertEqual(len(t['garment']['openings']),4)
        self.assertAlmostEqual(t['initial_max_edge_ratio'],1.)
    def test_cuff_repair_is_local_and_keeps_openings(self):
        cfg=catalog()['tasks']['garment_flip']['variants']['v002'];original,faces,top=prepare_garment(cfg)
        repaired,faces2,top2=prepare_garment(dict(cfg,reference_repair='right_cuff_laplacian_v1'))
        self.assertTrue(np.array_equal(faces,faces2))
        self.assertEqual(top['garment']['openings'],top2['garment']['openings'])
        moved=np.flatnonzero(np.linalg.norm(repaired-original,axis=1)>1e-12).tolist()
        self.assertEqual(moved,[81,82,83,274,275,276,302,414,1519,1520,1720])
        self.assertLess(np.linalg.norm(repaired-original,axis=1).max(),.0054)
        self.assertTrue(top2['garment']['reference_geometry_repair']['source_reference_changed'])
        inverted,_,it=prepare_garment(dict(cfg,reference_repair='right_cuff_laplacian_v1',inside_out=True))
        self.assertLess(garment_measure(inverted,it)['orientation_volume_ratio'],-.99)
        regularized,ff,tt=prepare_garment(dict(cfg,reference_repair='right_cuff_laplacian_v2'))
        self.assertTrue(np.array_equal(faces,ff))
        self.assertEqual(top['garment']['openings'],tt['garment']['openings'])
        self.assertAlmostEqual(np.linalg.norm(regularized[82]-regularized[83]),.003)
        self.assertLess(np.linalg.norm(regularized-original,axis=1).max(),.0065)

if __name__=='__main__':unittest.main()
