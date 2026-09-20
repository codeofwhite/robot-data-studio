"""Hard command and measured-state interlocks. No object state is exposed to the policy."""
import math
import numpy as np
from table_geometry import segment_hits_table
class Rejected(ValueError):pass
class Halted(RuntimeError):pass
def finite_vector(value,n,label):
    if not isinstance(value,(list,tuple)) or len(value)!=n:raise Rejected(label+" must be a length "+str(n)+" array")
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) for x in value):raise Rejected(label+" entries must be JSON numbers")
    try:a=np.array(value,dtype=float)
    except (TypeError,ValueError):raise Rejected(label+" must be numeric")
    if not np.isfinite(a).all():raise Rejected(label+" must be finite")
    return a
def validate_action(action,cfg,poses):
    if not isinstance(action,dict) or not action:raise Rejected("Provide an arm action")
    names=cfg.get('robot_names',['arm'])
    if len(poses)!=len(names):raise Rejected('Robot state count differs from configured names')
    if set(action)-set(names):raise Rejected("Unknown arm")
    result={}
    for i,name in enumerate(names):
        if name not in action:continue
        a=action[name]
        if not isinstance(a,dict) or set(a)-{"translation","rotation","gripper"}:raise Rejected("Unknown arm action field")
        d=finite_vector(a.get("translation",[0,0,0]),3,"translation")
        rot=finite_vector(a.get("rotation",[0,0,0]),3,"rotation")
        if np.linalg.norm(d)>cfg["max_step_m"]+1e-12:raise Rejected("Translation exceeds 2 cm")
        if np.linalg.norm(rot)>cfg["max_rotation_rad"]+1e-12:raise Rejected("Rotation exceeds 5 degrees")
        g=a.get("gripper","keep")
        if g not in ["keep","open","close"]:raise Rejected("Invalid gripper")
        goal=np.array(poses[i]["position"])+d
        if (goal<cfg["workspace_low"]).any() or (goal>cfg["workspace_high"]).any():raise Rejected("TCP target outside workspace")
        if segment_hits_table(poses[i]["position"],goal,cfg):raise Rejected("TCP path intersects table slab")
        result[name]={"translation":d,"rotation":rot,"gripper":g}
    return result
def joint_violation(q,limits):
    return np.maximum(limits[:,0]-q,np.maximum(q-limits[:,1],0))
def check_measured(q,velocity,effort,limits,cfg,label):
    if any(not np.isfinite(a).all() for a in [q,velocity,effort]):raise Halted(label+": nonfinite robot state")
    excess=joint_violation(q,limits)
    if excess[:7].max()>cfg["gates"]["arm_limit_rad"]:raise Halted(label+": arm joint limit exceeded")
    if excess[7:].max()>cfg["gates"]["finger_limit_m"]:raise Halted(label+": finger joint limit exceeded")
    if abs(velocity[:7]).max()>cfg["actual_joint_speed_limit"]:raise Halted(label+": actual arm speed exceeded")
    if abs(velocity[7:]).max()>cfg["actual_finger_speed_limit"]:raise Halted(label+": actual finger speed exceeded")
    caps=np.r_[cfg["arm_force_limits"],cfg["finger_force_limit"],cfg["finger_force_limit"]]
    if (abs(effort)>caps+1e-3).any():raise Halted(label+": actuator effort cap exceeded")
    return excess
def check_cloth(health,cfg):
    if health["max_edge_ratio"]>cfg["gates"]["edge_ratio"]:raise Halted("Cloth edge stretch exceeded")
    if health["max_table_vertex_penetration_m"]>cfg["gates"]["table_penetration_m"]:raise Halted("Cloth table penetration exceeded")

def approved_adjacent_pairs(arms):
    edges=[("link"+str(i),"link"+str(i+1)) for i in range(7)]+[("link7","left_finger"),("link7","right_finger")]
    return {"|".join(sorted([arm+"/"+a,arm+"/"+b])) for arm in arms for a,b in edges}

def check_adjacent_contact_configuration(info):
    arms=info["robot_names"]
    if not arms or len(set(arms))!=len(arms):raise Halted("Unexpected robot set in IPC contact audit")
    if arms!=info.get('configured_robot_names',['arm']):raise Halted('IPC robot set differs from configured scene')
    expected={"floor","table"}
    if arms:
        expected.add("cloth")
        expected|={a+"/"+l for a in arms for l in ["link"+str(i) for i in range(8)]+["left_finger","right_finger"]}
    bodies=info["bodies"]
    if set(bodies)!=expected:raise Halted("Actual IPC collision body set is incomplete")
    ids=[]
    for name,body in bodies.items():
        eid=body["element_id"];ids.append(eid)
        if body["geometry_contact_ids"]!=[eid] or len(body["geometry_slot_ids"])!=1:
            raise Halted("Actual geometry contact assignment differs: "+name)
    if len(set(ids))!=len(ids):raise Halted("IPC bodies share a contact element")
    allowed=approved_adjacent_pairs(arms)
    if info["native_adjacent_collision_enabled"] or set(info["native_adjacent_pairs"])!=allowed:
        raise Halted("Native adjacent filter differs from approved allowlist")
    fixed_pairs=set(info.get('fixed_foundation_pairs',[]))
    if fixed_pairs:
        if not info.get('original_scene') or info.get('fixed_base_robots')!=arms:
            raise Halted('Fixed assembly exclusions require original-scene fixed-base robots')
        fixed={'floor','table'}|{a+'/link0' for a in arms}
        expected_fixed={'|'.join(sorted((a,b))) for a in fixed for b in fixed if a!=b}
        if fixed_pairs!=expected_fixed:raise Halted('Fixed assembly exclusion includes a moving body or omits a fixed pair')
    allowed|=fixed_pairs
    names=sorted(bodies);required={a+"|"+b for i,a in enumerate(names) for b in names[i:]}
    models=info["actual_pair_models"]
    if set(models)!=required:raise Halted("Actual per-body IPC contact table is incomplete")
    for pair,m in models.items():
        a,b=pair.split("|")
        if m["element_ids"]!=[bodies[a]["element_id"],bodies[b]["element_id"]]:
            raise Halted("IPC pair uses the wrong geometry elements: "+pair)
        if m["enabled"]!=(pair not in allowed):raise Halted("Unapproved IPC contact mask: "+pair)
        ref=m["reference"]
        for field in ["friction","resistance"]:
            if not np.isfinite(m[field]) or not np.isfinite(ref[field]) or not math.isclose(m[field],ref[field],rel_tol=1e-12,abs_tol=1e-12):
                raise Halted("IPC material changed: "+pair)
        if m["config"]!=ref["config"]:raise Halted("IPC contact configuration changed: "+pair)

def check_contact_configuration(info):
    check_adjacent_contact_configuration(info["adjacent_contact_audit"])
    if not info["ipc_rigid_rigid_enabled"] or not info["all_collision_links_enabled"]:raise Halted("Required rigid collision disabled")
    if info["object_coupling_modes"]!={"floor":"ipc_only","table":"ipc_only"}:raise Halted("Unexpected static coupling modes")
    if info["robot_coupling_modes"]!=["external_articulation"]*len(info['adjacent_contact_audit']['robot_names']):raise Halted("Unexpected articulated coupling mode")
    if info["soft_constraint_entities"]!=[]:raise Halted("Mixed soft-constraint feedback forbidden")
