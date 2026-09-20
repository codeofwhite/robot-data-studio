from folding_v3.actions import Controller
from folding_v3.metrics import measure, satisfactory

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);targets=c.cfg['task_spec']['target_corners_xy_m']
    first=c.cfg.get('scene_grasp_seed',{}).get('vertex_index',335)
    for j,index in enumerate([first,*[i for i in [20,335] if i!=first]]):
        c.acquire(index,kind='upper_layer');c.mark('upper_layer_acquired',vertex_index=index)
        c.rec.phase='unfold';p=c.tcp();target=targets[str(index)]
        c.move([p[0],p[1],c.cfg['table_height']+.08])
        c.move([(p[0]+target[0])/2,(p[1]+target[1])/2,c.cfg['table_height']+.21])
        c.move([*target,c.cfg['table_height']+.08]);c.place(target)
        c.mark('corner_adjusted',vertex_index=index,target_xy=target)
    c.mark('half_opened')
    for _ in range(2):
        if satisfactory(measure(c.scene.cloth_vertices(),c.scene.topology,c.cfg),'unfold_half'):break
        import numpy as np
        v=c.scene.cloth_vertices();i=max(map(int,targets),key=lambda x:np.linalg.norm(v[x,:2]-targets[str(x)]))
        c.pull(i,targets[str(i)])
    c.mark('spread_complete');c.finish()
