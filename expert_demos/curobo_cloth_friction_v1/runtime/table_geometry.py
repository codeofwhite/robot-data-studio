"""World-space slab unions; the empty corner of an L worktop stays empty."""
import numpy as np

def slab_bounds(table):
    center=np.asarray(table["position"],float);half=np.asarray(table["half_extents"],float)
    if center.shape!=(3,) or half.shape!=(3,) or not np.isfinite(np.r_[center,half]).all() or (half<=0).any():
        raise ValueError("Invalid table geometry")
    return center-half,center+half

def table_slabs(cfg):
    tables=cfg.get('tables')
    if tables is None:tables=[cfg.get('table',{'position':[0,0,.74],'half_extents':[.9,.6,.03]})]
    if not tables:raise ValueError('At least one table slab is required')
    return [slab_bounds(t) for t in tables]

def table_bounds(cfg):
    """Legacy envelope for display; collision queries always use each slab."""
    slabs=table_slabs(cfg)
    return np.min([p[0] for p in slabs],axis=0),np.max([p[1] for p in slabs],axis=0)

def on_table_xy(vertices,cfg,inclusive=True):
    v=np.asarray(vertices);inside=np.zeros(len(v),dtype=bool)
    for lo,hi in table_slabs(cfg):
        inside|=(((v[:,:2]>=lo[:2])&(v[:,:2]<=hi[:2])) if inclusive else ((v[:,:2]>lo[:2])&(v[:,:2]<hi[:2]))).all(axis=1)
    return inside

def table_vertex_penetration(vertices,cfg):
    v=np.asarray(vertices);depth=0.
    for lo,hi in table_slabs(cfg):
        inside=((v>lo)&(v<hi)).all(axis=1)
        if inside.any():depth=max(depth,float(np.minimum(v[inside]-lo,hi-v[inside]).min(axis=1).max()))
    return depth

def segment_hits_table(start,end,cfg,margin=None):
    margin=cfg.get("preparation",{}).get("table_path_clearance_m",0.) if margin is None else margin
    return any(segment_hits_slab(start,end,lo,hi,margin) for lo,hi in table_slabs(cfg))

def segment_hits_slab(start,end,lo,hi,margin):
    p=np.asarray(start,float);d=np.asarray(end,float)-p
    lo=lo-margin;hi=hi+margin;t0=0.;t1=1.
    for axis in range(3):
        if abs(d[axis])<1e-12:
            if p[axis]<lo[axis] or p[axis]>hi[axis]:return False
        else:
            a=(lo[axis]-p[axis])/d[axis];b=(hi[axis]-p[axis])/d[axis]
            t0=max(t0,min(a,b));t1=min(t1,max(a,b))
            if t0>t1:return False
    return True
