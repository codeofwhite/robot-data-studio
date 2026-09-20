"""Cached FK for this scene's sibling-body Franka USD; checked against recorded links each frame."""
import numpy as np
from scipy.spatial.transform import Rotation
from pxr import Usd,UsdGeom,UsdPhysics,Gf

class CachedFrankaPose:
 def __init__(self,stage,name):
  root=stage.GetPrimAtPath('/World/'+name);cache=UsdGeom.XformCache();rootworld=np.asarray(cache.GetLocalToWorldTransform(root)).T
  bodies={str(x.GetPath()):x for x in Usd.PrimRange(root) if x.HasAPI(UsdPhysics.RigidBodyAPI)}
  if any(x.GetParent()!=root for x in bodies.values()):raise ValueError('Cached FK requires sibling-body Franka layout')
  joints=[];children=set()
  def frame(j,i):
   q=j.GetPrim().GetAttribute('physics:localRot'+str(i)).Get() or Gf.Quatf(1)
   t=j.GetPrim().GetAttribute('physics:localPos'+str(i)).Get() or Gf.Vec3f(0)
   m=np.eye(4);m[:3,3]=t;m[:3,:3]=Rotation.from_quat([*q.GetImaginary(),q.GetReal()]).as_matrix();return m
  for prim in Usd.PrimRange(root):
   if not prim.IsA(UsdPhysics.Joint):continue
   j=UsdPhysics.Joint(prim);aa=j.GetBody0Rel().GetTargets();bb=j.GetBody1Rel().GetTargets()
   if not aa or not bb:continue
   a,b=str(aa[0]),str(bb[0]);children.add(b);kind='fixed';axis=0;limits=None;drive=None
   if prim.IsA(UsdPhysics.RevoluteJoint):
    typed=UsdPhysics.RevoluteJoint(prim);kind='revolute';limits=(typed.GetLowerLimitAttr().Get(),typed.GetUpperLimitAttr().Get());axis='XYZ'.index(typed.GetAxisAttr().Get());drive=UsdPhysics.DriveAPI.Get(prim,'angular').GetTargetPositionAttr()
   elif prim.IsA(UsdPhysics.PrismaticJoint):kind='prismatic';axis='XYZ'.index(UsdPhysics.PrismaticJoint(prim).GetAxisAttr().Get())
   joints.append((prim.GetName(),a,b,frame(j,0),np.linalg.inv(frame(j,1)),kind,axis,limits,drive))
  self.roots={key:np.linalg.inv(rootworld)@np.asarray(cache.GetLocalToWorldTransform(body)).T for key,body in bodies.items() if key not in children};self.roots[str(root.GetPath())]=np.eye(4)
  known=set(self.roots);self.joints=[]
  while joints:
   ready=[x for x in joints if x[1] in known]
   if not ready:raise ValueError('Unresolved cached USD joint tree')
   for x in ready:self.joints.append(x);known.add(x[2]);joints.remove(x)
  self.attrs={key:body.GetAttribute('xformOp:transform') for key,body in bodies.items()}
  if any(not attr for attr in self.attrs.values()):raise ValueError('Expected authored body matrix transform')
 def apply(self,qs):
  world=dict(self.roots)
  for name,a,b,f0,f1,kind,axis,limits,drive in self.joints:
   value=float(qs.get(name,0));m=np.eye(4)
   if kind=='revolute':
    lo,hi=limits
    if lo is not None and hi is not None and not lo-1e-4<=value<=hi+1e-4:raise ValueError('Cached USD joint outside limits: '+name)
    rv=np.zeros(3);rv[axis]=np.deg2rad(value);m[:3,:3]=Rotation.from_rotvec(rv).as_matrix()
    if drive:drive.Set(value)
   elif kind=='prismatic':m[axis,3]=value
   world[b]=world[a]@f0@m@f1
  for key,attr in self.attrs.items():attr.Set(Gf.Matrix4d(world[key].T))
