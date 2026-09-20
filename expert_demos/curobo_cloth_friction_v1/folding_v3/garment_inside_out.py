"""Single-arm eversion pilot; measured failed stages stop and remain diagnostics."""
import numpy as np
from folding_v3.actions import Controller
from folding_v3.metrics import garment_measure

def execute(robot,rec,planner):
    from safety import Halted
    c=Controller(robot,rec,planner);g=c.scene.topology['garment'];keys=g['keypoints']
    def sleeve(side,first):
        cuff=np.array(g['openings'][side+'_cuff']);v=c.scene.cloth_vertices()
        mouth=v[cuff].mean(0);body=v[g['openings']['neck']].mean(0)
        direction=mouth[:2]-body[:2];direction/=np.linalg.norm(direction)
        index=keys[side+'_cuff_lower'];c.acquire(index,kind='inner_cuff')
        if first:c.mark('sleeve_inside_acquired',vertex_index=index)
        c.rec.phase='sleeve_evert';p=c.tcp()
        c.move([p[0],p[1],max(p[2]+.055,.87)])
        target=mouth[:2]+direction*.10
        c.move([*target,.89]);c.place(target)
        quality=garment_measure(c.scene.cloth_vertices(),c.scene.topology)
        c.mark('sleeve_eversion_observed',side=side,outward_fraction=quality['outward_panel_fraction'][side+'_sleeve'])
        if quality['outward_panel_fraction'][side+'_sleeve']<.8:
            raise Halted('Single-arm cuff extraction moved the garment without completing sleeve eversion; a second support point may be needed')
        c.mark('sleeve_everted' if first else 'second_sleeve_everted')
    sleeve('left',True)
    v=c.scene.cloth_vertices();mouth=v[g['openings']['hem']].mean(0)
    c.acquire(keys['neck_lower'],kind='inner_body');c.rec.phase='body_evert'
    p=c.tcp();c.move([p[0],p[1],1.02]);c.move([mouth[0],mouth[1]-.12,1.02]);c.place([mouth[0],mouth[1]-.12])
    if garment_measure(c.scene.cloth_vertices(),c.scene.topology)['outward_panel_fraction']['body']<.8:
        raise Halted('Body extraction did not complete measured inside-out inversion')
    c.mark('body_everted');sleeve('right',False);c.mark('garment_spread');c.finish()
