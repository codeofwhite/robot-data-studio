from fixtures_v4.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);s=c.cfg['task_spec']
    seed=c.cfg.get('scene_grasp_seed',{}).get('vertex_index',s['primary_corner'])
    # Grasp the observed upper boundary, as in successful v003. Taking the
    # hanging short-edge midpoint left a persistent doubled strip in v001/2.
    edges={}
    for face in c.scene.topology['faces']:
        for a,b in zip(face,face[1:]+face[:1]):
            edge=tuple(sorted((a,b)));edges[edge]=edges.get(edge,0)+1
    boundary={i for edge,count in edges.items() if count==1 for i in edge}
    vertices=c.scene.cloth_vertices()
    upper=sorted(boundary,key=lambda i:vertices[i,2],reverse=True)
    candidates=list(dict.fromkeys(upper+[seed,s['primary_corner'],188,20,335,147,168,0,315]))
    c.rec.mark('initial_grasp_candidate_order',vertex_indices=candidates,
               reason='Probe observed upper material boundary first; retain original rod collision geometry')
    i=c.select_reachable(candidates);c.acquire(i)
    # The far-side grasp cannot reach 1.38 m with the retained downward wrist.
    # Lift within reach, then draw the material toward the near side of the rod.
    c.lift_clear(1.34)
    p=c.tcp();c.rec.phase='rod_exit';c.move([p[0],s['fixture']['center_xy'][1]-.24,1.30])
    c.mark('clear_of_rod');c.lay_on_table(i);c.finish()
