"""Raw RGB from a display-only replica of the current recorded physical state."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from PIL import Image
from scene import Scene,configuration,array,ROOT
class Cameras:
    def __init__(self,cfg):
        self.cfg=cfg;self.scene=Scene(cfg,physics=False)
        rest=np.array(self.scene.topology["rest_vertices"])
        dist,self.mapping=cKDTree(rest).query(array(self.scene.cloth.get_vverts()).reshape(-1,3))
        if dist.max()>1e-5:raise RuntimeError("Display cloth vertices do not match physical asset")
    def sync(self,snapshot):
        s=self.scene
        for i,(r,q) in enumerate(zip(s.robots,snapshot["qpos"])):
            r.set_qpos(q)
            poses=np.array([np.r_[array(l.get_pos()),array(l.get_quat())] for l in r.links])
            if not np.allclose(poses,snapshot["link_poses"][i],atol=2e-5):raise RuntimeError("Camera replica FK mismatch")
        s.cloth.set_vverts(np.asarray(snapshot["cloth_vertices"])[self.mapping])
        for name,r in zip(["wrist"],s.robots):
            hand=r.get_link("hand");q=array(hand.get_quat());rot=Rotation.from_quat(q[[1,2,3,0]]);p=array(hand.get_pos())
            c=self.cfg["camera"]
            s.cameras[name].set_pose(pos=p+rot.apply(c["wrist_offset"]),lookat=p+rot.apply(c["wrist_look"]),up=rot.apply(c["wrist_up"]))
    def render(self,snapshot,out,obs_id):
        self.sync(snapshot);out=Path(out);out.mkdir(exist_ok=True,parents=True)
        images={};calibration={}
        for name,cam in self.scene.cameras.items():
            rgb=array(cam.render(force_render=True)[0]).astype("uint8")
            path=out/(name+".png");Image.fromarray(rgb).save(path)
            images[name]={"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            calibration[name]={"camera_to_world":array(cam.transform).tolist(),"intrinsics":array(cam.intrinsics).tolist(),"fov_degrees":float(cam.fov),"resolution":self.cfg["camera_resolution"],
                                "camera_axes":"OpenGL: +X right, +Y up, -Z forward"}
        return {"observation_id":obs_id,"physics_tick":int(snapshot["tick"]),"images":images,"calibration":calibration,"replica_fk_verified":True,"display_physics_steps":0}
def snapshot_file(path):
    with np.load(path) as d:return {k:d[k].copy() for k in d.files}
def capture_configuration(replay=None,config_path=None):
    if replay:return json.loads((Path(replay)/"config.json").read_text())
    if config_path:return json.loads(Path(config_path).read_text())
    return configuration()
def main():
    import genesis as gs
    p=argparse.ArgumentParser();p.add_argument("--snapshot");p.add_argument("--output");p.add_argument("--worker",action="store_true");p.add_argument("--replay");p.add_argument("--config");args=p.parse_args()
    cfg=capture_configuration(args.replay,args.config)
    gs.init(backend=gs.cpu,precision="32",seed=cfg["seed"],logging_level="warning")
    cams=Cameras(cfg)
    if args.snapshot:
        result=cams.render(snapshot_file(args.snapshot),args.output,0)
        (Path(args.output)/"verification.json").write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    elif args.worker:
        print("CAMERAS_READY",flush=True)
        for line in sys.stdin:
            job=json.loads(line)
            if job.get("shutdown"):break
            try:result=cams.render(snapshot_file(job["snapshot"]),job["output"],job["observation_id"])
            except Exception as e:result={"error":str(e)}
            print("CAMERA_RESULT "+json.dumps(result),flush=True)
    elif args.replay:
        import av
        run=Path(args.replay);dest=run/"raw_replay";dest.mkdir(exist_ok=False)
        data=np.load(run/"trajectory.npz");fps=cfg["video_fps"]
        containers={};streams={};checks={};frame_map=[]
        for name in cams.scene.cameras:
            c=av.open(str(dest/(name+".mp4")),"w");stream=c.add_stream("libx264",rate=fps)
            stream.width,stream.height=cfg["camera_resolution"];stream.pix_fmt="yuv420p";stream.options={"crf":"20"}
            containers[name]=c;streams[name]=stream
        times=data["tick"]*cfg["dt"];count=int(np.floor(times[-1]*fps))+1
        for frame in range(count):
            ix=int(np.argmin(abs(times-frame/fps)));snap={k:data[k][ix] for k in data.files};cams.sync(snap)
            for name,cam in cams.scene.cameras.items():
                rgb=array(cam.render(force_render=True)[0]).astype("uint8")
                if frame in {0,count//2,count-1}:Image.fromarray(rgb).save(dest/(name+"_"+str(frame).zfill(4)+".png"))
                for packet in streams[name].encode(av.VideoFrame.from_ndarray(rgb,format="rgb24")):containers[name].mux(packet)
            frame_map.append({"frame":frame,"sample":ix,"tick":int(data["tick"][ix])})
        for name,c in containers.items():
            for packet in streams[name].encode():c.mux(packet)
            c.close();path=dest/(name+".mp4")
            with av.open(str(path)) as video:decoded=sum(1 for _ in video.decode(video=0))
            if decoded!=count:raise RuntimeError("Video frame count mismatch")
            checks[name]={"frames":decoded,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size}
        (dest/"verification.json").write_text(json.dumps({"videos":checks,"replica_fk_verified":True,"display_physics_steps":0,"frame_map":frame_map},indent=2))
        print("REPLAY_COMPLETE",json.dumps(checks),flush=True)
if __name__=="__main__":main()
