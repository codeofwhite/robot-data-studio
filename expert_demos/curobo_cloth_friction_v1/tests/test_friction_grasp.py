import sys
import unittest
import json
import tempfile
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contact_grasp import hold_result, pad_face_distances, patch_pad_distance, evaluate_contact, verify_foundation


class ContactEvidenceTests(unittest.TestCase):
    def test_empty_or_unreviewed_foundation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gate.json'
            for value in [dict(passed=False), dict(passed=True, physics_passed=True,
                          video_review_pending=False, checks={}, evaluation_sha256=[])]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    verify_foundation(path)

    def setUp(self):
        self.cfg = {'dt': .004, 'assisted_grasp': {'enabled': False}, 'negative_control': False,
                    'contact_grasp': {'hold_s': .6, 'minimum_lift_m': .008,
                    'maximum_material_slip_m': .004, 'maximum_pad_distance_m': .0015,
                    'minimum_loaded_gap_m': .0002, 'maximum_loaded_gap_m': .02}}
        self.rows = [dict(tick=t, material_hand_local_m=[[0., 0., .1029]],
                         material_height_m=.815, left_pad_distance_m=.0005,
                         right_pad_distance_m=.0005, finger_gap_m=.001) for t in (0, 75, 150)]

    def test_loaded_hold_passes(self):
        self.assertTrue(all(hold_result(self.rows, .8, self.cfg)[1].values()))

    def test_near_tcp_but_outside_pad_fails(self):
        self.rows[1]['left_pad_distance_m'] = .025
        self.assertFalse(hold_result(self.rows, .8, self.cfg)[1]['both_pads_near_material'])

    def test_open_jaw_and_empty_closed_jaw_fail(self):
        for gap in (.07, 0.):
            for row in self.rows:
                row['finger_gap_m'] = gap
            self.assertFalse(hold_result(self.rows, .8, self.cfg)[1]['loaded_gap'])

    def test_sliding_and_no_lift_fail(self):
        self.rows[-1]['material_hand_local_m'] = [[0., 0., .113]]
        self.assertFalse(hold_result(self.rows, .8, self.cfg)[1]['material_retained'])
        self.assertFalse(hold_result(self.rows, .815, self.cfg)[1]['physical_lift'])

    def test_short_hold_is_not_success(self):
        self.assertFalse(hold_result(self.rows[:2], .8, self.cfg)[1]['hold_recorded'])

    def test_pad_face_is_bounded_not_infinite_plane(self):
        p = [0., 0., 0., 1., 0., 0., 0.]
        distance = pad_face_distances([[0., .001, .0445], [0., .001, .08]], p)
        self.assertAlmostEqual(distance[0], .001)
        self.assertGreater(distance[1], .02)

    def test_continuous_cloth_face_can_contact_between_vertices(self):
        vertices = np.array([[-.02, -.001, .02], [.02, -.001, .02], [0., -.001, .08]])
        pose = [0., 0., 0., 1., 0., 0., 0.]
        self.assertGreater(pad_face_distances(vertices[[2]], pose)[0], .02)
        self.assertAlmostEqual(patch_pad_distance(vertices, [[0, 1, 2]], [2], pose), .001)

    def test_unrelated_overlapping_layer_is_excluded(self):
        vertices = np.array([[-.02, -.03, .02], [.02, -.03, .02], [0., -.03, .08],
                             [-.02, -.001, .02], [.02, -.001, .02], [0., -.001, .08]])
        distance = patch_pad_distance(vertices, [[0, 1, 2], [3, 4, 5]], [2],
                                      [0., 0., 0., 1., 0., 0., 0.])
        self.assertAlmostEqual(distance, .03)

    def test_forged_success_event_does_not_replace_physics(self):
        data = dict(tick=np.array([0, 150]), cloth_constrained_vertices=np.zeros(2),
                    qpos=np.zeros((2, 1, 9)))
        _, gates = evaluate_contact(data, [{'name': 'contact_grasp_verified', 'tick': 150}],
                                    self.cfg, {'contact_link_indices': {}})
        self.assertFalse(gates['physical_acquisitions_verified'])

    def test_constraint_snapshot_invalidates_friction_claim(self):
        data = dict(tick=np.array([0, 150]), cloth_constrained_vertices=np.array([0, 1]),
                    qpos=np.zeros((2, 1, 9)))
        _, gates = evaluate_contact(data, [], self.cfg, {'contact_link_indices': {}})
        self.assertFalse(gates['no_cloth_constraints'])

    def test_independent_evaluator_recomputes_real_lift(self):
        ticks = np.array([0, 100, 175, 250, 300, 450])
        poses = np.zeros((6, 1, 3, 7)); poses[..., 3] = 1.
        for i in range(6):
            z = .7 if i == 0 else .715
            poses[i, 0, 0, :3] = [0., 0., z]
            gap = .035 if i in (0, 4, 5) else .0005
            poses[i, 0, 1, :3] = [0., gap, z + .0584]
            poses[i, 0, 2] = [0., -gap, z + .0584, 0., 0., 0., 1.]
        vertices = np.zeros((6, 1, 3)); vertices[:, 0, 2] = [.8029, .8179, .8179, .8179, .8029, .8029]
        qpos = np.zeros((6, 1, 9)); qpos[:, 0, 7:] = .0005; qpos[[0, 4, 5], 0, 7:] = .035
        data = dict(tick=ticks, cloth_vertices=vertices, link_poses=poses, qpos=qpos,
                    cloth_constrained_vertices=np.zeros(6))
        events = [dict(name='contact_before_close', tick=0, vertex_ids=[0]),
                  dict(name='contact_hold_start', tick=100),
                  dict(name='contact_hold_end', tick=250, gates={'fabricated': True}),
                  dict(name='contact_grasp_released', tick=300)]
        audit = {'contact_link_indices': dict(hand=0, left_finger=1, right_finger=2)}
        _, gates = evaluate_contact(data, events, self.cfg, audit)
        self.assertTrue(all(gates.values()))
        data['cloth_vertices'][1:4, 0, 2] = .8029
        _, gates = evaluate_contact(data, events, self.cfg, audit)
        self.assertFalse(gates['physical_acquisitions_verified'])


if __name__ == '__main__':
    unittest.main()
