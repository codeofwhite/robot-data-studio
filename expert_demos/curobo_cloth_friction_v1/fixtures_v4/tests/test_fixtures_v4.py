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
