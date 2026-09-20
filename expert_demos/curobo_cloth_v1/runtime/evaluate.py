"""End-only object-state evaluation. No cloth coordinate enters policy observations."""
import argparse,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
from table_geometry import on_table_xy
def projected_union_area(vertices,faces,scanlines=2048):
    """Midpoint integration of triangle/scanline interval unions; overlapping layers count once."""
    v=np.asarray(vertices,dtype=float);f=np.asarray(faces,dtype=int)
    if v.ndim!=2 or v.shape[1]!=3 or not np.isfinite(v).all():raise ValueError("Invalid vertices")
    if f.ndim!=2 or f.shape[1]!=3 or len(f)==0:raise ValueError("Invalid triangles")
    t=v[f,:2];ymin=float(t[:,:,1].min());ymax=float(t[:,:,1].max())
    if ymax==ymin:return 0.
    dy=(ymax-ymin)/scanlines;total=0.
    for y in ymin+(np.arange(scanlines)+.5)*dy:
        active=t[(t[:,:,1].min(axis=1)<y)&(t[:,:,1].max(axis=1)>y)]
        if len(active)==0:continue
        a=active;b=np.roll(active,-1,axis=1)
        valid=(np.minimum(a[:,:,1],b[:,:,1])<=y)&(np.maximum(a[:,:,1],b[:,:,1])>y)
        x=np.full(valid.shape,np.nan)
        x[valid]=(a[:,:,0]+np.divide((y-a[:,:,1])*(b[:,:,0]-a[:,:,0]),b[:,:,1]-a[:,:,1],
            out=np.zeros(valid.shape),where=valid))[valid]
        lo=np.nanmin(x,axis=1);hi=np.nanmax(x,axis=1)
        order=np.argsort(lo);lo=lo[order];hi=hi[order]
        left=float(lo[0]);right=float(hi[0]);length=0.
        for l,r in zip(lo[1:],hi[1:]):
            if l<=right:right=max(right,float(r))
            else:length+=right-left;left=float(l);right=float(r)
        total+=length+right-left
    return float(total*dy)
def metrics(vertices,topology,cfg,scanlines=None):
    v=np.asarray(vertices);n=scanlines or cfg["evaluation"]["scanlines"]
    area=projected_union_area(v,topology["faces"],n);heights=v[:,2]-cfg["table_height"]
    e=np.array(topology["edges"]);rest=np.array(topology["rest_vertices"])
    ratio=np.linalg.norm(v[e[:,0]]-v[e[:,1]],axis=1)/np.linalg.norm(rest[e[:,0]]-rest[e[:,1]],axis=1)
    return {"coverage":area/topology["flat_area_m2"],"projected_union_area_m2":area,
        "height_q95_m":float(np.quantile(heights,.95)),"min_height_m":float(heights.min()),
        "on_table_xy_fraction":float(on_table_xy(v,cfg).mean()),"max_height_m":float(heights.max()),
        "max_edge_ratio":float(ratio.max()),"scanlines":n}
def evaluate(run):
    run=Path(run);cfg=json.loads((run/"config.json").read_text())
    topology=json.loads((run/"source_snapshot/assets/cloth_topology.json").read_text());data=np.load(run/"trajectory.npz")
    summary=json.loads((run/"run_summary.json").read_text());initial=json.loads((run/"initial_metrics_private.json").read_text())
    end_tick=int(data["tick"][-1]);hold=round(cfg["evaluation"]["persistence_s"]/cfg["dt"]);threshold=end_tick-hold
    if threshold<0:raise ValueError("Missing persistence interval")
    ticks=data["tick"];indices=np.flatnonzero(ticks>=threshold)
    selected=np.unique(indices[np.rint(np.linspace(0,len(indices)-1,min(6,len(indices)))).astype(int)])
    samples=[dict(tick=int(ticks[i]),**metrics(data["cloth_vertices"][i],topology,cfg)) for i in selected]
    end=samples[-1];fine=metrics(data["cloth_vertices"][-1],topology,cfg,2*cfg["evaluation"]["scanlines"])
    difference=abs(end["coverage"]-fine["coverage"]);released=bool((data["qpos"][selected,0,7:]>=.035).all())
    e=cfg["evaluation"]
    gates={"no_halt":summary["halted"] is None,"coverage":all(s["coverage"]>=e["coverage_min"] for s in samples),
        "coverage_gain":end["coverage"]-initial["coverage"]>=e["coverage_gain_min"],
        "height":all(s["height_q95_m"]<=e["height_q95_max_m"] for s in samples),
        "on_table":all(s["min_height_m"]>=-cfg["gates"]["table_penetration_m"] and s["on_table_xy_fraction"]==1. for s in samples),
        "released":released,"metric_converged":difference<=e["coverage_convergence_tol"],
        "full_hold_recorded":int(ticks[selected[0]])<=threshold+5}
    return {"status":"success" if all(gates.values()) else "not_completed","gates":gates,"initial":initial,"final":end,
        "coverage_gain":end["coverage"]-initial["coverage"],"terminal_samples":samples,"coverage_resolution_difference":difference,
        "mode":summary.get("mode","prepared_grasp"),
        "limitations":("Exploratory single synthetic folded-corner trial; coverage gain starts before the first GPT action, after settling only. No matched passive control or real-robot/generalization claim." if summary.get("mode")=="exploratory_visual_from_fold" else "Single synthetic material; coverage gain starts at GPT handover after mechanical preparation. No autonomous pickup or real-robot claim. Numerically integrated triangle union."),
        "review_status":"SELF_REVIEWED_PROVISIONAL"}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("run");a=p.parse_args();print(json.dumps(evaluate(a.run),indent=2))
