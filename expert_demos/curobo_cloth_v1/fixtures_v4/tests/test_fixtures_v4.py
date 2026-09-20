import sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.append(str(Path(__file__).resolve().parents[2]/'runtime'))
from fixtures_v4 import catalog
from fixtures_v4.build_scenes import task_spec
from fixtures_v4.fixtures import components
from fixtures_v4.initial_states import initial_points,parent_run
from fixtures_v4.metrics import measure,satisfactory,box_top_coverage


class FixtureTests(unittest.TestCase):
    def test_fixture_capture_is_local_and_transfers_ownership_without_pose_write(self):
        from scene import Scene
        spec=task_spec('hang_on_rod','v001');center=np.array(spec['rod_clamp']['capture_center_world_m'])
        points=np.array([center,center+[.1,0,0]])
        scene=Scene.__new__(Scene);scene.cfg={'task_spec':spec};scene.tick=42
        scene.fixture_patch=None;scene.assisted_patch={'ids':np.array([0])}
        scene.cloth_vertices=lambda:points.copy()
        with self.assertRaisesRegex(ValueError,'mouth'):scene.attach_fixture_patch(1)
        with self.assertRaisesRegex(ValueError,'gripper'):scene.attach_fixture_patch(0)
        before=points.copy();event=scene.attach_fixture_patch(0,transfer_from_gripper=True)
        self.assertIsNone(scene.assisted_patch);self.assertEqual(event['vertex_ids'],[0])
        np.testing.assert_array_equal(points,before)
        with self.assertRaisesRegex(ValueError,'already'):scene.attach_fixture_patch(0)
        scene.release_fixture_patch();scene.cfg['task_spec']['rod_clamp']['enabled']=False
        with self.assertRaisesRegex(ValueError,'not enabled'):scene.attach_fixture_patch(0)

    def test_solver_callback_combines_disjoint_gripper_and_fixture_nodes(self):
        from scene import Scene
        from types import SimpleNamespace
        from unittest.mock import patch
        import io,json
        flags=np.array([1,1,1]);aim=np.zeros((3,3));slots={'is_constrained':flags,'aim_position':aim}
        geometry=SimpleNamespace(vertices=lambda:SimpleNamespace(find=lambda key:slots[key]))
        info=SimpleNamespace(geo_slots=lambda:[SimpleNamespace(geometry=lambda:geometry)])
        uipc=SimpleNamespace(view=lambda value:value,builtin=SimpleNamespace(is_constrained='is_constrained',aim_position='aim_position'))
        hand=SimpleNamespace(get_quat=lambda:[1,0,0,0],get_pos=lambda:[.3,.2,.1])
        scene=Scene.__new__(Scene);scene.tick=4;scene.cfg={'dt':.01,'assisted_grasp':{'strength_rate':100.}}
        scene.robots=[SimpleNamespace(get_link=lambda name:hand)]
        scene.assisted_patch={'ids':np.array([0]),'local':np.zeros((1,3)),'target_local':np.zeros((1,3)),'tick':0}
        scene.fixture_patch={'ids':np.array([1]),'targets':np.array([[1.,2.,3.]])}
        scene.assisted_trace=io.StringIO();scene.fixture_trace=io.StringIO()
        with patch.dict(sys.modules,{'uipc':uipc}):scene.animate_assisted_grasp(info)
        np.testing.assert_array_equal(flags,[1,1,0]);np.testing.assert_allclose(aim[:2],[[.3,.2,.1],[1,2,3]])
        self.assertEqual(json.loads(scene.fixture_trace.getvalue())['vertex_ids'],[1])
        scene.fixture_patch=None
        with patch.dict(sys.modules,{'uipc':uipc}):scene.animate_assisted_grasp(info)
        np.testing.assert_array_equal(flags,[1,0,0])

    def test_health_records_actual_fixture_node_error_after_physics(self):
        from scene import Scene
        scene=Scene.__new__(Scene);scene.cfg=dict(task_spec=task_spec('hang_on_rod','v001'),robot_names=[],
            table={'position':[0,0,.74],'half_extents':[1,1,.04]})
        scene.robots=[];scene.rigid_objects=lambda:{};scene._fixed_reference={}
        points=np.array([[0,0,1.04],[.01,0,1.038]])
        scene.cloth_vertices=lambda:points;scene.edges=np.array([[0,1]]);scene.rest_lengths=np.array([.01])
        scene.fixture_patch={'ids':np.array([1]),'targets':np.array([[.01,0,1.04]])}
        result=scene.physics_health()['fixture_constraint_after_step']
        self.assertAlmostEqual(result['error_m'][0],.002)
        np.testing.assert_array_equal(result['actual_positions_world_m'],points[[1]])

    def test_fixture_shell_and_jaw_proxy_are_explicit(self):
        parts=components(task_spec('hang_on_rod','v001'))
        jaws=[p for p in parts if p['name'] in ('FixtureClipJawLower','FixtureClipJawUpper')]
        self.assertEqual(len(jaws),2);self.assertTrue(all(p['collision'] is False for p in jaws))
        self.assertTrue(all(p.get('collision',True) for p in parts if p['name'] in ['FixtureRod','FixtureClipBracket']))
        self.assertNotIn('rod_clamp',task_spec('cover_box','v001'))

    def test_fixture_trace_rejects_mismatched_ownership_and_display_state(self):
        from fixtures_v4.metrics import fixture_trace_audit
        cfg={'task_spec':task_spec('hang_on_rod','v001'),'assisted_grasp':{'strength_rate':100.}}
        center=cfg['task_spec']['rod_clamp']['capture_center_world_m']
        events=[dict(name='fixture_grasp_attached',tick=1,vertex_ids=[0],aim_positions_world_m=[center],transferred_from_gripper=True),
                dict(name='fixture_assisted_terminal',free_bare_rod_hanging_claimed=False)]
        rows=[dict(tick=1,active=False,vertex_ids=[],aim_positions_world_m=[],strength_rate=100.),
              dict(tick=2,active=True,vertex_ids=[0],aim_positions_world_m=[center],strength_rate=100.)]
        vertices=np.array([[center],[np.array(center)+[0,0,-.002]]]);ticks=np.array([1,2])
        result=fixture_trace_audit(cfg,events,rows,[dict(tick=2,vertex_ids=[1])],ticks,vertices)
        self.assertAlmostEqual(result['max_constraint_error_m'],.002)
        physical={1:{'cloth_health':{'fixture_constraint_after_step':dict(rows[0],actual_positions_world_m=[],error_m=[])}},
                  2:{'cloth_health':{'fixture_constraint_after_step':dict(rows[1],actual_positions_world_m=vertices[1].tolist(),error_m=[.002])}}}
        audited=fixture_trace_audit(cfg,events,rows,[],ticks,vertices,physics_rows=physical)
        self.assertEqual(audited['recorded_active_physics_ticks'],1)
        physical[2]['cloth_health']['fixture_constraint_after_step']['error_m']=[0.]
        with self.assertRaisesRegex(ValueError,'error'):fixture_trace_audit(cfg,events,rows,[],ticks,vertices,physics_rows=physical)

        with self.assertRaisesRegex(ValueError,'Double'):fixture_trace_audit(cfg,events,rows,[dict(tick=2,vertex_ids=[0])],ticks,vertices)
        broken=copy.deepcopy(rows);broken[1]['active']=False
        with self.assertRaisesRegex(ValueError,'state'):fixture_trace_audit(cfg,events,broken,[],ticks,vertices)
        broken=copy.deepcopy(rows);broken[1]['aim_positions_world_m'][0][0]+=.05
        with self.assertRaisesRegex(ValueError,'target'):fixture_trace_audit(cfg,events,broken,[],ticks,vertices)

    def test_observed_crown_handles_rotated_hem_and_distinct_regions(self):
        from fixtures_v4.hang_on_rod import observed_boundary_candidates
        f=task_spec('hang_on_rod','v001')['fixture'];x,y=f['center_xy'];z=f['center_height_m']
        topology=dict(faces=[[0,1,2],[0,2,3]],rest_vertices=[[0,0,0],[.4,0,0],[.4,.3,0],[0,.3,0]])
        # Only a different, rotated edge crosses the crown; old material-hem
        # grouping would omit it. Left/right are defined by observed world X.
        points=np.array([[x,y+.1,z-.1],[x-.08,y,z+.018],[x+.07,y,z+.018],[x,y-.1,z-.1]])
        self.assertEqual(observed_boundary_candidates(points,topology,f,-1),[1,2])
        self.assertEqual(observed_boundary_candidates(points,topology,f,1,[1]),[2])

    def test_regrasp_reselects_material_point_after_the_hover_motion(self):
        from fixtures_v4.actions import Controller
        from types import SimpleNamespace
        c=Controller.__new__(Controller);state={'hovered':False,'attached':None,'tcp':np.zeros(3)};observed=[]
        points=np.array([[0.,0.,.8],[.1,0.,.8]])
        def attach(ids):state['attached']=ids;return dict(vertex_ids=ids)
        c.scene=SimpleNamespace(cloth_vertices=lambda:points,attach_cloth_patch=attach)
        c.cfg=dict(table_height=.78,task_spec=task_spec('hang_on_rod','v001'))
        c.rec=SimpleNamespace(phase='',mark=lambda *args,**kwargs:None);c.robot=object();c.planner=object()
        c.retreat=lambda:None;c.motion=lambda *args,**kwargs:None;c.approach_height=lambda p:.9
        def move(p):state['tcp']=np.asarray(p);state['hovered']=True
        c.move=move;c.tcp=lambda:state['tcp'];c.select_reachable=lambda ids:ids[0]
        c.hold=lambda *args:None;c.mark=lambda *args,**kwargs:None
        def reselect():observed.append(state['hovered']);return [1 if state['hovered'] else 0]
        self.assertEqual(c.acquire(None,reselect=reselect),1)
        self.assertEqual(observed,[False,True]);self.assertEqual(state['attached'],[1])

    def test_crown_candidates_exclude_a_high_unsupported_flap(self):
        from fixtures_v4.hang_on_rod import crown_candidates
        f=task_spec('hang_on_rod','v001')['fixture'];x,y=f['center_xy'];z=f['center_height_m']
        points=np.array([[x,y,z+.042],[x,y,z+.018],[x,y+.06,z-.08]])
        self.assertEqual(crown_candidates(points,[0,1,2],f),[1])

    def test_rod_crown_pinch_uses_support_clearance_only_near_crown(self):
        from fixtures_v4.actions import grasp_position
        cfg=dict(task_spec=task_spec('hang_on_rod','v001'),table_height=.78)
        x,y=cfg['task_spec']['fixture']['center_xy']
        point=[x-.0725,y-.0075,1.027]
        self.assertAlmostEqual(grasp_position(point,cfg)[2],1.043)
        self.assertLess(grasp_position(point,cfg)[2]-point[2],.032)
        self.assertAlmostEqual(grasp_position([x,y+.10,.93],cfg)[2],.935)

    def test_rejected_target_rectangle_probe_is_not_an_executed_failure(self):
        from evaluate import plan_evidence
        plans={1:dict(request=dict(tcp_world=[.54,-.515,.803]),result=dict(success=False,status='IK_FAIL')),
               2:dict(request=dict(tcp_world=[.52,-.50,.803]),result=dict(success=True,status='None'))}
        probe=dict(planner_id=1,goal=[.54,-.515,.803],success=False,status='IK_FAIL')
        events=[dict(name='spread_target_probes',probes=[probe],all_reachable=False),dict(name='planned_waypoint',planner_id=2)]
        gates,metrics=plan_evidence(plans,events,allow_probes=True)
        self.assertTrue(all(gates.values()));self.assertEqual(metrics['rejected_reachability_probes'],1)
        events.append(dict(name='planned_waypoint',planner_id=1))
        self.assertFalse(plan_evidence(plans,events,allow_probes=True)[0]['curobo_probe_records_valid'])
        self.assertFalse(plan_evidence(plans,[dict(name='planned_waypoint',planner_id=1)],allow_probes=True)[0]['curobo_plans_valid'])

    def test_hanging_requires_supported_release_and_distinct_regrasps(self):
        from fixtures_v4.metrics import rod_sequence_complete
        old=[dict(name=n) for n in ['task_start','assisted_grasp_attached','cloth_lifted','crossed_rod','assisted_grasp_released','released_on_rod','task_complete']]
        self.assertFalse(rod_sequence_complete(old))
        events=[dict(name='rod_sequence_revision',version=2),dict(name='assisted_grasp_attached')]
        events += [dict(name=n) for n in ['rod_feed_started','rod_loaded','assisted_grasp_released','released_on_rod','rod_supported']]
        for side,index in [(-1,327),(1,13)]:
            events += [dict(name='assisted_grasp_attached'),dict(name='rod_spread_started'),dict(name='assisted_grasp_released'),dict(name='rod_side_spread',side=side,vertex_index=index)]
        events += [dict(name='rod_spread_complete'),dict(name='task_complete')]
        self.assertTrue(rod_sequence_complete(events))
        events[-3]['vertex_index']=327
        self.assertFalse(rod_sequence_complete(events))

    def test_retrieval_checks_receiving_table_without_invented_center_alignment(self):
        m=dict(target_surface_fraction=1.,projected_area_fraction=.85,center_error_m=.102)
        self.assertTrue(satisfactory(m,'retrieve_from_basket'))
        self.assertTrue(satisfactory(m,'retrieve_from_rod'))
        m['target_surface_fraction']=.4
        self.assertFalse(satisfactory(m,'retrieve_from_basket'))

    def test_fixture_surface_pinches_keep_robot_clearance(self):
        from fixtures_v4.actions import grasp_position
        for task,point_z,goal_z in [('cover_box',.871,.888),('place_in_basket',.793,.810)]:
            spec=task_spec(task,'v001');cfg=dict(task_spec=spec,table_height=.78)
            x,y=spec['fixture']['center_xy'];goal=grasp_position(np.array([x,y,point_z],np.float32),cfg)
            self.assertAlmostEqual(goal[2],goal_z)
            self.assertLess(goal[2]-point_z,.032)

    def test_fixture_clearance_does_not_raise_adjacent_or_suspended_grasps(self):
        from fixtures_v4.actions import grasp_position
        spec=task_spec('cover_box','v001');cfg=dict(task_spec=spec,table_height=.78)
        x,y=spec['fixture']['center_xy']
        self.assertAlmostEqual(grasp_position([x+.2,y,.781],cfg)[2],.798)
        self.assertAlmostEqual(grasp_position([x,y,1.1],cfg)[2],1.105)

    def test_planner_probe_serializes_physics_float32(self):
        import json
        from types import SimpleNamespace
        from fixtures_v4.actions import Controller
        class Planner:
            count=0
            def call(self,request):
                json.dumps(request);self.count+=1
                return dict(success=True,status=None)
        c=Controller.__new__(Controller);c.cfg=dict(table_height=.78,task_spec=task_spec('place_in_basket','v001'))
        c.scene=SimpleNamespace(cloth_vertices=lambda:np.array([[.2,.3,.82]],np.float32))
        c.robot=SimpleNamespace(state=lambda:[dict(joints=[0.]*7)])
        c.rec=SimpleNamespace(mark=lambda *a,**kw:json.dumps(kw));c.planner=Planner()
        from scipy.spatial.transform import Rotation
        c.rotation=Rotation.identity();self.assertEqual(c.select_reachable([0]),0)
        self.assertEqual(c.planner.count,2)

    def test_basket_opening_remains_open(self):
        s=task_spec('place_in_basket','v001');parts=components(s);self.assertEqual(len(parts),5)
        x,y=s['fixture']['center_xy'];z=.86
        self.assertFalse(any(np.all(np.abs(np.array([x,y,z])-p['position'])<np.array(p['size'])/2) for p in parts))
        self.assertTrue(any(np.all(np.abs(np.array([x,y,.786])-p['position'])<np.array(p['size'])/2) for p in parts))

    def test_authored_cloth_preserves_edges(self):
        for task in ['hang_on_rod','place_in_basket','cover_box']:
            for cfg in catalog()['tasks'][task]['variants'].values():
                v=initial_points(task,cfg).reshape(61,81,3)
                np.testing.assert_allclose(np.linalg.norm(np.diff(v,axis=1),axis=2),.005,atol=1e-8)
                np.testing.assert_allclose(np.linalg.norm(np.diff(v,axis=0),axis=2),.005,atol=1e-8)

    def test_one_sided_cloth_is_not_hanging_success(self):
        m=dict(rod_contact_band_fraction=.08,near_tail_fraction=.8,far_tail_fraction=0.,above_table_fraction=1.)
        self.assertFalse(satisfactory(m,'hang_on_rod'));m['far_tail_fraction']=.2;self.assertTrue(satisfactory(m,'hang_on_rod'))

    def test_above_basket_is_not_inside(self):
        spec=task_spec('place_in_basket','v001');cfg=dict(task_spec=spec,table_height=.78)
        x,y=spec['fixture']['center_xy'];v=np.array([[x-.02,y-.02,.81],[x+.02,y-.02,.81],[x,y+.02,.81]])
        topology=dict(flat_area_m2=.12,faces=[[0,1,2]])
        self.assertTrue(satisfactory(measure(v,topology,cfg),'place_in_basket'))
        v[:,2]=1.1;self.assertFalse(satisfactory(measure(v,topology,cfg),'place_in_basket'))

    def test_cover_requires_actual_box_height(self):
        f=task_spec('cover_box','v001')['fixture'];x,y=f['center_xy'];z=.871
        v=np.array([[x-.2,y-.2,z],[x+.2,y-.2,z],[x+.2,y+.2,z],[x-.2,y+.2,z]])
        faces=[[0,1,2],[0,2,3]];self.assertEqual(box_top_coverage(v,faces,f),1.)
        v[:,2]=.784;self.assertEqual(box_top_coverage(v,faces,f),0.)
        self.assertFalse(satisfactory(dict(box_top_coverage=1.,draping_sides=0),'cover_box'))

    def test_retrieval_requires_real_parent(self):
        with self.assertRaises(ValueError):parent_run('/nonexistent-fixture-test','retrieve_from_rod','v001')

if __name__=='__main__':unittest.main()
