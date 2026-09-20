import copy
import json
import sys
import unittest
from pathlib import Path
import numpy as np

CORE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CORE))
from tabletop_v2 import TASKS,catalog
from tabletop_v2.build_scenes import initial_points,task_spec,grid,transform
from tabletop_v2.metrics import measure,satisfactory,task_result
from evaluate import plan_evidence


class TabletopTests(unittest.TestCase):
    def test_rejected_probe_cannot_hide_failed_executed_motion(self):
        good={'request':{'tcp_world':[.3,-.2,.89]},'result':{'success':True,'status':'None'}}
        bad={'request':{'tcp_world':[.62,-.31,.89]},'result':{'success':False,'status':'IK_FAIL'}}
        probe={'name':'corner_approach_probe','planner_id':2,'goal':[.62,-.31,.89],'success':False,'status':'IK_FAIL'}
        events=[{'name':'planned_waypoint','planner_id':1},probe]
        gates,metrics=plan_evidence({1:good,2:bad},events,allow_probes=True)
        self.assertTrue(all(gates.values()));self.assertEqual(metrics['rejected_reachability_probes'],1)
        self.assertFalse(all(plan_evidence({1:bad,2:bad},events,allow_probes=True)[0].values()))
        self.assertFalse(all(plan_evidence({1:good,2:bad},events+[{'name':'planned_waypoint','planner_id':2}],allow_probes=True)[0].values()))
        self.assertFalse(all(plan_evidence({1:good,2:bad},events,allow_probes=False)[0].values()))
        wrong=copy.deepcopy(events);wrong[-1]['goal']=[0,0,0]
        self.assertFalse(all(plan_evidence({1:good,2:bad},wrong,allow_probes=True)[0].values()))

    def cfg(self,task,variant='v001'):
        return dict(task_id=task,task_spec=task_spec(task,variant),table_height=.78)

    def topology(self):return dict(physical_grid=[21,16],flat_area_m2=.12)

    def physical(self,points):return points.reshape(61,81,3)[::4,::4].reshape(-1,3)

    def test_all_twelve_initial_states_are_isometric(self):
        for task in TASKS:
            for variant in catalog()['tasks'][task]['variants']:
                with self.subTest(task=task,variant=variant):
                    p=self.physical(initial_points(task,variant)).reshape(16,21,3)
                    np.testing.assert_allclose(np.linalg.norm(np.diff(p,axis=0),axis=2),.02,atol=2e-8)
                    np.testing.assert_allclose(np.linalg.norm(np.diff(p,axis=1),axis=2),.02,atol=2e-8)
                    np.testing.assert_allclose(np.linalg.norm(p[1:,1:]-p[:-1,:-1],axis=2),.02*np.sqrt(2),atol=2e-8)

    def test_exact_flat_goal_satisfies_each_task(self):
        for task in TASKS:
            cfg=self.cfg(task);s=cfg['task_spec'];p=transform(grid(),s['target_center_world_m'][:2],s['target_yaw_deg'])
            m=measure(self.physical(p),self.topology(),cfg)
            self.assertTrue(satisfactory(m,task));self.assertLess(m['angle_error_deg'],1e-9)

    def test_below_table_projection_is_rejected(self):
        cfg=self.cfg('directed_flatten');s=cfg['task_spec'];p=self.physical(transform(grid(),s['target_center_world_m'][:2],90));p[:,2]=.70
        self.assertFalse(satisfactory(measure(p,self.topology(),cfg),'directed_flatten'))

    def test_alignment_requires_rotation_and_translation(self):
        cfg=self.cfg('translate_rotate_align');p=self.physical(initial_points('translate_rotate_align','v001'))
        m=measure(p,self.topology(),cfg);self.assertGreater(m['angle_error_deg'],15);self.assertFalse(satisfactory(m,'translate_rotate_align'))

    def test_hanging_initial_condition_present(self):
        for v in ['v001','v002','v003']:
            cfg=self.cfg('edge_retrieve_spread',v);m=measure(self.physical(initial_points('edge_retrieve_spread',v)),self.topology(),cfg)
            self.assertGreater(m['hanging_fraction'],.3)

    def test_folded_corner_has_shortened_material_diagonal(self):
        for v in ['v001','v002','v003']:
            m=measure(self.physical(initial_points('unfold_corner',v)),self.topology(),self.cfg('unfold_corner',v))
            self.assertLess(m['primary_diagonal_xy_m'],.465)

    def test_success_pose_without_actions_is_not_task_success(self):
        task='unfold_corner';cfg=self.cfg(task);spec=cfg['task_spec']
        start=self.physical(initial_points(task,'v001'));end=self.physical(transform(grid(),spec['target_center_world_m'][:2],90))
        data={'tick':np.array([0,10]),'cloth_vertices':np.array([start,end])}
        events=[dict(name=n,tick=0 if n=='task_start' else 10) for n in spec['required_stages']]
        _,g=task_result(data,events,self.topology(),cfg)
        self.assertTrue(g['task_goal_reached']);self.assertFalse(g['action_executed'])


if __name__=='__main__':unittest.main()
