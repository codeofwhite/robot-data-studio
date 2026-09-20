"""Physical material presets, not measured real-fabric calibrations."""
import copy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MATERIALS={
 'light':dict(gsm=80.,thickness=.0004,E=30000.,bending=.004,friction=.35),
 'medium':dict(gsm=120.,thickness=.0006,E=60000.,bending=.01,friction=.6),
 'heavy':dict(gsm=320.,thickness=.0012,E=150000.,bending=.02,friction=.75)}
INITIALS={'nominal':dict(offset_xy=[0.,0.],yaw_deg=0.,fold_angle_deg=160.),
 'shift_left':dict(offset_xy=[-.01,0.],yaw_deg=-5.,fold_angle_deg=150.),
 'shift_right':dict(offset_xy=[.01,0.],yaw_deg=5.,fold_angle_deg=165.)}
PROFILES={'single_franka':{'robots':1,'dofs':9,'state_order':['joint1','joint2','joint3','joint4','joint5','joint6','joint7','finger_joint1','finger_joint2'],'status':'requires_runtime_gate'},
 'dual_franka':{'robots':2,'dofs':18,'state_order':'left arm 9 then right arm 9','status':'blocked','reason':'Current audited IPC velocity/contact adapter supports exactly one arm; no unverified dual-arm data may be published.'}}
def configuration(material='medium',initial='nominal',seed=194731):
    cfg=json.loads((ROOT/'runtime/base_config.json').read_text())
    m=copy.deepcopy(MATERIALS[material]);gsm=m.pop('gsm');m['rho']=gsm/1000/m['thickness'];m['nu']=.3
    cfg['cloth']=m;cfg['material_provenance']={'preset':material,'synthetic':True,'measured_real_fabric':False,'gsm':gsm,'density_rule':'kg/m3 = gsm / 1000 / thickness_m','bending_units':'Genesis native coefficient; not directly interchangeable with other engines','damping':'not implemented; not swept'}
    cfg['source_project']=str(ROOT/'runtime/source');cfg['surface_friction']={'table':.6,'gripper':.6}
    cfg['seed']=seed;cfg['initial_variant']=copy.deepcopy(INITIALS[initial])
    c=cfg['square'];c['center_xy']=[a+b for a,b in zip(c['center_xy'],INITIALS[initial]['offset_xy'])]
    c['yaw_deg']=INITIALS[initial]['yaw_deg'];c['fold_angle_deg']=INITIALS[initial]['fold_angle_deg']
    cfg['nominal_mass_kg']=c['width_m']**2*gsm/1000;cfg['record_stride']=5
    return cfg
