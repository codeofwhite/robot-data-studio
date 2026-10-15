# Genesis 原生采集与 Isaac 离线渲染

当前推荐 Genesis 原生遥操采集，再从 Episodes 提交 Isaac 离线渲染。原 Genesis＋Isaac 在线桥接保留作诊断，以下主流程与历史记录分别说明。

## 当前主流程：Genesis 原生采集 → Isaac 离线渲染（2026-10-15）

创建会话选择 **Genesis / Cloth Scenes**，默认键盘、20 Hz；实际频率和当前物理后端见 Collector 高级诊断。先使用单臂刚体场景，再验证 `cloth_corner_lift` 原生布料场景。当前原生布料默认是已有 `pbd_legacy`，不是 FEM／IPC。采集过程中不启动 Isaac，不等待其画面。

保存 Episode 后在会话页扫描，到 **Episodes → Isaac 离线渲染** 选择空闲 GPU。可查看初始化／帧进度、失败历史、任务详情与日志、派生 Episode 首帧／逐帧预览。输入不完整的旧数据会提示重新采集；首轮支持现有单臂三种刚体任务与布料角点任务，不支持双臂离线重建。此处复用原生衣物目录，不代表原在线路径的全部 90 个 ClothForge 资产已迁移。

原始 Episode 包含六种标准状态／动作、实际仿真时间、逐帧机器人链接位姿、四路相机世界位姿；布料额外保存物理粒子与速度，manifest 保存对应的固定三角拓扑、源网格哈希、源机器人 XML 哈希及实际求解器。相机位姿在原生渲染后、动作推进前采集，与该行观测一致。

离线渲染复用专家 `Builder` 与 `CachedFrankaPose`，按保存状态设置物体和衣物，按逐帧相机位姿生成同帧 RGB。每帧检查 USD／Genesis 机器人位姿对应；不再调用 Genesis 物理推进。派生数据保持 `engine_id=genesis` 表示物理来源，另记 Isaac 作为图像渲染器，列表显示「Isaac 离线渲染」。

派生 Episode 的 `trajectory.npz` 逐字节复制原文件；图像替换，UUID 更新，lineage 关联父 Episode，`trajectory_modified=false`。源人工／自动结果保持原值，派生 QA 重新为 pending，不自动接受训练数据。旧源文件不会被覆盖。后台沿用现有 Worker 生命周期与 GPU 租约，离线任务不占 Collector 端口，不增加数据库迁移或独立队列。

| 文件 | 本轮新增或替换及原因 |
| --- | --- |
| `gello-remote/src/gello_remote/genesis_worker.py` | 原生 Collector 新增冻结重建元数据、实际相机／机器人链接位姿数组、真实周期及输入观测序号；修正超时周期只有 `sleep(0)` 时的 I/O 调度饥饿。保留原控制、物理步长、标准录制按钮与四路图像。 |
| `ClothTwin/franka_only/cloth_scenes.py` | 新增从实际 PBD／FEM 网格导出拓扑的方法，验证粒子数量与索引范围；不更换物理材料或衣物资产。 |
| `adapters/clothtwin.py` | 原生启动显式选择 EGL GPU；新增托管离线渲染 Worker 分支，使用现有 GPU 资源锁，不启动采集控制台。 |
| `services/episode_render_service.py` | 校验已索引源 Episode、建立独立派生会话、检查源哈希、提供进度并扫描完成结果。 |
| `routes/episodes.py` | 新增 GET／POST `/episodes/{id}/isaac-render`，源数据从索引 ID 解析，不接受浏览器任意文件路径。 |
| `render_episode.py` | 新增标准 Episode 输入适配；复用专家 USD／FK 构建器，输出四路 Isaac JPEG、位姿误差报告与源轨迹完全一致的派生 Episode。失败退出码为 1，未完成内容不发布为正式 Episode。 |
| `app/episodes/page.tsx` | 新增 GPU 选择、进度、失败历史、任务日志入口、派生结果预览和渲染来源标签。 |
| `app/sessions/new/page.tsx` | 主流程说明改为原生采集后离线渲染；Genesis 默认键盘和 20 Hz；原在线桥接入口仍作为独立调试场景保留。 |
| `backend/tests/test_episode_render.py` | 检查旧数据拒绝、源文件不变、源数据变化／被拒绝时阻断、GPU 租约与 API 参数；实际图像编码由原生／Isaac GPU 验收覆盖。 |

本轮完整证据在 `data/native_episode_render_v1/`。最终本机实测（四路 Genesis RGB，20 Hz 目标频率，12 次交替按键，均在录制中测量）：

| 原生路径 | 实际频率中位数 | 计算周期中位数 | 按键到 Canvas 绘制 p95 |
| --- | ---: | ---: | ---: |
| Genesis 刚体 | 19.7 Hz | 41.5 ms | 153.9 ms |
| Genesis PBD 布料 | 17.1 Hz | 51.8 ms | 200.0 ms |

布料首轮 p95 为 283.3 ms，未达到目标；修正事件循环在计算超时后的 I/O 调度后，达到 ≤200 ms 的目标边界。测量关联浏览器发送的按键序号、包含已应用命令的后续观测及对应 JPEG 在 Canvas 的绘制时间，包含本机浏览器解码，但没有测用户 SSH／远端网络或人工试用。每轮 12 个样本是功能验收，不是稳定性能基准；PBD 不能代表 FEM／IPC 的性能。

刚体 151 帧与布料 133 帧均通过 UI 提交，完成四视角 Isaac 离线渲染，共 1136 张 JPEG。布料为 653 个物理粒子、1207 个固定三角面。两条派生轨迹与源 NPZ 逐字节相同，源 manifest／NPZ 哈希不变；人工／自动失败标记按原值保留，派生数据均为 pending QA。逐帧 USD／原始机器人位姿校验最大位置误差分别约 6.20e-7 m／5.73e-7 m。

完成轮询曾触发一次并发扫描 UNIQUE 索引冲突；已在新服务内串行执行一次完成索引，加入四线程回归，并验证八个并发 HTTP 查询均为 200。没有放宽唯一约束或吞掉异常。`acceptance-summary.json`、`native-*-browser.json`、`render-*-acceptance.json` 及截图保存原始证据。

最终回归：Studio 后端 57 项、gello 控制／协议 31 项、ClothTwin 场景／双臂／协议 46 项通过；TypeScript（`tsc --noEmit --incremental false`）与差异检查通过。测试使用独立数据库，未安装依赖、修改驱动、重启用户会话或合并分支。

首轮只支持原生现有单臂场景与新采集的完整状态。旧数据缺少拓扑／相机位姿时明确提示重采，不补造状态；FEM／IPC 和全部 ClothForge 资产的迁移仍单独待验收。此前在线桥接继续保留，不再作为主要采集路径。

下面保留此前在线桥接与卡顿对照的实现历史，不再作为推荐采集方式。

## 纯刚体卡顿对照（2026-10-15）

新建会话选择 **Isaac Sim / Isaac Lab → 单 Franka＋刚体方块 · Genesis IPC 对照**。场景 ID 为 `genesis_ipc_rigid_single`，CLI 为同一 `live.py --rigid-only`。仍为 Genesis 刚体＋IPC 接触、Isaac RTX 渲染、640×480 单相机、相同 Panda 初始姿态与键盘操作。没有 FEM 衣物；8 cm 固定方块作为接触障碍物，本次不提供自由方块抓取。两条路径都支持 Episode 录制。

修改后的控制流及区别：

| 文件 | 本轮行为变更 |
| --- | --- |
| `live.py` | 新增 `--rigid-only`，跳过衣物与 FEM 创建，添加固定方块。原专家接触校验要求存在 cloth，且同步适配只接受固定底座／固定 IPC 物体；新场景在本文件配置同样的 Panda 九对相邻碰撞排除，并继承原接触材料及跨物体接触。未改专家 runtime。 |
| `collector.py` | 原有布料快照／cloth arrays 改为按场景选择；刚体记录 7D `object_pose`，不写伪造的空布料数组。两条路径新增 `timings.jsonl`，现有高级诊断区显示各段毫秒数。 |
| `viewer.py` | 新增方块位姿与尺寸同步；渲染 GPU 从固定物理 0 改为会话选定的物理 GPU，CUDA 仍以逻辑 0 运行。Vulkan 与 CUDA 的设备编号含义不同，曾导致 GPU1 初始化无有效图像；没有改动驱动或其他任务。 |
| `adapters/isaac_sim.py`、`physics_backends.py` | 注册无衣物参数的刚体场景，启动同一 Worker。后端显示名改为 Genesis + IPC，布料场景说明仍明确 FEM Cloth。 |
| `app/sessions/new/page.tsx` | 两个 Genesis/Isaac 场景共用控制和相机配置；刚体场景不请求衣物列表、不显示衣物版本或材料。 |
| 两个相关后端测试 | 补充无衣物启动参数、Episode 根目录与纯刚体状态数组检查。 |

高级诊断的数值均为墙钟耗时：`physics_ms` 是每控制周期 25 个物理步（含 GPU 同步等待）；`snapshot_ms` 是状态读取及发布；`frame_wait_ms` 是录制等待匹配 RGB；`writer_ms` 是帧编码与写入；`cycle_ms` 是整个控制周期。`render_ms` 来自最近一个完成渲染的独立帧，包含机器人 FK 更新、RTX、RGB 获取与图片／数据包写入；它可能和当前物理周期不同步，不能直接与其他列相加。所有数据写在会话 raw 根目录下 `teleop/<launch-id>/`。

物理循环与输入处理目前串行，录制还会等待匹配画面。若物理周期本身慢，输入也只能在下一个控制周期被处理。此对照保留 IPC，没有同时换成 Genesis 原生刚体求解器；不能仅凭体感把原因归为 FEM、IPC 或网络。实际对照结果与截图维护在 `data/genesis_rigid_compare_v1/`。

本轮串行实测（GPU1；丢弃最初两个周期；表为墙钟中位数，单位 ms）：

| 场景／状态 | 样本周期 | 物理推进 | 等待匹配图像 | 整个控制周期 | 最近完成的渲染帧 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 纯刚体／空闲 | 34 | 333 | 0 | 344 | 57 |
| 纯刚体／录制 | 12 | 425 | 106 | 557 | 80 |
| 布料／空闲 | 5 | 1143 | 0 | 1157 | 67 |
| 布料／录制 | 4 | 1309 | 93 | 1431 | 66 |

推断：这组短时测试主要耗时在物理推进链路（包括 IPC 与同步），布料又增加了明显开销；录制时等待同一步图像也增加约 0.1 s。输入队列每控制周期处理一次，因此这条串行结构本身会使遥操不跟手。不能据此拆分 Genesis 刚体、IPC 迭代和状态同步各自的开销，也没有测用户 SSH 隧道／浏览器的端到端延迟。此处不是稳定性或正式性能基准。

验证：真实浏览器纯刚体和布料两轮移动、录制保存、复位均通过；各保存一条 12 帧／4 帧标准 Episode，关节变化均约 0.0346 rad，均通过 `inspect_episode`。纯刚体 Episode 实际被 Studio 扫描 indexed=1、invalid=0。创建页无衣物选项、可创建正确后端会话。51 项后端回归、TypeScript 与差异检查通过。

证据：`data/genesis_rigid_compare_v1/{comparison.json,rigid-browser.json,cloth-browser.json,studio-acceptance.json,rigid-scan.json,rigid-collector.png}`。两轮用同一 GPU 串行执行，测试物理／渲染进程与临时 API 已关闭；用户原有会话未被重启。FPS 显示已排除 Isaac 初次初始化时间；它仍是控制循环平均频率，不是浏览器测得的端到端显示帧率。

## 从原型到正式采集

原型的自定义 HTTP 控制页、暂停按钮和 O/C 夹爪命令，已替换为现有 Collector 键盘页面和 WebSocket 协议。页面复用 `gello-remote` 的 CSS、`collector_common.mjs`、`keyboard_ui.mjs`，保留本地单臂 HTML；没有修改上游源码。点击相机画面后可直接使用键盘。

- 方向键：XY 平移；W/S：上升／下降；Q/E：Roll；A/D：Yaw；Space：开合夹爪。
- 开始采集／C：开始 Episode；采集中 C：人工成功保存；X：人工失败保存；Backspace：丢弃；R：空闲时复位。
- 支持任务描述、帧数、成功／失败、丢弃和复位。单臂键盘控制，尚未接 GELLO 硬件。

| 文件 | 改动与数据流 |
| --- | --- |
| `live.py` | 从承担全部原型职责改为创建 Genesis 单臂场景与调用采集循环；新增 Episode 根目录、控制频率和采集配额参数。复用既有专家 IPC 关节轴、状态同步与接触适配。 |
| `garment_ipc.py` | 抽出资产哈希／材料读取、静止度量恢复、原生顶点和拓扑对应、质量及自由接缝弯曲设置。替换原型顶点全距离矩阵为 KDTree 对应。复杂静止度量不收敛时明确失败。 |
| `collector.py` | 新增共用 Collector HTTP／WebSocket 协议、键盘与生命周期、标准 Franka Episode Writer。物理快照→同一步 RGB→观测与下一个控制周期动作→推进 Genesis。 |
| `viewer.py` | 从只输出预览改为额外原子输出 `capture.npz`，携带物理步、重置编号、RGB 和采集时间；输出真实相机内外参及独立安装版本。渲染器退出时采集报错。 |
| `controls.html` | 删除原型专用控件，使用标准 Collector 布局和录制按钮；单臂提示、可聚焦画布、隐藏不适用的运行中参数区。 |
| `backend/src/robot_data_studio/adapters/isaac_sim.py` | 场景描述改为采集；传入控制频率／配额／UI资源路径；Episode 写入会话 raw 根目录，渲染临时文件仍在每次启动的新目录。未指定版本时新场景选择资产最新版本。 |
| `app/sessions/new/page.tsx` | 衣物选择从注册表读取可读名称与版本，支持资产入口链接；替换“不采集 Episode”提示，提供正式配额及加载状态。 |
| `backend/tests/test_genesis_ipc_collector.py`、`test_isaac_bimanual_adapter.py` | 检查 RGB 步／重置编号匹配、渲染退出、人工与自动结果隔离、最新资产版本和会话根目录传递。 |

## Episode 契约

记录至会话根目录 `episode_XXXXXX/{manifest.json,trajectory.npz,base_rgb/}`；Writer 先写 `.tmp`，完成后原子发布。沿用 `robot_data_episode` v1：18D 原生状态、16D 策略状态、7D 操作者输入、8D requested／safe／applied action。applied 是实际传给位置伺服的关节目标，包含重力补偿偏置；safe 是限速限位后的目标。额外保存衣物顶点、相邻采集快照差分速度、末端位姿、物理步和重置编号。

相机为一个真实 Isaac RTX `base` RGB，640×480。录制逐帧等待 `(reset_id, physics_step)` 完全一致的渲染包；空闲预览允许跳帧。manifest 记录 Isaac／Genesis 版本、物理后端、资产版本与网格哈希、材料、静止几何审计、相机标定和实际仿真步长。人工成功／失败不伪造自动结果：`auto_success=null`，扫描后进入 `pending` QA。

固定名义控制频率默认为 10 Hz（仿真时间），每个控制周期推进整数物理步；IPC／RTX 可能慢于墙钟时间。当前验证约 0.5 个控制周期／秒，不能据此宣称实时 10 FPS。没有辅助抓取或固定衣物节点。

## 本轮验收（2026-10-14）

证据根目录：`data/genesis_ipc_collector_v1/`。

- 浏览器实际成功保存、失败保存、丢弃和复位通过；重置后实际键盘运动已录入第三条 Episode，最大关节变化约 0.03455 rad。
- 3 条 Episode 共 10 帧通过现有 `inspect_episode`；Studio `scan_session` 实际索引 3 条，invalid=0，全部 pending QA。见 `episode-acceptance.json`、`collector.png`。
- 正式创建页浏览器验收通过：90 个衣物选项、会话创建后的 Genesis IPC 配置、现有 Episodes 页面显示 3 条待 QA 数据；见 `studio-acceptance.json`、`create-session.png`、`studio-episodes.png`。使用独立 API8011／测试数据库，浏览器将 API 请求重定向到测试实例，未改生产 CORS 或数据。
- 资产注册表共 90 个最新模型。88 个通过原生 Genesis IPC 装载与两步有限状态检查；不是逐资产机器人任务或长时稳定性验收。见 `native-import/report.json` 与 `native-import.log`。
- 87 个使用原始平面静止度量；1 个 GarmentCode 模型重建三维静止参考，最大相对静止边长误差约 3.57e-12。其弯曲参考为重建装配形状、缝边弯曲为零，不能宣称与原始平面弯曲参考完全等价。
- **2 个仍失败**：`MDL-clothforge-gcd-v2-rand_07sxfm3oxa`、`MDL-clothforge-gcd-v2-rand_0bc49t2k2o`。相对静止边长残差分别约 1.72e-4、1.17e-2，未达到 1e-5 容差。没有将受力后的初态当作静止参考，也没有修改源资产或放宽容差。
- 当前 libuipc shell 从共享三维参考顶点初始化每面参考矩阵；Python 接口未暴露独立逐面 rest matrix 设置。这是两件复杂缝合衣物的待解决导入问题，尚不能声称全部资产可用。

原型接触推移证据仍在 `data/genesis_ipc_teleop_demo/`；最大衣物顶点位移约 0.171 m。夹取抬升未保持住衣物，不计为任务成功。本轮成功按钮仅验收人工标记和保存流程。

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:packages/robot-data-contracts/src \
  backend/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  backend/tests/test_genesis_ipc_collector.py backend/tests/test_isaac_bimanual_adapter.py \
  backend/tests/test_engine_descriptors.py backend/tests/test_sessions.py backend/tests/test_worker_allowlist.py
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node node_modules/typescript/bin/tsc --noEmit --incremental false
git diff --check
```

49 项回归、TypeScript 和差异检查通过。验收物理进程退出码 0，Isaac 子进程组与独立 API 已关闭；GPU0 显存回落至 99 MiB，未停止其他 GPU 任务。浏览器脚本、独立索引数据库和原生资产检查脚本位于本轮证据目录，未改生产数据库。本轮没有安装依赖、修改 Genesis／libuipc／gello 源码或提交／合并；“全部资产可遥操”验收尚差上述两件，不满足最终合并条件。
