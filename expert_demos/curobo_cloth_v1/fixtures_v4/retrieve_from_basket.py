from fixtures_v4.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);v=c.scene.cloth_vertices()
    # A reachable material corner can peel the crumpled sheet from the basket.
    # Mid-edge lifting often deposited a doubled strip. All candidates still
    # require the same original-scene hover and grasp collision checks.
    candidates=sorted([0,20,315,335],key=lambda i:v[i,2],reverse=True)
    candidates+=sorted([167,188,147,168],key=lambda i:v[i,2],reverse=True)
    c.rec.mark('initial_grasp_candidate_order',vertex_indices=candidates,
               reason='Prefer a reachable material corner, then explicitly probe edge midpoints if required')
    i=c.select_reachable(candidates);c.acquire(i);c.lift_clear(1.31);c.mark('clear_of_basket');c.lay_on_table(i);c.finish()
