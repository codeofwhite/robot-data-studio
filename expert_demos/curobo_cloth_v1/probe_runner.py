"""Change exactly one approved material parameter, then use the unchanged physical task runner."""
import argparse,sys,copy,math
import runner
p=argparse.ArgumentParser(add_help=False);p.add_argument('--parameter',required=True);p.add_argument('--value',required=True,type=float)
a,rest=p.parse_known_args()
allowed={'gsm':[80.,120.,320.],'thickness':[.0004,.0006,.0012],'E':[30000.,60000.,150000.],'bending':[.004,.01,.02],
         'cloth_friction':[.35,.6,.75],'table_friction':[.35,.6,.8],'gripper_friction':[.35,.6,.8]}
if a.parameter not in allowed or a.value not in allowed[a.parameter]:raise ValueError('Probe must use a frozen one-variable value')
original=runner.configuration
def config(material='medium',initial='nominal',seed=194731):
    if material!='medium' or initial!='nominal':raise ValueError('One-variable probes require medium/nominal baseline')
    c=copy.deepcopy(original(material,initial,seed));before=copy.deepcopy(c['cloth'])
    if a.parameter=='gsm':c['material_provenance']['gsm']=a.value
    elif a.parameter in ['thickness','E','bending']:c['cloth'][a.parameter]=a.value
    elif a.parameter=='cloth_friction':c['cloth']['friction']=a.value
    else:c['surface_friction'][a.parameter.removesuffix('_friction')]=a.value
    gsm=c['material_provenance']['gsm'];c['cloth']['rho']=gsm/1000/c['cloth']['thickness']
    c['nominal_mass_kg']=c['square']['width_m']**2*gsm/1000
    c['parameter_probe']={'parameter':a.parameter,'value':a.value,'baseline':'medium/nominal','baseline_cloth':before,
                          'density_derived_from_gsm_and_thickness':True,'numerical_and_visual_parameters_unchanged':True}
    return c
runner.configuration=config
sys.argv=[sys.argv[0]]+rest
if __name__=='__main__':runner.main()
