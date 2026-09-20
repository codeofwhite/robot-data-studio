import os,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT.parents[1]/'data/expert_demos/curobo-cloth-v1'
cache=DATA/'cache'
for name in ['tmp','genesis','numba','matplotlib','torch_extensions']:(cache/name).mkdir(parents=True,exist_ok=True)
env=os.environ.copy()
env.update(CUDA_VISIBLE_DEVICES=os.environ.get('CLOTH_GPU','1'),EGL_DEVICE_ID=os.environ.get('CLOTH_GPU','1'),CUDA_LAUNCH_BLOCKING='1',
 PYTHONDONTWRITEBYTECODE='1',PYOPENGL_PLATFORM='egl',OMP_NUM_THREADS='4',
 GS_CACHE_FILE_PATH=str(cache/'genesis'),XDG_CACHE_HOME=str(cache),
 TMPDIR=str(cache/'tmp'),NUMBA_CACHE_DIR=str(cache/'numba'),MPLCONFIGDIR=str(cache/'matplotlib'),
 TORCH_EXTENSIONS_DIR=str(cache/'torch_extensions'))
raise SystemExit(subprocess.call(['/data/zhanghejun/miniconda3/envs/genesis/bin/python','-B','-u',str(ROOT/sys.argv[1])]+sys.argv[2:],cwd=DATA,env=env))
