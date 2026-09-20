"""Genesis / IPC physics and an isolated display-only scene using the same assets."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
from table_geometry import table_vertex_penetration
def array(x):return x.detach().cpu().numpy().copy() if hasattr(x,"detach") else np.array(x)
def configuration():return json.loads((ROOT/"config.json").read_text())
class Scene:
    def __init__(self,cfg,physics=True):
        import genesis as gs
        self.cfg=cfg;self.physics=physics;self.tick=0
        self.assisted_patch=None;self.assisted_grasp_used=False;self.assisted_trace=None
        source=Path(cfg["source_project"]);a=source/"assets"
        options={}
        if physics:
            options["coupler_options"]=gs.options.IPCCouplerOptions(two_way_coupling=True,enable_rigid_rigid_contact=True,
                constraint_strength_translation=cfg["ipc"].get("constraint_strength_translation",100.0),
                constraint_strength_rotation=cfg["ipc"].get("constraint_strength_rotation",100.0),
                enable_rigid_dofs_sync=True,enable_rigid_ground_contact=False,contact_d_hat=cfg["ipc"]["d_hat"],
                newton_tolerance=cfg["ipc"]["newton_tolerance"],
                newton_translation_tolerance=cfg["ipc"].get("newton_translation_tolerance",.005),
                linear_system_tolerance=cfg["ipc"].get("linear_system_tolerance"),
                contact_friction_enable=True,contact_eps_velocity=cfg["ipc"]["contact_eps_velocity"],sanity_check_enable=True)
        self.world=gs.Scene(show_viewer=False,sim_options=gs.options.SimOptions(dt=cfg["dt"],substeps=1,gravity=(0,0,-9.81) if physics else (0,0,0)),
          rigid_options=gs.options.RigidOptions(iterations=100,tolerance=1e-8,constraint_timeconst=max(.008,2*cfg['dt']),
                         enable_self_collision=True,enable_neutral_collision=True),
          vis_options=gs.options.VisOptions(ambient_light=(.45,.45,.45),background_color=(.78,.78,.76),shadow=True,
              lights=[{"type":"directional","dir":(-1,-1,-2),"color":(1.,.96,.9),"intensity":1.7}]),**options)
        if physics:
            
            from ipc_axis_compat import install_axis_compat
            self.axis_adapter=install_axis_compat(self.world.sim.coupler)
        mu=cfg["cloth"]["friction"]
        def rigid(friction):return gs.materials.Rigid(coup_type=cfg["ipc"].get("rigid_object_coupling","two_way_soft_constraint"),coup_friction=friction) if physics else gs.materials.Rigid()
        binding=cfg.get('scene_binding')
        if binding:
            from scene_adapter import verify_scene_sources,sha
            verify_scene_sources(binding)
            for mesh in binding['collision_meshes'].values():
                if sha(mesh['path'])!=mesh['sha256']:raise ValueError('Scene collision geometry changed')
                if 'physics_mjcf' in mesh:
                    if sha(mesh['physics_mjcf'])!=mesh['physics_mjcf_sha256']:raise ValueError('Scene physics assembly changed')
                    for path,digest in mesh['part_sha256'].items():
                        if sha(path)!=digest:raise ValueError('Scene collision component changed: '+path)
        floor_file=binding['collision_meshes']['environment']['path'] if binding else str(a/'floor.obj')
        table_file=binding['collision_meshes']['table']['path'] if binding else str(a/'table.obj')
        exact_mesh={'convexify':False,'decimate':False,'watertighten':None} if binding else {}
        floor_morph=gs.morphs.MJCF(file=binding['collision_meshes']['environment']['physics_mjcf'],pos=(0,0,0),collision=physics,**exact_mesh) if binding else gs.morphs.Mesh(file=floor_file,pos=(0,0,-.05),fixed=True,collision=physics)
        self.floor=self.world.add_entity(floor_morph,
                   material=rigid(cfg["surface_friction"]["table"]),surface=gs.surfaces.Default(diffuse_texture=gs.textures.ImageTexture(image_path=str(a/"floor_color.png"))))
        table_morph=gs.morphs.MJCF(file=binding['collision_meshes']['table']['physics_mjcf'],pos=(0,0,0),collision=physics,**exact_mesh) if binding and 'physics_mjcf' in binding['collision_meshes']['table'] else gs.morphs.Mesh(file=table_file,pos=(0,0,0) if binding else cfg.get("table",{}).get("position",[0,0,.74]),fixed=True,collision=physics,**exact_mesh)
        self.table=self.world.add_entity(table_morph,
                   material=rigid(cfg["surface_friction"]["table"]),surface=gs.surfaces.Default(diffuse_texture=gs.textures.ImageTexture(image_path=str(a/"oak_color.png"))))
        self.robots=[]
        for base,yaw in zip(cfg["bases"],cfg["yaws"]):
            mat=gs.materials.Rigid(coup_type="external_articulation",coup_friction=cfg["surface_friction"]["gripper"]) if physics else gs.materials.Rigid()
            r=self.world.add_entity(gs.morphs.MJCF(file=str(ROOT/"assets/panda.xml"),pos=base,euler=(0,0,yaw),collision=physics),material=mat)
            for name,value in zip(["joint"+str(i) for i in range(1,8)]+["finger_joint1","finger_joint2"],cfg["home"]):
                r.get_joint(name).init_qpos[:]=value
            self.robots.append(r)
        surf=gs.surfaces.Default(color=(.12,.57,.50,1),roughness=.9,double_sided=True)
        if physics:
            c=cfg["cloth"]
            self.cloth=self.world.add_entity(gs.morphs.Mesh(file=str(ROOT/"assets/square.obj")),
                material=gs.materials.FEM.Cloth(E=c["E"],nu=c["nu"],rho=c["rho"],thickness=c["thickness"],
                       bending_stiffness=c["bending"],friction_mu=mu),surface=surf)
        else:
            self.cloth=self.world.add_entity(gs.morphs.Mesh(file=str(ROOT/"assets/square.obj"),fixed=True,collision=False,enable_custom_vverts=True),surface=surf)
        self.cameras={}
        if not physics:
            c=cfg["camera"]
            self.cameras["top"]=self.world.add_camera(res=tuple(cfg["camera_resolution"]),GUI=False,**c["top"])
            if "front" in c:
                self.cameras["front"]=self.world.add_camera(res=tuple(cfg["camera_resolution"]),GUI=False,**c["front"])
            for name in ["wrist"]:
                self.cameras[name]=self.world.add_camera(res=tuple(cfg["camera_resolution"]),pos=(0,0,1.5),lookat=(0,0,.77),
                                           up=(0,1,0),fov=c["wrist_fov"],GUI=False)
        if physics:
            self.prepare_initial_fold()
            self.prepare_adjacent_ipc()
            if binding:
                import trimesh
                from scipy.spatial import cKDTree
                from scipy.spatial.transform import Rotation
                imported=[]
                for name,entity in self.rigid_objects().items():
                    mesh=binding['collision_meshes']['environment' if name=='floor' else 'table']
                    source_files=list(mesh['part_sha256']) if 'part_sha256' in mesh else [mesh['path']]
                    geoms=[g for link in entity.links for g in link.geoms]
                    if len(source_files)!=len(geoms):raise ValueError('Source and imported collision component counts differ')
                    file_by_geom={g.idx:path for g,path in zip(geoms,source_files)}
                    for link in entity.links:
                        for geom in link.geoms:
                            mesh=trimesh.Trimesh(geom.init_verts,geom.init_faces,process=False)
                            q=np.asarray(geom.init_quat);v=Rotation.from_quat(q[[1,2,3,0]]).apply(geom.init_verts)+geom.init_pos
                            expected=trimesh.load(file_by_geom[geom.idx],force='mesh',process=False).vertices
                            error=max(float(cKDTree(expected).query(v)[0].max()),float(cKDTree(v).query(expected)[0].max()))
                            imported.append({'body':name,'geom':geom.idx,'vertices':len(mesh.vertices),'triangles':len(mesh.faces),'watertight':bool(mesh.is_watertight),
                                'source':file_by_geom[geom.idx],'max_world_vertex_error_m':error})
                (ROOT.parent/'collision_import_audit.json').write_text(json.dumps(imported,indent=2))
                if any(not r['watertight'] for r in imported):raise ValueError('Imported source collision component is not closed; see collision_import_audit.json')
                if any(r['max_world_vertex_error_m']>2e-6 for r in imported):raise ValueError('Physics collision component differs from planner world geometry')
        self.world.build()
        self.contact_link_indices={name:next(i for i,l in enumerate(self.robots[0].links) if l.name==name) for name in ['hand','left_finger','right_finger']}
        if physics:
            from ipc_state_sync import install_state_sync
            self.velocity_sync=install_state_sync(self.world.sim.coupler,self.robots,cfg["dt"])
            import torch
            self.cloth.set_pos(self.world.sim.cur_substep_local,torch.tensor(self.initial_fold,dtype=gs.tc_float,device=gs.device)[None])
            if not np.allclose(self.cloth_vertices(),self.initial_fold,atol=2e-7):raise RuntimeError("Initial native/IPC cloth mismatch")
        for r in self.robots:assert np.allclose(array(r.get_qpos()),cfg["home"],atol=1e-5)
        self._fixed_reference={name:np.r_[array(e.base_link.get_pos()),array(e.base_link.get_quat())] for name,e in self.rigid_objects().items()}
        self._fixed_reference.update({name+'/link0':np.r_[array(r.base_link.get_pos()),array(r.base_link.get_quat())] for name,r in zip(cfg.get('robot_names',['arm']),self.robots)})
        self.topology=json.loads((ROOT/"assets/cloth_topology.json").read_text())
        self.edges=np.array(self.topology["edges"],dtype=int)
        rest=np.array(self.topology["rest_vertices"])
        self.rest_lengths=np.linalg.norm(rest[self.edges[:,0]]-rest[self.edges[:,1]],axis=1)
    def rigid_objects(self):
        return {"floor":self.floor,"table":self.table}
    def attach_cloth_patch(self,vertex_ids):
        raise RuntimeError('Cloth attachments are forbidden in friction-only v1')
    def release_cloth_patch(self):
        raise RuntimeError('No cloth attachment exists in friction-only v1')
    def constraint_audit(self):
        import uipc
        c=self.world.sim.coupler
        objects=c._ipc_objects.find('cloth_0_0')
        if len(objects)!=1:raise RuntimeError('Expected exactly one audited cloth')
        slot=list(objects[0].geometries().ids())[0]
        current,rest=c._ipc_scene.geometries().find(int(slot))
        geom=current.geometry();flags=geom.vertices().find(uipc.builtin.is_constrained)
        active=0 if flags is None else int(np.count_nonzero(flags.view()))
        return {'constrained_vertices':active,'assisted_grasp_used':bool(self.assisted_grasp_used)}
    def cloth_vertices(self):
        return array(self.cloth.get_state().pos).reshape(-1,3)
    def snapshot(self):
        return {"tick":self.tick,"qpos":[array(r.get_qpos()).tolist() for r in self.robots],
                "link_poses":[[np.r_[array(l.get_pos()),array(l.get_quat())].tolist() for l in r.links] for r in self.robots],
                "cloth_vertices":self.cloth_vertices().tolist(),
                "cloth_constrained_vertices":self.constraint_audit()["constrained_vertices"]}
    def physics_health(self):
        fixed={name:e.base_link for name,e in self.rigid_objects().items()}
        fixed.update({name+'/link0':r.base_link for name,r in zip(self.cfg.get('robot_names',['arm']),self.robots)})
        for name,link in fixed.items():
            if not np.allclose(np.r_[array(link.get_pos()),array(link.get_quat())],self._fixed_reference[name],atol=2e-6,rtol=0):
                raise RuntimeError('A body excluded as fixed moved: '+name)
        v=self.cloth_vertices();e=self.edges
        if not np.isfinite(v).all():raise RuntimeError("Nonfinite cloth state")
        ratio=float((np.linalg.norm(v[e[:,0]]-v[e[:,1]],axis=1)/self.rest_lengths).max())
        pen=table_vertex_penetration(v,self.cfg)
        audit=self.constraint_audit()
        if audit["constrained_vertices"] or audit["assisted_grasp_used"]:raise RuntimeError("Forbidden cloth constraint detected")
        return {"max_edge_ratio":ratio,"max_table_vertex_penetration_m":pen,**audit}

    def contact_configuration(self):
        c=self.world.sim.coupler
        return {"contact_link_indices":self.contact_link_indices,"cloth_constraint_audit":self.constraint_audit(),
            "ipc_friction_enabled":bool(c.options.contact_friction_enable),
            "adjacent_contact_audit":self.adjacent_contact_configuration(),
            "ipc_rigid_rigid_enabled":bool(c.options.enable_rigid_rigid_contact),
            "all_collision_links_enabled":all(c._coupling_collision_settings.get(r,{}).get(l,True) for r in list(self.rigid_objects().values())+self.robots for l in r.links),
            "object_coupling_modes":{n:c._coup_type_by_entity[e].name.lower() for n,e in self.rigid_objects().items()},
            "robot_coupling_modes":[c._coup_type_by_entity[r].name.lower() for r in self.robots],
            "soft_constraint_entities":[str(e.uid) for e,m in c._coup_type_by_entity.items() if m.name=="TWO_WAY_SOFT_CONSTRAINT"]}
    def prepare_initial_fold(self):
        import uipc
        from prepare_assets import fold_vertices
        c=self.world.sim.coupler;original=c._add_fem_entities_to_ipc
        def add_folded_current_with_flat_rest():
            original()
            objs=c._ipc_objects.find("cloth_0_0")
            if len(objs)!=1:raise RuntimeError("Expected exactly one physical cloth")
            ids=list(objs[0].geometries().ids())
            if len(ids)!=1:raise RuntimeError("Expected one cloth geometry")
            current,rest=c._ipc_scene.geometries().find(int(ids[0]))
            flat=np.array(rest.geometry().vertices().find(uipc.builtin.position).view()).reshape(-1,3)
            topology=json.loads((ROOT/"assets/cloth_topology.json").read_text())
            if not np.allclose(flat,topology["rest_vertices"],atol=1e-7):raise RuntimeError("Unexpected physical cloth vertex ordering")
            self.initial_fold=np.asarray(topology['initial_vertices']) if 'scene_binding' in self.cfg else fold_vertices(flat,self.cfg)
            uipc.view(current.geometry().vertices().find(uipc.builtin.position)).reshape(-1,3)[:]=self.initial_fold
            rest_after=np.array(rest.geometry().vertices().find(uipc.builtin.position).view()).reshape(-1,3)
            if not np.array_equal(flat,rest_after):raise RuntimeError("Rest geometry changed during initialization")
            if self.cfg.get('assisted_grasp',{}).get('enabled'):
                raise RuntimeError('Friction-only scene rejects assisted configuration')
            self.initial_geometry_audit={"rest_shape":"flat","current_shape":"flat corner over table edge; gravity settles it" if self.cfg["square"]["fold_angle_deg"]==0 else "one corner rotated about mesh-aligned crease",
                "flat_rest_preserved":True,"vertices":len(flat),"pinned_vertices":0,"runtime_pose_setters":0,
                "max_initial_height_m":float(self.initial_fold[:,2].max()-self.cfg["table_height"])}
            if 'scene_binding' in self.cfg:
                self.initial_geometry_audit.update(current_shape='sampled original USD cloth surface',scene=self.cfg['scene_binding']['scene'],
                    source_prim=topology['source_prim'],source_vertex_ids=topology['source_vertex_ids'],
                    initial_max_edge_ratio=topology['initial_max_edge_ratio'])
        c._add_fem_entities_to_ipc=add_folded_current_with_flat_rest

    def prepare_adjacent_ipc(self):
        """Mirror the native adjacent filter on actual merged IPC robot bodies."""
        if not self.cfg["ipc"].get("inherit_native_adjacent_filter"):return
        import uipc
        from genesis.engine.couplers.ipc_coupler.utils import find_target_link_for_fixed_merge
        from safety import Halted,approved_adjacent_pairs
        c=self.world.sim.coupler;original=c._register_contact_pairs
        def register_with_native_adjacency():
            original()
            if c.rigid_solver._enable_adjacent_collision:raise Halted("Native adjacent filter is unexpectedly enabled")
            entries={};native_pairs=set();arms=[]
            for name,entity in self.rigid_objects().items():
                slots=[slot for link,group in c._abd_slots_by_link.items() if link.entity is entity for slot in group]
                if len(slots)!=1:raise Halted("Expected one merged IPC body for "+name)
                elem=c._ipc_abd_contacts[entity]
                entries[name]=(elem,elem,slots)
            if hasattr(self,"cloth"):
                elem=c._ipc_cloth_contacts[self.cloth]
                objs=c._ipc_objects.find("cloth_0_0")
                if len(objs)!=1:raise Halted("Expected one actual IPC cloth object")
                slots=[c._ipc_scene.geometries().find(int(i))[0] for i in objs[0].geometries().ids()]
                if len(slots)!=1:raise Halted("Expected one actual IPC cloth geometry")
                entries["cloth"]=(elem,elem,slots)
            for arm,entity in zip(self.cfg.get('robot_names',['arm']),self.robots):
                arms.append(arm);old=c._ipc_abd_contacts[entity]
                merged={find_target_link_for_fixed_merge(link) for link in entity.links if link.geoms}
                expected={"link"+str(i) for i in range(8)}|{"left_finger","right_finger"}
                if {link.name for link in merged}!=expected:raise Halted("Unexpected merged Panda collision links")
                for link in sorted(merged,key=lambda x:x.idx):
                    name=arm+"/"+link.name;slots=c._abd_slots_by_link.get(link,[])
                    if len(slots)!=1:raise Halted("Missing actual IPC robot body: "+name)
                    elem=c._ipc_contact_tabular.create("native_adjacent_"+name)
                    for slot in slots:elem.apply_to(slot.geometry())
                    entries[name]=(elem,old,slots)
                    if link.parent_idx>=0:
                        parent=entity.links[link.parent_idx-entity.link_start]
                        parent=find_target_link_for_fixed_merge(parent)
                        if parent in merged and parent is not link:
                            native_pairs.add("|".join(sorted([arm+"/"+parent.name,name])))
            if native_pairs!=approved_adjacent_pairs(arms):raise Halted("Native merged adjacency differs from approved 9-pair allowlist")
            self._per_link_contacts=entries;self._native_adjacent_pairs=sorted(native_pairs)
            fixed={'floor','table'}|{a+'/link0' for a in arms}
            self._fixed_foundation_pairs={"|".join(sorted((a,b))) for a in fixed for b in fixed if a!=b} if 'scene_binding' in self.cfg else set()
            if self._fixed_foundation_pairs and any(not r.base_link.is_fixed for r in self.robots):raise Halted('Fixed assembly filter requires fixed robot bases')
            self._contact_reference={};self._contact_arms=arms
            names=sorted(entries)
            for i,a in enumerate(names):
                x,sx,_=entries[a]
                for b in names[i:]:
                    y,sy,_=entries[b];key=a+"|"+b
                    source=c._ipc_contact_tabular.at(sx.id(),sy.id())
                    if not source.is_enabled():raise Halted("Original required IPC contact was disabled: "+key)
                    ref={"friction":source.friction_rate(),"resistance":source.resistance(),"config":source.config()}
                    self._contact_reference[key]=ref
                    c._ipc_contact_tabular.insert(x,y,ref["friction"],ref["resistance"],key not in native_pairs|self._fixed_foundation_pairs,ref["config"])
            for name,(elem,source,slots) in entries.items():
                if "/" in name:c._ipc_contact_tabular.insert(c._ipc_no_collision_contact,elem,0.,0.,False)
            # Validate assigned geometry IDs and actual table before IPC initialization.
            from safety import check_adjacent_contact_configuration
            check_adjacent_contact_configuration(self.adjacent_contact_configuration())
        c._register_contact_pairs=register_with_native_adjacency

    def adjacent_contact_configuration(self):
        import uipc
        from safety import Halted
        c=self.world.sim.coupler;bodies={}
        for name,(element,source,slots) in self._per_link_contacts.items():
            ids=[]
            for slot in slots:
                attr=slot.geometry().meta().find(uipc.builtin.contact_element_id)
                if attr is None:raise Halted("Missing actual geometry contact ID: "+name)
                ids.extend(int(x) for x in array(attr.view()).reshape(-1))
            bodies[name]={"element_id":element.id(),"geometry_contact_ids":ids,
                "geometry_slot_ids":[slot.id() for slot in slots],"source_element_id":source.id()}
        models={};names=sorted(bodies)
        for i,a in enumerate(names):
            for b in names[i:]:
                x=bodies[a]["geometry_contact_ids"][0];y=bodies[b]["geometry_contact_ids"][0]
                model=c._ipc_contact_tabular.at(x,y);key=a+"|"+b
                models[key]={"element_ids":[x,y],"enabled":bool(model.is_enabled()),
                    "friction":model.friction_rate(),"resistance":model.resistance(),"config":model.config(),
                    "reference":self._contact_reference[key]}
        return {"robot_names":self._contact_arms,"bodies":bodies,"actual_pair_models":models,
            'configured_robot_names':self.cfg.get('robot_names',['arm']),'original_scene':'scene_binding' in self.cfg,
            'fixed_base_robots':[name for name,r in zip(self._contact_arms,self.robots) if r.base_link.is_fixed],
            'fixed_foundation_pairs':sorted(self._fixed_foundation_pairs),
            "native_adjacent_collision_enabled":bool(c.rigid_solver._enable_adjacent_collision),
            "native_adjacent_pairs":self._native_adjacent_pairs}
