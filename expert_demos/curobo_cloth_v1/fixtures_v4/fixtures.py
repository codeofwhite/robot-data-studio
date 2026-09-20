"""Closed component geometry shared by rendering, cuRobo and IPC."""
import numpy as np


def components(spec):
    f=spec['fixture'];kind=f['kind'];x,y=f['center_xy'];parts=[]
    def box(name,pos,size,material):
        parts.append(dict(name=name,shape='box',position=pos,size=size,material=material))
    if kind=='rod':
        z=f['center_height_m'];length=f['length_m']
        parts.append(dict(name='FixtureRod',shape='cylinder',position=[x,y,z],radius=f['radius_m'],length=length,axis='X',material='steel'))
        for side in [-1,1]:
            xx=x+side*(length/2+.018)
            box('FixtureRodPost'+str(side),[xx,y,(.78+z)/2],[.018,.025,z-.78+.018],'steel')
            box('FixtureRodFoot'+str(side),[xx,y,.786],[.045,.10,.012],'dark')
        clamp=spec.get('rod_clamp',{})
        if clamp.get('enabled'):
            cx,cy,cz=clamp['capture_center_world_m']
            connected=clamp.get('revision',3)>=4
            box('FixtureClipMount',[cx,cy+(.033 if connected else .066),z-.015],[.024,.110 if connected else .05,.014],'dark')
            box('FixtureClipBracket',[cx,cy+.081,cz],[.020,.014,.070],'clip')
            box('FixtureClipReach',[cx,cy+.047,cz+.025],[.016,.068,.008],'clip')
            for side in [-1,1]:
                box('FixtureClipJaw'+('Lower' if side<0 else 'Upper'),[cx,cy,cz+side*.019],[.018,.036,.004],'dark')
                parts[-1]['collision']=False
                parts[-1]['role']='Recorded auxiliary clamp jaw indicator; solver constraint supplies the local hold'
            if connected:
                for label in ['Lower','Upper']:
                    box('FixtureClipJaw'+label+'Stem',[cx,cy+.012,cz],[.006,.008,.001],'dark')
                    parts[-1].update(collision=False,role='Recorded jaw actuator display; local solver constraint supplies holding')
    elif kind=='basket':
        w,d,h=f['size_m'];t=f['wall_m'];z=f['base_height_m']
        box('FixtureBasketBottom',[x,y,z+t/2],[w,d,t],'basket')
        for side in [-1,1]:
            box('FixtureBasketSideX'+str(side),[x+side*(w-t)/2,y,z+(h+t)/2],[t,d,h-t],'basket')
            box('FixtureBasketSideY'+str(side),[x,y+side*(d-t)/2,z+(h+t)/2],[w-2*t,t,h-t],'basket')
    elif kind=='box':
        size=f['size_m'];box('FixtureCoverBox',[x,y,f['base_height_m']+size[2]/2],size,'cardboard')
    else:raise ValueError(kind)
    return parts


def add_to_stage(stage,spec):
    from pxr import UsdGeom,UsdShade,UsdPhysics,Gf,Sdf
    materials={}
    for name,color,metal,rough in [('steel',(.42,.46,.49),.85,.27),('dark',(.045,.055,.06),.4,.36),('basket',(.18,.28,.34),0.,.48),('cardboard',(.52,.32,.15),0.,.85),('clip',(.82,.32,.055),.35,.34)]:
        path='/World/Materials/Fixture_'+name;mat=UsdShade.Material.Define(stage,path)
        shader=UsdShade.Shader.Define(stage,path+'/Shader');shader.CreateIdAttr('UsdPreviewSurface')
        for key,typ,val in [('diffuseColor',Sdf.ValueTypeNames.Color3f,Gf.Vec3f(*color)),('metallic',Sdf.ValueTypeNames.Float,metal),('roughness',Sdf.ValueTypeNames.Float,rough)]:shader.CreateInput(key,typ).Set(val)
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface');materials[name]=mat
    for part in components(spec):
        path='/World/'+part['name'].replace('-','Minus')
        if part['shape']=='box':
            geom=UsdGeom.Cube.Define(stage,path);geom.CreateSizeAttr(1.)
            UsdGeom.Xformable(geom).AddTranslateOp().Set(Gf.Vec3d(*part['position']))
            UsdGeom.Xformable(geom).AddScaleOp().Set(Gf.Vec3f(*part['size']))
        else:
            geom=UsdGeom.Cylinder.Define(stage,path);geom.CreateRadiusAttr(part['radius']);geom.CreateHeightAttr(part['length']);geom.CreateAxisAttr(part['axis'])
            UsdGeom.Xformable(geom).AddTranslateOp().Set(Gf.Vec3d(*part['position']))
        UsdShade.MaterialBindingAPI.Apply(geom.GetPrim()).Bind(materials[part['material']])
        UsdPhysics.CollisionAPI.Apply(geom.GetPrim()).CreateCollisionEnabledAttr(part.get('collision',True))
    return components(spec)


def pose_clamp_indicator(stage,spec,row):
    """Display the recorded auxiliary hold, not an unrecorded cloth deformation."""
    from pxr import UsdGeom,Gf
    clamp=spec.get('rod_clamp',{})
    if not clamp.get('enabled'):return
    active=bool(row and row.get('active'))
    center=np.asarray(row['aim_positions_world_m'][0] if active else clamp['capture_center_world_m'])
    for side,label in [(-1,'Lower'),(1,'Upper')]:
        prim=stage.GetPrimAtPath('/World/FixtureClipJaw'+label)
        translation=next(op for op in UsdGeom.Xformable(prim).GetOrderedXformOps() if op.GetOpType()==UsdGeom.XformOp.TypeTranslate)
        translation.Set(Gf.Vec3d(*(center+[0,0,side*(.0023 if active else .019)])))

    if clamp.get('revision',3)>=4:
        fixed_top=spec['fixture']['center_height_m']+spec['fixture']['radius_m']
        for side,label in [(-1,'Lower'),(1,'Upper')]:
            jaw_z=center[2]+side*(.0023 if active else .019)
            a=jaw_z+side*.002
            b=clamp['capture_center_world_m'][2]+.021 if side>0 else fixed_top
            prim=stage.GetPrimAtPath('/World/FixtureClipJaw'+label+'Stem')
            for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
                if op.GetOpType()==UsdGeom.XformOp.TypeTranslate:op.Set(Gf.Vec3d(float(center[0]),float(center[1]+.012),float((a+b)/2)))
                if op.GetOpType()==UsdGeom.XformOp.TypeScale:op.Set(Gf.Vec3f(.006,.008,float(max(abs(a-b),.001))))
