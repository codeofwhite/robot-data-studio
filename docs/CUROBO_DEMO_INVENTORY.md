# cuRobo 布料专家数据 · 台账（横向索引）

> **本文只是入口，不是权威状态。** 权威依据是各批次的 `manifest.json` 与各 run 的 `evaluation.json`；本文的数字是 **2026-09-23 从磁盘直读的快照**，会随新批次过时。
> 单批次的纵向设计说明（物理模型边界、文件变更表、复现命令）见 [`CUROBO_EXPERT_DEMOS.md`](CUROBO_EXPERT_DEMOS.md)。
> 全仓 `data/` 的文件级成功/失败归类见 [`../data/RUN_INDEX.md`](../data/RUN_INDEX.md)——**两者的"成功"定义不同，见文末第 7 节**。

## 1. 怎么打开图库

五个图库是静态 HTML，**用 `file://` 打开会因相对路径失效**。在服务器上起一个本地服务，**根目录必须是 `data/expert_demos/`**（以 `fixtures_v4/` 为根会让其它四个图库断链）：

```bash
cd /data/zhanghejun/robot-data-studio/data/expert_demos
python3 -m http.server 8899 --bind 127.0.0.1
```

**远程访问沿用仓库既有约定**（同 `README.md` 的 3000/8010/8080）：在 VS Code 里转发 `8899`，**本地端口号保持不变**，然后在本地浏览器打开 `http://127.0.0.1:8899/…`。

> `8899` 只是这个临时图库服务用的端口，**不属于平台保留端口**（3000 前端 / 8010 API / 8080 Collector 是平台端口）。跑完直接停掉即可，不影响 Studio。

| 图库 | 地址 |
|---|---|
| **fixtures_v4（当前主力，12 条完整示范）** | `http://127.0.0.1:8899/curobo-cloth-v1/fixtures_v4/index.html` |
| l_table_v1（最早） | `http://127.0.0.1:8899/curobo-cloth-v1/l_table_v1/index.html` |
| tabletop_v2 | `http://127.0.0.1:8899/curobo-cloth-v1/tabletop_v2/index.html` |
| folding_v3 | `http://127.0.0.1:8899/curobo-cloth-v1/folding_v3/index.html` |
| scene_binding_revision_001 | `http://127.0.0.1:8899/curobo-cloth-v1/scene_binding_revision_001/index.html` |

`curobo-cloth-friction-v1` **没有图库**，只能直接看 run 目录里的 mp4。

单条 run 的视频与证据文件（四个视频 + 证据包，每个示范都有这一套）：

```text
tasks/<task>/<variant>/runs/<run_id>/
├── overview_4x.mp4        # 四倍速总览（图库默认播这个）
├── replay/front.mp4       # 精确状态回放
├── pbr_replay/front.mp4   # 完整主视角，原始速度，RTX
├── pbr_overhead/front.mp4 # 完整俯视角
├── trajectory_view.html   # 交互轨迹
├── evidence.zip           # 证据包
├── evaluation.json        # **任务成败的权威依据**（22 个门）
└── README.md              # 该 run 的数据说明
```

## 2. 先搞清楚：这里有四套互不相同的任务名

**批次任务名不是从 `tasks.json` 那 8 类派生的**，各批次独立命名。四套清单两两之间基本不重叠，这是最容易混的地方。

| 出处 | 任务名 |
|---|---|
| `expert_demos/curobo_cloth_v1/tasks.json`（8 类候选） | `corner_lift`、`edge_retrieve`、`place`、`edge_align`、`feed`、`smooth`、`fold`、`bimanual_unfold` |
| `tabletop_v2`（4 类） | `edge_retrieve_spread` 桌沿取布并铺开、`directed_flatten` 定向铺平、`translate_rotate_align` 平移与旋转对齐、`unfold_corner` 翻开折角 |
| `folding_v3`（5 类） | `unfold_half` 展开对折布、`towel_half_fold` 毛巾单次对折、`folded_transfer` 折好后跨桌搬运、`garment_flip` 衣物整件翻面、`garment_inside_out` 衣物里外翻转 |
| `fixtures_v4`（5 类） | `hang_on_rod` 搭杆悬挂、`retrieve_from_rod` 取下挂布并铺开、`place_in_basket` 布料放入收纳筐、`retrieve_from_basket` 从筐中取布整理、`cover_box` 用布覆盖盒子 |

`tasks.json` 里那 8 类中只有 `corner_lift`、`smooth` 有可执行配方，其余 6 类标 `blocked_recipe_or_profile`。**"8 个任务"和"有成功视频的 5 个任务"是两回事。**

## 3. 批次谱系

| 批次 | 位置（相对 `data/expert_demos/`） | 任务 | 当前完整示范 | 状态依据 |
|---|---|---|---|---|
| `l_table_v1`（最早） | `curobo-cloth-v1/l_table_v1/` | 1 类 × 3 初态 | **0** | 无 manifest；3 初态中 2 个标"场景已生成，动态任务尚未验证" |
| `scene_binding_revision_001` | `curobo-cloth-v1/scene_binding_revision_001/` | 场景绑定修订，不产示范 | — | `REPORT.md` |
| `tabletop_v2` | `curobo-cloth-v1/tabletop_v2/` | 4 类 × 3 初态 | **12**（全 registered，但 `current_task_intent=0`，**已被取代**） | `manifest.json` |
| `folding_v3` | `curobo-cloth-v1/folding_v3/` | 5 类 | **3** | `manifest.json` |
| **`fixtures_v4`（主力）** | `curobo-cloth-v1/fixtures_v4/` | 5 类 × 3 初态 | **12** | `manifest.json` |
| `curobo-cloth-friction-v1` | `curobo-cloth-friction-v1/` | 14 变体复跑 + 5 单变量探针 | **1/14** | `REPORT.md` |
| `tasks.json` 候选矩阵 | `../expert_demos/curobo_cloth_v1/tasks.json` | 8 类 × 3 材料 × 3 初态 = 72 配置 | **2/8 有配方** | `assets/registry` 的 `CFG-` / `VAL-` |

## 4. `fixtures_v4` 的 12 条完整示范

`success=true` 且 `registered=true` 且 `current_task_intent=true`。路径相对 `data/expert_demos/curobo-cloth-v1/fixtures_v4/`。

| 任务 | 初态 | 中文 | run_id | asset_id |
|---|---|---|---|---|
| `retrieve_from_rod` | v001 | 取下挂布并铺开 | `fxv4-retrieve-from-rod-v001-20260918t102649` | `VAL-curobo-cloth-fxv4-retrieve-from-rod-v001-20260918t102649` |
| `retrieve_from_rod` | v002 | 取下挂布并铺开 | `fxv4-retrieve-from-rod-v002-20260918t084959` | `VAL-curobo-cloth-fxv4-retrieve-from-rod-v002-20260918t084959` |
| `retrieve_from_rod` | v003 | 取下挂布并铺开 | `fxv4-retrieve-from-rod-v003-20260918t080637` | `VAL-curobo-cloth-fxv4-retrieve-from-rod-v003-20260918t080637` |
| `place_in_basket` | v001 | 布料放入收纳筐 | `fxv4-place-in-basket-v001-20260918t062446` | `VAL-curobo-cloth-fxv4-place-in-basket-v001-20260918t062446` |
| `place_in_basket` | v002 | 布料放入收纳筐 | `fxv4-place-in-basket-v002-20260918t065002` | `VAL-curobo-cloth-fxv4-place-in-basket-v002-20260918t065002` |
| `place_in_basket` | v003 | 布料放入收纳筐 | `fxv4-place-in-basket-v003-20260918t071219` | `VAL-curobo-cloth-fxv4-place-in-basket-v003-20260918t071219` |
| `retrieve_from_basket` | v001 | 从筐中取布整理 | `fxv4-retrieve-from-basket-v001-20260918t063735` | `VAL-curobo-cloth-fxv4-retrieve-from-basket-v001-20260918t063735` |
| `retrieve_from_basket` | v002 | 从筐中取布整理 | `fxv4-retrieve-from-basket-v002-20260918t110329` | `VAL-curobo-cloth-fxv4-retrieve-from-basket-v002-20260918t110329` |
| `retrieve_from_basket` | v003 | 从筐中取布整理 | `fxv4-retrieve-from-basket-v003-20260918t084552` | `VAL-curobo-cloth-fxv4-retrieve-from-basket-v003-20260918t084552` |
| `cover_box` | v001 | 用布覆盖盒子 | `fxv4-cover-box-v001-20260918t081414` | `VAL-curobo-cloth-fxv4-cover-box-v001-20260918t081414` |
| `cover_box` | v002 | 用布覆盖盒子 | `fxv4-cover-box-v002-20260918t081620` | `VAL-curobo-cloth-fxv4-cover-box-v002-20260918t081620` |
| `cover_box` | v003 | 用布覆盖盒子 | `fxv4-cover-box-v003-20260918t095944` | `VAL-curobo-cloth-fxv4-cover-box-v003-20260918t095944` |

视频路径：`tasks/<task>/<variant>/runs/<run_id>/overview_4x.mp4`（另有 `replay/`、`pbr_replay/`、`pbr_overhead/` 三路）。

`hang_on_rod` 不在此表——见下节。

## 5. 杆上展开（"晾被子"）任务：已尝试、未成功

用户要求的动作序列：**先把布送上横杆，再在杆上分段展开**（类比晾被子）。这是 `fixtures_v4` 里唯一未完成的当前意图任务。

### 5.1 时间线

1. **原始版被否决。** v001/v002/v003 的 `t062446`/`t070155`/`t071442` 是"一次抓取、跨杆搬运、释放"。数值上成功（`numeric_success=true`）且已注册成 `VAL-` 资产，但 `current_task_intent=false`。原因记录在 `reports/rod_task_revision_2.json`：
   > User requires loading the rod then spreading on it with a single arm; original one-grasp carry-and-release lacks the requested stages

2. **修订 2**（2026-09-18）：慢送上杆 → 松开承托 → 左侧换抓铺开 → 右侧换抓铺开 → 松开末端保持。多个 run 全卡在 `rod_supported_spreading` 门。

3. **观察到的物理困难**（`reports/ROD_SUPPORT_OPTION.md`）：单纯抬起杆顶布边横拉，主要带动窄布**整体滑移**；低位拉角和倾斜接近也试过。`orientation_transition_gpu2` 诊断里角点 315 松手前 X≈0.106 m、松手后回到 ≈-0.005 m，杆上支承宽度 0.125 → 0.123 m。

4. **批准"可见止滑夹"备选**（`reports/rod_clip_scope_approval.json`，2026-09-18T13:09:54，用户原话"approve 确实比较难一些，如果布料表面摩擦太滑的话。"）：第一侧布边送入可见止滑夹 → 局部夹固 → 单臂换抓另一侧沿杆展开 → 松开机械手保持垂挂。**代价**：改变了工装与数据语义，夹具保留夹持的版本不声称自由裸杆悬挂。

### 5.2 最好结果：21/22 门通过

最终原型 `fxv4-hang-on-rod-v003-20260920t131001-rod-clip-r4`，14837 ticks / 148.37 s 仿真（墙钟 1949 s），**只卡在 `task_goal_reached` 一门**。

值得注意的是该 run 的 `evaluation.json` 里 **`rod_supported_spreading: true`** —— 早先所有尝试都失败的那一门此时已通过，**展开动作本身成立了**。

夹具确实起了作用：tick 11061 激活，顶点 14，夹持距离 0.0129 m，持续到结束，漂移仅 0.003 m。记录原话：*"the regrasp-slippage failure it was approved to fix did not recur on the clamped side"*。

### 5.3 失败机理：是松手那一下塌的

卡在**第二侧铺开后的松手**。第二侧顶点 329：

| | tick | 世界坐标 (m) | 杆顶附近顶点数 |
|---|---|---|---|
| 松手前 | 13786 | `[0.111, 0.324, 1.035]` | **105** |
| 松手后 | 13962 | `[-0.058, 0.237, 0.824]` | **9** |

回弹 0.169 m，下落 0.211 m。`ROD_CLIP_STATE.json` 的结论：

> The spread works while the second side is held (rod-top vertices 76→105). **It is the let-go that collapses the drape.** With the rod friction-only for every node except the one clamp, a single clamped node cannot hold the spread against the stored elastic tension.

即杆上除那一个夹固点外全靠摩擦，单点扛不住布料储存的弹性张力。

⚠️ **一个必须一并记下的反向证据**：`diagnostics/hang_on_rod/v003/rod_clip_r4/raised_feed_physics` 对照诊断回弹只有 0.044 m，看着更好，但它的起点不同（第一笔约 6 cm vs 完整流程 18.5 cm），记录明确说它"没有走到完整流程用的选择路径，夹固点选择不可移植"。**不能拿它当"其实能行"的证据。**

另有一条 run 是被**外部进程杀掉**的（`t135744-rod-clip-r4`，停在 tick 9958 的 acquire 相位，夹具未激活）：*"external process termination, not a physics halt: no launch.json, no OOM, no reboot, no screen session. **Not resumable because runner.py has no resume flag**"*。

### 5.4 ⚠️ 最终原型没有视频（刻意没有）

`ROD_CLIP_STATE.json` 明确记录：

> `render_rod_clip_when_ready.py refuses success media for a failed evaluation; no two-view video exists for this run`

渲染器**设计上拒绝为失败的评价产出成功媒体**。所以最接近成功的那次（21/22）看不到画面，这是行为而非缺失。

### 5.5 能看的视频

| 类别 | 内容 | 路径（相对 `data/expert_demos/`） |
|---|---|---|
| 历史版完整视频 ×3 | 一次抓取搬运版，**没有杆上铺开** | `curobo-cloth-v1/fixtures_v4/tasks/hang_on_rod/v00{1,2,3}/runs/*t0{62446,70155,71442}/overview_4x.mp4` |
| v003 分段终端 run | `t110208`，完整四路视频 | `curobo-cloth-v1/fixtures_v4/tasks/hang_on_rod/v003/runs/*t110208/overview_4x.mp4` |
| 诊断预览 · 送布快照 | 修订 2 送布 | `curobo-cloth-v1/fixtures_v4/diagnostics/hang_on_rod/v001/revision2_feed_snapshot_6604/feed_preview/front.mp4` |
| 诊断预览 · 自由角第一笔 | 先自由角、后夹 | `curobo-cloth-v1/fixtures_v4/diagnostics/hang_on_rod/v002/free_corner_first_preview/first_stroke/front.mp4` |
| 诊断预览 · r3 夹爪几何 ×2 | 止滑夹几何 | `curobo-cloth-v1/fixtures_v4/diagnostics/hang_on_rod/v003/rod_clip_r3/geometry_preview/pbr_clip_preview{,_v2}/front.mp4` |
| 诊断预览 · r4 夹固末端 | 夹固末端 | `curobo-cloth-v1/fixtures_v4/diagnostics/hang_on_rod/v003/rod_clip_r4/aligned_hem_visual_review/pbr_clamp_terminal/front.mp4` |

另有 `crown_peel` 诊断（从杆上剥开布冠的动作探索）：`crown_peel`（GPU 6）被 KeyboardInterrupt 中断在 657 ticks；`crown_peel_gpu2`（GPU 2,3）完整跑完 6487 ticks。两者都从 `t110208` 的 tick 8282 独立初始化（速度归零），自述 *"Independent control diagnostic, not continuous with parent and **never publishable as a full demonstration**"*。几何诊断见 `reports/crown_peel_geometry.json`。

### 5.6 当前状态与遗留

`reports/ROD_CLIP_STATE.json` → `status: paused_by_user_after_recorded_failure`。遗留三项：

- 第二侧释放回弹未解决
- 3 条当前意图的 hanging rollout 仍需真实视觉审查
- 只有 15 条全部完成才做最终审计

### 5.7 相关文件

`reports/ROD_SUPPORT_OPTION.md`（批准前提案原文）、`reports/ROD_CLIP_STATE.json`（当前权威状态）、`reports/rod_clip_scope_approval.json`（批准记录）、`reports/rod_task_revision_2.json`（修订 2 与三条被取代 run）。

## 6. 诚实清单：未成功与被取代的部分

| 项目 | 事实 |
|---|---|
| `fixtures_v4` / `hang_on_rod` | 3 个初态全部无当前完整示范；最好成绩 21/22 门，无视频（见第 5 节） |
| `fixtures_v4` 其余 run | 大量 `诊断记录` 保留在原地（失败不删、不登记） |
| `folding_v3` | 15 条目里只有 **3 个**注册成功；`folded_transfer` 全部失败（7+2+0 次尝试），`garment_inside_out` 全部失败或未跑 |
| `tabletop_v2` | 12 个全部 registered，但**全部 `current_task_intent=false`**——被后续批次取代，不要拿它当"当前有 12 个" |
| `curobo-cloth-friction-v1` | 14 变体首轮只有 **1 个**验证成功（`unfold_corner v001`）；13 失败、12 未跑。且这是**固定场景工程复跑，不是随机试验成功率** |
| `curobo-cloth-friction-v1` 的 2 ms 探针 | **未通过**：闭爪阶段一侧手指达 0.20624 m/s，触发保留的 0.2 m/s 安全限制。4 ms 的成功不证明时间步鲁棒性 |
| `tasks.json` 8 类候选 | 6 类标 `blocked_recipe_or_profile`，不能导出为成功专家数据 |
| `curobo-cloth-friction-v1` 覆盖箱体 | 首次抓取通过、首次释放后覆盖 75.4%，后续执行降到 20%、再抓失败。**只算阶段性成果**，不计完整成功，也不证明覆盖状态能保持 |

## 7. 证据边界（写任何结论前先读这段）

- 全部结果标记 **`SELF_REVIEWED_PROVISIONAL`**，材料是合成参数，**不是实测布料标定**。
- **`assisted_grasp: true`**：夹爪附近有**已授权的局部辅助夹持**。它不是完全自主，也不是作弊——已披露、可追踪、会释放。`evaluate.json` 有 `assistance_disclosed`、`assistance_trace_complete`、`assistance_released`、`local_assistance_only` 四门管这件事。引用这些数据时必须带上"辅助夹持"这个限定。
- **cuRobo 只做机器人和刚性桌面的运动规划**；布料形变与夹持成败由 Genesis FEM Cloth + IPC 物理和独立 `evaluate.py` 判定，**不是 cuRobo 算出来的**。
- **配置数量 ≠ 成功示范数量**。72 个配置是候选矩阵的规模，不是 72 个成功。
- **单次成功不代表泛化**；独立进程重复也不等于统计独立随机试验。
- **RTX/PBR 视频只改善显示**，不作为新物理轨迹或额外成功样本计数。

## 8. 与 `data/RUN_INDEX.md` 的关系（重要）

`data/RUN_INDEX.md` 是另一个索引，**成功定义不同，两边数字对不上是正常的**：

| | `RUN_INDEX.md` | 本文 |
|---|---|---|
| 判据 | 文件存在性启发式：有 `trajectory.npz` 且无 `failure.txt` | 22 门 `evaluation.json` |
| 扫描范围 | 硬编码两个根：`curobo-cloth-v1/runs`、`curobo-cloth-friction-v1/probes`（`scripts/index_data_runs.py:41-42`） | 全部批次 |
| expert 成功数 | 13 | 12（`fixtures_v4` 当前）+ 12（`tabletop_v2`）+ 3（`folding_v3`） |

### 两个已确认的缺口

1. **新批次完全不在索引里。** 索引脚本只扫 `curobo-cloth-v1/runs/`，**不下潜到 `fixtures_v4/tasks/*/*/runs/`、`tabletop_v2/…`、`folding_v3/…`**。所以 27 个门校验过的示范在 `data/views/expert_passed`（只有 13 条，全是 `l_table_v1` 时代的）里一条都没有。

2. **启发式在新批次上会假阳性。** 失败的 `rod-clip-r4`（`t131001`）与成功的 `cover_box` v001 文件签名**完全一致**——都有 `trajectory.npz`、都没有 `failure.txt`。唯一能区分的是 `evaluation.json` 里的 `success: false` / `failed_gates: ["task_goal_reached"]`。**所以修法不是给 glob 加路径，而是这三批要读 gate，不能读 `failure.txt`。**

> 修 `scripts/index_data_runs.py` 属于代码改动，**不在本台账的范围内**，单独提。

### 另外

`reports/CHANGES.md` 与 `reports/ROD_SUPPORT_OPTION.md` 都指向 `WORK_STATE.json`，但该文件已不存在——现在只有 `reports/WORK_STATE_before_consolidation.json`。**这两处是悬空指针。**

## 9. 已知的持久化缺口

`.gitignore` 忽略 `/data/` 与 `/assets/`。因此本台账引用的**全部** `manifest.json`、`index.html`、mp4、`assets/registry` 都是未跟踪的，"哪个 run 成功了"这个事实只存在于这块盘上，git 里查不到。是否把 `manifest.json` / `index.html` / 各 run 的 `README.md` 与 `evaluation.json` 这类小体积状态文件改为可跟踪，是一个**独立决定**，不在本台账范围内。
