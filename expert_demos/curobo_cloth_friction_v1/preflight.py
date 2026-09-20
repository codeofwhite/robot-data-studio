"""Read-only dependency/device checks; optional actual GPU MotionGen check."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PY='/data/zhanghejun/SIMPLE/.venv/bin/python'
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update(CUDA_VISIBLE_DEVICES='0',PYTHONDONTWRITEBYTECODE='1',
        XDG_CACHE_HOME=str(out/'cache'),TORCH_EXTENSIONS_DIR=str(out/'cache/torch_extensions'))
    result=subprocess.run([PY,'-B','-u',str(ROOT/'planner.py'),'--config',str(ROOT/'runtime/base_config.json'),
                           '--preflight',str(out/'planner.json')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'planner.log').write_text(result.stdout);print(result.stdout[-5000:])
    report={'planner_returncode':result.returncode,'planner_pass':result.returncode==0,'review_status':'SELF_REVIEWED_PROVISIONAL'}
    (out/'preflight.json').write_text(json.dumps(report,indent=2));sys.exit(result.returncode)
if __name__=='__main__':main()
