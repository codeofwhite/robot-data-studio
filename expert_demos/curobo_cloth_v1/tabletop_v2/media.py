"""Measured-state viewer, full-frame accelerated video and batch directory index."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import html
from fractions import Fraction
import datetime

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
BATCH=PROJECT/'data/expert_demos/curobo-cloth-v1/tabletop_v2'

def assistance_metrics(run):
    run=Path(run);dest=run/'visual_assistance_metrics.json'
    if dest.exists():
        value=json.loads(dest.read_text());assert value['trajectory_sha256']==sha(run/'trajectory.npz');return value
    if (run/'evidence.zip').exists():raise ValueError('Published run is immutable')
    constraints={x['tick']:x for x in map(json.loads,(run/'grasp_constraints.jsonl').read_text().splitlines())}
    with np.load(run/'trajectory.npz') as archive:
        ticks=archive['tick'];vertices=archive['cloth_vertices']
    errors=[];sample_ticks=[]
    for i,tick in enumerate(ticks):
        row=constraints.get(int(tick),{});ids=row.get('vertex_ids',[])
        if ids:
            errors.extend(np.linalg.norm(vertices[i,ids]-np.asarray(row['aim_positions_world_m']),axis=1).tolist())
            sample_ticks.extend([int(tick)]*len(ids))
    value=dict(assisted_samples=len(errors),maximum_grasp_constraint_distance_m=max(errors) if errors else None,
        p95_grasp_constraint_distance_m=float(np.percentile(errors,95)) if errors else None,
        maximum_at_tick=sample_ticks[int(np.argmax(errors))] if errors else None,
        trajectory_sha256=sha(run/'trajectory.npz'),note='Recorded node positions versus that tick of the local constraint target; not a pure-contact grip measurement.')
    dest.write_text(json.dumps(value,indent=2));return value

def record_visual_review(run,viewed_frames,observations,known_limitations,*,passed):
    """Call only after a reviewer has actually inspected the named saved frames."""
    run=Path(run).resolve()
    if (run/'evidence.zip').exists():raise ValueError('Published run is immutable')
    assert all(viewed_frames.get(name) for name in ['pbr_replay','pbr_overhead'])
    images=[]
    for folder,indices in viewed_frames.items():
        report=json.loads((run/folder/'verification.json').read_text())
        for i in indices:
            frame=report['frame_map'][i];path=run/folder/frame['image_path']
            assert sha(path)==frame['image_sha256']
            images.append(dict(camera=folder,frame=i,tick=frame['tick'],path=str(path),sha256=sha(path)))
    value=dict(passed=bool(passed),assisted_grasp_disclosed=True,review_status='SELF_REVIEWED_PROVISIONAL',
        reviewer='Codex visual inspection of saved renderer frames',reviewed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        trajectory_sha256=sha(run/'trajectory.npz'),video_sha256=sha(run/'pbr_replay/front.mp4'),
        method='Inspect the named representative real frames in both views; complete sequence separately checked against recorded tick map. No claim of frame-by-frame human review.',
        viewed_images=images,observations=observations,known_limitations=known_limitations,
        assistance_metrics=assistance_metrics(run))
    with (run/'visual_review.json').open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    return value

def overview_and_review_frames(run):
    import av
    report=json.loads((run/'pbr_replay/verification.json').read_text())
    source=run/'pbr_replay/front.mp4';target=run/'overview_4x.mp4'
    assert sha(source)==report['video']['sha256']
    assert sha(run/'trajectory.npz')==report['trajectory_sha256']
    if target.exists():
        overview=json.loads((run/'overview_4x.json').read_text())
        assert overview['video_sha256']==sha(target)
        assert overview['source_video_sha256']==sha(source)
    else:
        fps=Fraction(report['video']['fps'])*4;count=0
        with av.open(str(source)) as original,av.open(str(target),'w') as output:
            stream=output.add_stream('libx264',rate=fps)
            stream.width=original.streams.video[0].width;stream.height=original.streams.video[0].height
            stream.pix_fmt='yuv420p';stream.options={'crf':'19','preset':'medium'}
            for frame in original.decode(video=0):
                frame.pts=count;frame.time_base=1/fps
                for packet in stream.encode(frame):output.mux(packet)
                count+=1
            for packet in stream.encode():output.mux(packet)
        assert count==report['video']['frames']
        overview=dict(source_video=str(source),source_video_sha256=sha(source),
            source_trajectory_sha256=report['trajectory_sha256'],speed_multiplier=4,frames=count,
            fps=float(fps),duration_s=float(count/fps),video_sha256=sha(target),assisted_grasp_disclosed=True,
            processing='All source frames in original order at 4x frame rate; no interpolation, omitted phases or generated frames.')
        (run/'overview_4x.json').write_text(json.dumps(overview,indent=2))
    events=json.loads((run/'events.json').read_text())
    stages={'task_start','acquired','edge_recovered','spread_complete','alignment_complete','corner_unfolded','corner_adjusted','task_complete'}
    selected=[dict(name='initial',tick=0)]+[x for x in events if x['name'] in stages]
    selected.append(dict(name='last_video_frame',tick=report['frame_map'][-1]['tick']))
    views={}
    for folder in ['pbr_replay','pbr_overhead']:
        camera=json.loads((run/folder/'verification.json').read_text());views[folder]=[]
        for event in selected:
            frame=min(camera['frame_map'],key=lambda x:abs(x['tick']-event['tick']))
            views[folder].append(dict(event=event['name'],event_tick=event['tick'],**frame,
                                     absolute_image_path=str(run/folder/frame['image_path'])))
    (run/'visual_review_frames.json').write_text(json.dumps(dict(trajectory_sha256=report['trajectory_sha256'],views=views,
        status='Selected real frames for visual review; selection itself does not establish success.'),indent=2))

def run_guide(run):
    cfg=json.loads((run/'config.json').read_text());spec=cfg['task_spec']
    hero_fps=json.loads((run/'pbr_replay/verification.json').read_text())['video']['fps']
    overhead_fps=json.loads((run/'pbr_overhead/verification.json').read_text())['video']['fps']
    text=f'''# {spec['name']} · {spec['variant_id']}

场景：{cfg['scene_binding']['scene']['asset_id']}，运行：{run.name}。

单 Franka，cuRobo 规划，Genesis FEM / IPC 布料，仿真辅助夹持。辅助点随实际夹爪移动；不使用桌面吸附、不在运行中改写布料位置。材料参数是合成值。本条记录不代表纯摩擦抓取、真机成功率或跨材料泛化。

- `overview_4x.mp4`：保留完整动作顺序的四倍速总览；`overview_4x.json` 保存来源和哈希。
- `pbr_replay/front.mp4`：原场景主视角、{hero_fps:g} Hz 全程回放；`pbr_overhead/front.mp4`：{overhead_fps:g} Hz 全程俯视回放。逐帧 tick 和哈希见各自 `verification.json`。
- `trajectory_view.html`：离线交互几何回放，读取记录的布料顶点、关节和辅助点。
- `trajectory.npz`：物理状态快照；`physics.jsonl`：每步命令与实际状态；`grasp_constraints.jsonl`：辅助夹持目标、节点和偏差。
- `events.json`、`task_progress.json`：动作阶段、重抓尝试和任务指标。
- `config.json`：初态、目标和数值参数；`scene_binding.json`、`source_manifest.json`、`source_snapshot/`：来源、代码与场景快照；`environment_provenance.json`：实际环境版本和引擎文件哈希。
- `replay/verification.json` 指向 Canonical Episode 及文件哈希；Episode 是可追溯数据，不等同于已获准训练的 QA 数据。
- `evaluation.json`：自动指标；`visual_review.json`：看过实帧后的观察；`delivery_verification.json`：最终关联检查。缺少任一检查时，不标作完整成功专家示范。
- `evidence.zip`：登记资产时生成的完整证据包。

若存在 `render_attempts/`，里面保留被替换或中断的渲染尝试；正式视频以 `pbr_replay/` 和 `pbr_overhead/` 的验证报告为准。

控制步长 {cfg['dt']} 秒。全部 GPU 进程保留 `CUDA_VISIBLE_DEVICES=0,1`。主视角和俯视角共用同一轨迹，不重新生成布料运动。显示法线平滑只改变光照，记录顶点保持一致。已知辅助点可能出现毫米级到厘米级滞后，具体观察见视觉检查。
'''
    target=run/'README.md'
    if target.exists():assert target.read_text()==text
    else:target.write_text(text)

def index():
    cat=json.loads((HERE/'catalog.json').read_text());rows=[];cards=[]
    for task,definition in cat['tasks'].items():
        for variant_id in definition['variants']:
            root=BATCH/'tasks'/task/variant_id/'runs';attempts=[]
            for run in sorted(root.glob('*')) if root.exists() else []:
                def read(name):
                    path=run/name;return json.loads(path.read_text()) if path.exists() else {}
                ev=read('evaluation.json');review=read('visual_review.json');delivery=read('delivery_verification.json');intent=read('intent_review.json')
                complete=bool(ev.get('success') and review.get('passed') and delivery.get('passed') and (run/'evidence.zip').exists() and intent.get('expert_eligible') is not False)
                status='完整示范' if complete else ('待视觉检查' if ev.get('success') else ('诊断记录' if ev else '运行中'))
                if intent.get('expert_eligible') is False:status='动作原型，待补完整顺序'
                asset_id='VAL-curobo-cloth-'+run.name
                registered=(PROJECT/'assets/registry'/asset_id/'v000001.json').exists()
                attempts.append(dict(run_id=run.name,path=run.relative_to(BATCH).as_posix(),status=status,
                    success=complete,numeric_success=ev.get('success'),failed_gates=ev.get('failed_gates',[]),
                    registered=registered,asset_id=asset_id if registered else None))
            row=dict(task=task,name=definition['name'],variant=variant_id,attempts=attempts);rows.append(row)
            best=next((x for x in reversed(attempts) if x['success']),attempts[-1] if attempts else None)
            links='尚未运行';preview=''
            if best:
                run=BATCH/best['path'];parts=[]
                for filename,label in [('overview_4x.mp4','四倍速总览'),('pbr_replay/front.mp4','完整主视角'),('pbr_overhead/front.mp4','完整俯视角'),('trajectory_view.html','交互轨迹'),('README.md','数据说明'),('evidence.zip','证据包'),('evaluation.json','任务指标')]:
                    if (run/filename).exists():parts.append('<a href="'+html.escape(best['path']+'/'+filename)+'">'+label+'</a>')
                links=' · '.join(parts)
                if (run/'overview_4x.json').exists():
                    base=html.escape(best['path'])
                    preview='<video controls playsinline preload="none" style="width:100%;border-radius:8px" poster="'+base+'/pbr_replay/front_00000.png" src="'+base+'/overview_4x.mp4"></video><small>四倍速完整动作 · 原始速度见完整主视角</small>'
            cards.append('<article><h2>'+html.escape(definition['name'])+' <small>'+variant_id+'</small></h2><p>'+html.escape(best['status'] if best else '场景已配置')+' · '+str(len(attempts))+' 次记录</p>'+preview+'<p>'+links+'</p></article>')
    BATCH.mkdir(parents=True,exist_ok=True)
    (BATCH/'manifest.json').write_text(json.dumps(dict(batch_id='tabletop_v2',assisted_grasp=True,tasks=rows),ensure_ascii=False,indent=2))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>L 形工作台 · 布料任务示范</title><style>body{font:16px system-ui;max-width:1080px;margin:32px auto;padding:0 20px;background:#edf1ef;color:#153d32}h1{font-size:28px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}article{background:white;border:1px solid #cbd8d1;border-radius:12px;padding:18px}h2{font-size:19px;margin:0}small{color:#5e8273}a{color:#176d54;line-height:2}p{line-height:1.6}</style><h1>L 形工作台 · 四类布料任务</h1><p>单 Franka · cuRobo · 物理布料 · 已授权辅助夹持。每个初态独立存放，完整示范需要轨迹、全程视频、视觉检查和证据包。诊断尝试保留。</p><main>'''+''.join(cards)+'</main></html>'
    (BATCH/'index.html').write_text(page)
    print('INDEX_UPDATED',sum(any(x['success'] for x in r['attempts']) for r in rows),'of',len(rows),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path);args=parser.parse_args()
    if args.run:
        run=args.run.resolve()
        if (run/'evidence.zip').exists():raise ValueError('Published evidence is immutable; use --index only')
        build(run);overview_and_review_frames(run);assistance_metrics(run);run_guide(run)
    index()


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build(run):
    run=Path(run);out=run/'trajectory_view.html'
    if out.exists():
        report=json.loads((run/'trajectory_view.json').read_text())
        assert report['viewer_sha256']==sha(out) and report['source_trajectory_sha256']==sha(run/'trajectory.npz')
        return
    cfg=json.loads((run/'config.json').read_text())
    # NPZ members decompress on each access. Load each array once before the
    # per-frame loop so a long trace does not repeatedly decompress itself.
    with np.load(run/'trajectory.npz') as archive:data={key:archive[key] for key in archive.files}
    topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
    events=json.loads((run/'events.json').read_text());event_ticks={r['tick'] for r in events}
    rows={r['tick']:r for r in map(json.loads,(run/'physics.jsonl').read_text().splitlines())}
    grip_file=run/'grasp_constraints.jsonl'
    grip={r['tick']:r for r in map(json.loads,grip_file.read_text().splitlines())} if grip_file.exists() else {}
    stride=round(.1/cfg['dt']);frames=[]
    for i,t in enumerate(data['tick']):
        t=int(t)
        if t%stride and t not in event_ticks and i!=len(data['tick'])-1:continue
        constraint=grip.get(t,{'vertex_ids':[],'aim_positions_world_m':[]})
        frames.append({'tick':t,'t':round(t*cfg['dt'],6),'phase':rows.get(t,{}).get('phase','settle'),
            'q':np.round(data['qpos'][i,0],6).tolist(),'links':np.round(data['link_poses'][i,0,:,:3],5).tolist(),
            'cloth':np.round(data['cloth_vertices'][i],5).tolist(),'ids':constraint['vertex_ids'],
            'aim':np.round(constraint['aim_positions_world_m'],5).tolist()})
    value={'run':run.name,'scene':cfg['scene_binding']['scene'],'frames':frames,'faces':topology['faces'],
        'task_name':cfg['task_spec']['name'],'target':[p+[cfg['table_height']+.002] for p in cfg['task_spec']['target_outline_xy_m']],
        'tables':cfg.get('tables',[cfg['table']]),'height':cfg['table_height'],'events':events,
        'duration':frames[-1]['t'],'trajectory_sha256':sha(run/'trajectory.npz'),
        'assisted_grasp':cfg.get('assisted_grasp',{}).get('enabled',False),
        'partial_preview':(run/'partial_preview_provenance.json').exists()}
    page=TEMPLATE.replace('__DATA__',json.dumps(value,separators=(',',':'),ensure_ascii=False).replace('</','<\\/'))
    out.write_text(page);(run/'trajectory_view_source.py').write_bytes(Path(__file__).read_bytes())
    report={'source_trajectory_sha256':sha(run/'trajectory.npz'),'source_physics_sha256':sha(run/'physics.jsonl'),
        'viewer_sha256':sha(out),'viewer_code_sha256':sha(__file__),'displayed_frames':len(frames),
        'vertex_rounding_m':.00001,'joint_rounding_rad':.000001,'interpolation':False,
        'scope':'Measured-state geometry viewer; use the separate PBR videos for photorealistic appearance.'}
    if grip_file.exists():report['source_constraint_sha256']=sha(grip_file)
    (run/'trajectory_view.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

TEMPLATE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>L 形工作台 · 轨迹回放</title><style>
*{box-sizing:border-box}body{margin:0;font:14px system-ui,"Noto Sans CJK SC",sans-serif;color:#e7f2ee;background:#112320}header{padding:14px 20px;background:#19332d}h1{font-size:19px;margin:0 0 5px}p{margin:5px 0;color:#b9d0c7}main{padding:10px 18px}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}button,select{font:inherit;color:#e7f2ee;border:1px solid #507569;background:#21483c;border-radius:6px;padding:7px 12px;cursor:pointer}input[type=range]{accent-color:#67d9ae}#time{flex:1;min-width:160px}.stage{border-radius:6px;background:#2a5547;color:#bef6dd;padding:5px 10px}canvas{display:block;width:100%;height:330px;background:#eef1ee;border-radius:8px;margin:9px 0}#numbers{font:12px ui-monospace,monospace;color:#b9d0c7;line-height:1.8;overflow-wrap:anywhere}.events{display:flex;gap:6px;overflow:auto;margin:9px 0}.events button{white-space:nowrap;font-size:12px;padding:5px 8px}.legend{font-size:12px;color:#bfdbcf}.small{font-size:11px;color:#8dac9f}label{font-size:12px;display:flex;gap:5px;align-items:center}</style>
<header><h1 id="taskname">布料任务</h1><p id="subtitle"></p></header><main>
<div class="bar"><button id="play">播放</button><select id="speed"><option value="1">1 倍速</option><option value="4" selected>4 倍速</option><option value="8">8 倍速</option></select><input id="time" type="range" min="0" value="0" step="1"><span id="stamp"></span><span id="phase" class="stage"></span></div>
<canvas id="canvas"></canvas><div class="bar"><button id="view3d">斜视</button><button id="viewtop">俯视</button><label>视角<input id="azimuth" type="range" min="-180" max="180" value="-38"></label><label>高度<input id="elevation" type="range" min="12" max="90" value="44"></label><span class="legend">绿色：布料　白色：机器人连杆　橙色：辅助夹持目标</span></div>
<div id="events" class="events"></div><div id="numbers"></div><p class="small">此视图展示记录中的几何状态；写实画面见关联视频。拖动时间轴不会重新运行物理。显示坐标保留到 0.01 毫米，原始精度见 NPZ。</p><p id="hash" class="small"></p></main>
<script>const D=__DATA__;
const $=id=>document.getElementById(id),C=$('canvas'),ctx=C.getContext('2d');let current=0,playing=false,playTime=0,last=0;
const names={settle:'初始落定',acquire:'抓取',drag:'拖拽',hang:'悬挂',transfer:'转移',lay_down:'放下铺开',regrasp_flatten:'重抓铺平',release:'释放',terminal_hold:'结束',pull:'拉角调整'};
$('subtitle').textContent=D.scene.asset_id+' @v'+D.scene.version+' · '+(D.assisted_grasp?'辅助夹持示范':'接触示范')+' · '+D.run+(D.partial_preview?' · 阶段预览，任务尚未完成':'');
$('taskname').textContent=D.task_name;
$('hash').textContent='轨迹 SHA-256：'+D.trajectory_sha256;$('time').max=D.frames.length-1;
function project(p){const a=Number($('azimuth').value)*Math.PI/180,e=Number($('elevation').value)*Math.PI/180,x=p[0]-.03,y=p[1]-.04,z=p[2]-.9;const u=x*Math.cos(a)+y*Math.sin(a),v=(-x*Math.sin(a)+y*Math.cos(a))*Math.sin(e)+z*Math.cos(e);return [C.clientWidth/2+u*scale,C.clientHeight*.56-v*scale,(-x*Math.sin(a)+y*Math.cos(a))*Math.cos(e)-z*Math.sin(e)];}
let scale=180;
function polygon(vertices,fill,stroke){ctx.beginPath();vertices.forEach((p,i)=>{const q=project(p);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.8;ctx.stroke()}}
function line(a,b,color,width){a=project(a);b=project(b);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.stroke()}
function dot(p,color,r){const a=project(p);ctx.beginPath();ctx.arc(a[0],a[1],r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#314b43';ctx.lineWidth=1;ctx.stroke()}
function draw(){const ratio=Math.min(devicePixelRatio||1,2),w=C.clientWidth,h=C.clientHeight;if(C.width!==w*ratio||C.height!==h*ratio){C.width=w*ratio;C.height=h*ratio}ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);scale=Math.min(w/2.25,h/1.8);const f=D.frames[current];
 const tables=D.tables.map(t=>{const p=t.position,b=t.half_extents,z=p[2]+b[2];return [[p[0]-b[0],p[1]-b[1],z],[p[0]+b[0],p[1]-b[1],z],[p[0]+b[0],p[1]+b[1],z],[p[0]-b[0],p[1]+b[1],z]]});tables.forEach((t,i)=>{polygon(t,'#d9d8cf','#9eaca5');const c=project([D.tables[i].position[0],D.tables[i].position[1],D.height]);ctx.fillStyle='#72847c';ctx.font='13px system-ui';ctx.fillText(i?'B · 操作桌面':'A · 侧桌',c[0]-42,c[1]+30)});
 const target=D.target;for(let i=0;i<4;i++)line(target[i],target[(i+1)%4],'#7baf98',1.5);
 const faces=D.faces.map(face=>({face,depth:face.reduce((s,i)=>s+project(f.cloth[i])[2],0)/3})).sort((a,b)=>b.depth-a.depth);
 for(const {face} of faces){const tri=face.map(i=>f.cloth[i]);const z=tri.reduce((s,p)=>s+p[2],0)/3;const light=Math.max(30,Math.min(57,37+(z-D.height)*30));polygon(tri,'hsl(165,42%,'+light+'%)','#245e5050')}
 for(let i=1;i<Math.min(9,f.links.length);i++){line(f.links[i-1],f.links[i],'#718b80',13);line(f.links[i-1],f.links[i],'#f1f4ef',9)}
 f.links.slice(0,9).forEach(p=>dot(p,'#dce5df',5));if(f.links.length>10){line(f.links[8],f.links[9],'#e9eee8',6);line(f.links[8],f.links[10],'#e9eee8',6)}
 f.ids.forEach((id,i)=>{dot(f.cloth[id],'#f09d4b',5);if(f.aim[i]){line(f.cloth[id],f.aim[i],'#cf7035',2);dot(f.aim[i],'#fff1d8',3)}});
 $('stamp').textContent=f.t.toFixed(2)+' / '+D.duration.toFixed(2)+' 秒';$('phase').textContent=names[f.phase]||f.phase;$('time').value=current;
 $('numbers').textContent='记录步 '+f.tick+' · 关节角（rad） '+f.q.slice(0,7).map(x=>x.toFixed(3)).join('  ')+' · 夹爪开口 '+(1000*(f.q[7]+f.q[8])).toFixed(1)+' mm · 辅助点 '+(f.ids.length?f.ids.join(', '):'已释放');
}
function seek(t){let lo=0,hi=D.frames.length-1;while(lo<hi){const m=Math.ceil((lo+hi)/2);D.frames[m].t<=t?lo=m:hi=m-1}current=lo;playTime=D.frames[lo].t;draw()}
$('time').oninput=()=>{playing=false;$('play').textContent='播放';current=Number($('time').value);playTime=D.frames[current].t;draw()};$('play').onclick=()=>{if(current===D.frames.length-1)seek(0);playing=!playing;$('play').textContent=playing?'暂停':'播放';last=performance.now()};
['azimuth','elevation'].forEach(id=>$(id).oninput=draw);$('viewtop').onclick=()=>{$('azimuth').value=0;$('elevation').value=90;draw()};$('view3d').onclick=()=>{$('azimuth').value=-38;$('elevation').value=44;draw()};
const eventNames={task_start:'任务起始',edge_recovered:'收回桌内',spread_complete:'铺平结束',alignment_complete:'位置方向对齐',corner_unfolded:'翻开折角',corner_adjusted:'拉角完成',settled:'起始',acquired:'抓住',drag_complete:'拖拽结束',hanging_complete:'悬挂',transfer_complete:'转移结束',lay_down_complete:'放下',task_complete:'任务结束'};
D.events.filter(e=>eventNames[e.name]||e.name.startsWith('corner_spread_')).forEach(e=>{const b=document.createElement('button');b.textContent=(eventNames[e.name]||'铺平调整')+' · '+(e.tick*(D.duration/D.frames.at(-1).tick)).toFixed(1)+'s';b.onclick=()=>{playing=false;$('play').textContent='播放';seek(e.tick*(D.duration/D.frames.at(-1).tick))};$('events').appendChild(b)});
function animate(now){if(playing){const target=Math.min(D.duration,playTime+(now-last)/1000*Number($('speed').value));let lo=current;while(lo+1<D.frames.length&&D.frames[lo+1].t<=target)lo++;current=lo;playTime=target;draw();if(target>=D.duration){playing=false;$('play').textContent='播放'}}last=now;requestAnimationFrame(animate)}
window.addEventListener('resize',draw);draw();requestAnimationFrame(animate);
</script></html>'''

if __name__=='__main__':main()
