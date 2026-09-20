"""Instance-local synchronization of contact-corrected fixed-base joint velocities."""
import hashlib,inspect
import numpy as np
EXPECTED_POST_SHA = '5adcb857ad020a230d8eabfbe12f7d1f57e9150817c27cd58cca04034bb5695f'
def finite_difference(current,previous,dt):
    current=np.asarray(current);previous=np.asarray(previous)
    if current.shape!=previous.shape or current.ndim!=2 or current.shape[1]!=9:raise RuntimeError("Expected one 9-DOF Panda state")
    if not np.isfinite(current).all() or not np.isfinite(previous).all() or not np.isfinite(dt) or dt<=0:raise RuntimeError("Invalid IPC velocity input")
    return (current-previous)/dt
def install_state_sync(coupler,robots,dt):
    import genesis as gs
    original=coupler._post_advance_external_articulation
    actual=hashlib.sha256(inspect.getsource(original).encode()).hexdigest()
    if EXPECTED_POST_SHA is None or actual!=EXPECTED_POST_SHA:raise RuntimeError("IPC post-advance implementation changed")
    if not robots or any(not r.base_link.is_fixed or r.n_dofs!=9 or r.n_qs!=9 for r in robots):
        raise RuntimeError("Velocity adapter requires fixed-base Pandas with scalar joints")
    audit={"method_sha256":actual,"scope":"this coupler instance only","velocity_rule":"contact-corrected joint displacement / dt",
        "steps":0,"raw_native_finger_speed_peak":0.,"corrected_finger_speed_peak":0.}
    audit['robot_count']=len(robots);audit['last_velocity_by_robot']={}
    # This scene has no soft-force coupling: perform one native prediction BEFORE
    # IPC, so no later native integration overwrites the contact-corrected state.
    from types import MethodType
    solver=coupler.rigid_solver
    expected_phase_hashes={'substep_pre_coupling': 'dac4b0c21c733b8a0182d33cc54f80d92026f205748c5679a074ace1c2485d3d', 'substep_post_coupling': '449c0ec3395a132dce205c1c44a0b103416eca509b409c70ac81b595b41567e9'}
    for name,expected in expected_phase_hashes.items():
        if hashlib.sha256(inspect.getsource(getattr(solver,name)).encode()).hexdigest()!=expected:
            raise RuntimeError("Unaudited rigid integration phase")
    modes={entity:mode.name for entity,mode in coupler._coup_type_by_entity.items()}
    if any(mode not in {"EXTERNAL_ARTICULATION","IPC_ONLY"} for mode in modes.values()):
        raise RuntimeError("Prediction-before-IPC requires no soft force coupling")
    if any(not entity.base_link.is_fixed for entity in modes):
        raise RuntimeError("This phase adapter requires fixed-base robots and fixed IPC objects")
    audit["rigid_phase_hashes"]=expected_phase_hashes
    audit["integration_order"]="one native prediction -> IPC projection -> corrected state"
    audit["native_prediction_steps"]=0
    def predict_before_ipc(this,f):
        this.substep(f)
        audit["native_prediction_steps"]+=1
    def no_second_native_integration(this,f):
        if audit["native_prediction_steps"]!=audit["steps"]:
            raise RuntimeError("Unbalanced native/IPC integration count")
    solver.substep_pre_coupling=MethodType(predict_before_ipc,solver)
    solver.substep_post_coupling=MethodType(no_second_native_integration,solver)
    # Scene.build performs one compile step and then restores frame zero. Its Python
    # articulation caches are not part of that restored native/IPC checkpoint.
    # Initialize them once from the now-restored, measured initial configuration.
    coupler._store_gs_rigid_states()
    entries=coupler._articulation_data_by_entity
    if set(entries)!=set(robots):raise RuntimeError("Unexpected initial articulation set")
    audit["initial_reference_resets"]=[]
    for r,ad in entries.items():
        before=ad.ref_dof_prev.copy();initial=ad.qpos_stored.copy()
        audit["initial_reference_resets"].append({"cached_before":before.tolist(),"native_initial":initial.tolist(),
            "max_difference":float(abs(before-initial).max())})
        ad.ref_dof_prev[:]=initial;ad.qpos_current[:]=initial;ad.qpos_new[:]=initial
        ad.delta_theta_tilde[:]=0.;ad.delta_theta_ipc[:]=0.
        for link,previous in zip(ad.joints_child_link,ad.prev_links_transform):
            for env_idx in range(coupler.sim._B):
                previous[env_idx]=coupler._abd_transforms_by_link[link][env_idx].copy()
    audit["installed_after_build_warmup"]=True
    def synced():
        entries=coupler._articulation_data_by_entity
        if set(entries)!=set(robots):raise RuntimeError("Unexpected articulated entity set")
        previous={r:ad.ref_dof_prev.copy() for r,ad in entries.items()}
        raw={r:r.get_dofs_velocity().detach().cpu().numpy().copy() for r in robots}
        original()
        for r,ad in entries.items():
            velocity=finite_difference(ad.qpos_new.astype(gs.np_float),previous[r].astype(gs.np_float),dt)
            coupler.rigid_solver.set_dofs_velocity(velocity if coupler.sim.n_envs>0 else velocity[0],
                dofs_idx=slice(r.dof_start,r.dof_end),skip_forward=False)
            audit["raw_native_finger_speed_peak"]=max(audit["raw_native_finger_speed_peak"],float(np.abs(raw[r][...,7:]).max()))
            audit["corrected_finger_speed_peak"]=max(audit["corrected_finger_speed_peak"],float(np.abs(velocity[...,7:]).max()))
            audit["last_raw_native_velocity"]=raw[r].tolist()
            audit["last_contact_corrected_velocity"]=velocity.tolist()
            audit['last_velocity_by_robot'][str(robots.index(r))]={'raw':raw[r].tolist(),'corrected':velocity.tolist()}
        # Cache the corrected FK transforms rather than the unconstrained predictor.
        coupler._store_gs_rigid_states()
        for r,ad in entries.items():
            for link,previous_transform in zip(ad.joints_child_link,ad.prev_links_transform):
                for env_idx in range(coupler.sim._B):
                    previous_transform[env_idx]=coupler._abd_transforms_by_link[link][env_idx].copy()
        audit["steps"]+=1
    coupler._post_advance_external_articulation=synced
    return audit
