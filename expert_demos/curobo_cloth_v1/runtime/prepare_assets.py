"""Generate a flat-rest square and bake only the robot's initial configuration."""
import hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parent
def fold_vertices(vertices,cfg):
    c=cfg["square"];out=np.array(vertices,dtype=float).copy()
    yaw=np.deg2rad(c.get("yaw_deg",0));rot=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
    uv=(out[:,:2]-c["center_xy"])@rot;normal=np.r_[rot@np.array([1.,-1.])/np.sqrt(2),0.]
    distance=(uv[:,0]-uv[:,1]-c["crease_u_minus_v_m"])/np.sqrt(2)
    flap=distance>1e-10;theta=np.deg2rad(c["fold_angle_deg"])
    out[flap]+=distance[flap,None]*((np.cos(theta)-1)*normal+np.sin(theta)*np.array([0.,0.,1.]))
    return out
def square_mesh(cfg):
    c=cfg["square"];n=c["grid_n"];w=c["width_m"];cx,cy=c["center_xy"]
    v=np.array([[cx+x,cy+y,cfg["table_height"]+c["initial_clearance_m"]]
        for y in np.linspace(-w/2,w/2,n) for x in np.linspace(-w/2,w/2,n)])
    yaw=np.deg2rad(c.get("yaw_deg",0));rot=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
    v[:,:2]=(v[:,:2]-[cx,cy])@rot.T+[cx,cy]
    faces=[]
    for j in range(n-1):
        for i in range(n-1):
            a=j*n+i;b=a+1;d=a+n;cidx=d+1
            faces.extend([[a,b,cidx],[a,cidx,d]])
    f=np.array(faces,dtype=int)
    edges=sorted({tuple(sorted([int(a),int(b)])) for tri in f for a,b in zip(tri,np.roll(tri,-1))})
    return v,f,np.array(edges,dtype=int)
def prepare():
    cfg=json.loads((ROOT/"config.json").read_text());v,f,e=square_mesh(cfg);fold=fold_vertices(v,cfg)
    ratio=np.linalg.norm(fold[e[:,0]]-fold[e[:,1]],axis=1)/np.linalg.norm(v[e[:,0]]-v[e[:,1]],axis=1)
    if not np.allclose(ratio,1,atol=1e-10):raise RuntimeError("Fold crease must follow mesh edges exactly")
    (ROOT/"assets/square.obj").write_text("\n".join(["v %.12g %.12g %.12g"%tuple(x) for x in v]+["f %d %d %d"%tuple(x+1) for x in f])+"\n")
    (ROOT/"assets/cloth_topology.json").write_text(json.dumps({"rest_vertices":v.tolist(),"faces":f.tolist(),"edges":e.tolist(),
        "flat_area_m2":cfg["square"]["width_m"]**2,"rest_shape":"flat","initial_max_edge_ratio":float(ratio.max())},indent=2))
    source=Path(cfg["source_project"])/"assets/panda.xml";tree=ET.parse(source);xml=tree.getroot()
    xml.find("compiler").set("meshdir",str(source.parent/"meshes"))
    names=["joint"+str(i) for i in range(1,8)]+["finger_joint1","finger_joint2"];changes=[]
    for name,target in zip(names,cfg["home"]):
        body=next(b for b in xml.findall(".//body") if b.find("joint") is not None and b.find("joint").get("name")==name)
        j=body.find("joint");old=float(j.get("ref","0"));delta=target-old
        q=np.array(list(map(float,body.get("quat","1 0 0 0").split())));rot=Rotation.from_quat(q[[1,2,3,0]])
        finger=name.startswith("finger");axis=np.array(list(map(float,j.get("axis","0 1 0" if finger else "0 0 1").split())))
        if finger:
            pos=np.array(list(map(float,body.get("pos","0 0 0").split())))+rot.apply(axis*delta)
            body.set("pos"," ".join(format(x,".15g") for x in pos))
        else:
            q=(rot*Rotation.from_rotvec(axis*delta)).as_quat()[[3,0,1,2]]
            body.set("quat"," ".join(format(x,".15g") for x in q))
        j.set("ref",str(target));changes.append({"joint":name,"before_ref":old,"after_ref":target})
    tree.write(ROOT/"assets/panda.xml",encoding="unicode")
    (ROOT/"assets/sources.json").write_text(json.dumps({"reused_asset_project":cfg["source_project"],
        "base_code_commit":"e5289b01758a3f0cbb19d51b9690a0124c150271","source_panda_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
        "robot_reference_changes":changes,"square":"Generated here; no GarmentLab asset; no pinned vertices"},indent=2))
    print("ASSETS_READY",len(v),len(f),len(e))
if __name__=="__main__":prepare()
