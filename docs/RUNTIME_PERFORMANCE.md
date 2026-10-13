# 系统运行速度与工程效率记录

本文件持续记录 Robot Data Studio 的运行瓶颈、工程改动和实测前后对比。区分仿真计算、图像渲染、编码传输与浏览器显示，目标频率不作为实测速度。每轮记录条件与证据，不用预设名称代替性能或物理质量验收。

## 2026-10-13：720 顶点 T 恤的 Newton／PhysX 对照尝试

**最新结论：GPU 0 上两条求解路径都完成有限下落，PhysX 本轮更快，但仍不能解决交互卡顿。** 四相机实际图像刷新 Newton 约 0.51 Hz、PhysX 约 0.93 Hz；两者物理阶段均远超 120 Hz 的预算。PhysX 最终衣物鼓起、最低点距桌面约 2 cm，尚未通过物理质量验收。以下保留 GPU 7 资源不足的失败过程，GPU 0 成功记录见本节末尾。进程返回 0 不作为成功依据。

当前会话 `20261013T170813+0800_clothforge_free_drop_scripted_c2f5745f` 的只读 12 秒采样：720 顶点 T 恤、GPU 0、精确档 8 子步／30 迭代／自碰撞间隔 1，约 6 外层物理步/秒、RTF 0.05；四路实际图像约 0.5 Hz，编码约 8 ms，未观察到编码队列丢帧。观察循环每 12 外层步采图，因此服务器自身两秒左右才产生一张新图，不应首先归因于 WebRTC。该会话后来由用户移入回收站，对照只读取回收站中的原配置，不恢复或修改它。

**批准范围与实现**：仅新增临时脚本 `/tmp/newton-workstation-performance/cloth-solver-compare.py`、该目录的结果和本节记录，没有修改正式 UI、场景 runtime 或共享 SDK。脚本复用现有自由下落场景初始化、v17 桌面、HDRI、四路 960×720 相机和原 T 恤网格/外观，在独立诊断进程内允许 PhysX，复用 `load_garment`／`spawn_garment` 的 PhysX Surface Deformable 路径。Newton 的外层 dt 为 1/120 秒、内部 8 子步；PhysX 用 8 次 1/960 秒物理步组成同一外层周期，衣物迭代数均为 30。两者材料实现不完全等价：PhysX 使用已有厚度、杨氏模量、密度与弯曲单位映射，`tri_kd`／`edge_kd` 没有对应映射，不能当作物理精度等价实验。

计划先初始化相同 RTX 场景，然后分别计时不持续渲染与四相机运行；“physics-only”仍有启动阶段的 RTX/相机资源，不是完全不加载渲染的程序。计时主动同步 CUDA，不能冒充无诊断开销的正常速度。有限步数最初为 264，受共享负载影响后缩短为 120（前 24 步预热，后 96 步推进 0.8 秒）；视频若成功将按仿真 10 Hz 编码，墙钟采图频率另报。

**实测条件与失败**：GPU 7 开始利用率约 2%、可用显存约 8.5 GB；执行期间新增外部实验进程，`nvidia-smi pmon -i 7 -c 1` 观察该进程 SM 占用约 99%。PhysX 启动前只余约 5.3 GB 显存。没有停止外部作业或更换 GPU。

| 项目 | 结果 |
| --- | --- |
| Newton，不持续渲染 | 初始化/首步耗时很长；240 秒上限内未完成有限运行，无稳态计时 |
| Newton，四相机 | 在相同资源饥饿条件下取消重复试验，未计为通过 |
| PhysX，不持续渲染 | 初始化 CUDA OOM，衣物节点读取失败，随后 RTX 渲染失败；退出码 0，但没有结果文件 |
| PhysX，四相机 | 同样在初始化阶段 CUDA OOM，没有结果文件 |

PhysX 明确错误包括 `Unable to allocate memory of size 671088640 for mGpuContactPairsDev`、`Failed to fetch deformable body simulationNodalPositions`，以及随后 DLSS／Hydra 渲染失败。源码的启动配置区分物理 CUDA ordinal 0 与 RTX host ordinal 7；本轮没有足够证据将 OOM 归因于 GPU 映射错误。PhysX 默认刚体接触容量为 `2**23`，本次沿用默认容量，未静默缩小缓冲或关闭自碰撞。有限试验没有形成有效节点轨迹，因此也未能验证下落质量。

**证据与验证**：运行命令为 `/home/zhanghejun/miniconda3/envs/isaaclab/bin/python -B /tmp/newton-workstation-performance/cloth-solver-compare.py`，随后跳过已超时的 Newton 重复项，使用 `--physx-only` 继续。各项 `command.json`、`worker.log`、`gpu-before.txt`／`gpu-after.txt` 和汇总 `summary.json` 位于 `/tmp/newton-workstation-performance/cloth-solver-compare/`。失败记录标为 `verified_run=false`；所有诊断专属进程组已清理，未生成可交付视频、未生成机器人 Episode。脚本 AST 与文档 `git diff --check` 验证通过。

**后续条件**：取得有足够显存、计算负载稳定的 GPU 时间窗口后再做同参数对照，才有条件判断 Newton 接入路径与 PhysX 的速度差异。如果决定为小规模纯衣物配置专门的 PhysX 缓冲预算，需单独说明容量变化及资源验证，不能把 OOM 隐藏成成功或用本次失败作为求解器排名。

### 计算空闲窗口重试与诊断脚本修正

清理后 GPU 7 计算占用降至 0%、可用显存约 6.8 GB，按相同参数重试，结果单独保存到 `cloth-solver-compare/retry-idle/`，保留前面的失败日志。计算空闲不代表显存独占。

| Newton 精确档 | 物理步/秒 | RTF | 物理均值 | 四路采集均值 | 实际图像刷新 |
| --- | --- | --- | --- | --- | --- |
| 不持续渲染 | 6.20 | 0.0517 | 161.17 ms | 不采图 | 不采图 |
| 四相机 | 7.27 | 0.0606 | 134.39 ms | 35.55 ms/四路采集 | 0.620 Hz |

两项均完成 120 外层步（1 秒仿真，前 24 步预热），节点坐标有限；最低点从 1.010 m 落到约 0.761857 m。四相机各 10 帧、10 张不同图像，保存四路短 MP4（按仿真 10 Hz 播放，不代表实时显示），人工查看最终正视图，衣物在桌面且没有机械臂。四相机稳态 96 步中，物理约 12.901 秒、四路采集 8 次合计约 0.284 秒、视口 16 次合计约 0.016 秒：约 98% 计时开销在物理阶段。两项运行的共享负载与短测波动仍存在，不能解读成加相机提速。

PhysX 重试仍没有有效结果：有运行出现 scene 创建/268 MB 显存申请失败，有运行出现 RTX `ERROR_OUT_OF_DEVICE_MEMORY`，随后 CUDA error 700。默认缓冲容量未修改。另修正了临时诊断脚本中 PhysX `ProxyArray` 节点读取：显式 `.torch.detach().cpu().numpy()`；新增异常保存，避免 `app.close()` 的退出过程掩盖 Python 异常。修正后再次尝试的数据位于 `cloth-solver-compare/retry-physx/`，明确 OOM／非法访问，未认定成功。没有修改正式衣物加载代码。

脚本参数 `--retry-idle`、`--physx-only --retry-physx` 仅选择独立结果目录和已批准的试验子集；GPU、网格、材料、时间步、迭代和缓冲容量保持同一配置。失败项与成功的 Newton 项分别保留，不能用原首轮“全部失败”汇总代替后续结果。需要进一步验证 PhysX 时，优先使用显存充足的资源窗口；更换目标 GPU 或调整缓冲预算属于后续追加范围。

### 追加批准：GPU 0 同参数对照完成

用户批准将目标改为 GPU 0。临时脚本新增 `--gpu0`：同时设置 `CUDA_VISIBLE_DEVICES=0` 和 collector `--gpu-id 0`，结果 GPU 字段读取实际 launch 参数，输出单独放在 `cloth-solver-compare/gpu0/`。旧 GPU 7 路径、求解数值、默认缓冲、网格/材质、桌面/相机与有限步数均保留。没有修改正式 UI、启动会话、安装依赖或停止外部作业。

开始前 GPU 0 可用显存约 30 GB、利用率约 77%，仍有其他进程。四项启动前/结束后快照利用率为 68%～77%，不能视为独占、严格控制负载或重复统计。各项均正常完成、坐标有限、没有日志 Error；PhysX 不再发生 GPU 7 的显存不足。启动仍有一次 deformable view 暂未就绪 warning，随后节点轨迹能够读取且完成运动，warning 不等于节点质量验收。

| GPU 0 同一 T 恤精确档 | 外层物理步/秒 | RTF | 物理均值 / P95 | 四路采集均值 | 实际图像刷新 |
| --- | --- | --- | --- | --- | --- |
| Newton，不持续渲染 | 6.14 | 0.0512 | 162.75 / 213.77 ms | 不采图 | 不采图 |
| Newton，四相机 | 6.06 | 0.0505 | 160.42 / 212.85 ms | 54.06 ms | 0.514 Hz |
| PhysX，不持续渲染 | 9.28 | 0.0773 | 107.63 / 136.75 ms | 不采图 | 不采图 |
| PhysX，四相机 | 11.08 | 0.0923 | 85.29 / 118.62 ms | 56.95 ms | 0.934 Hz |

每项 120 外层周期，前 24 周期预热，稳态 96 周期按指定 dt 推进 0.8 秒；PhysX 每周期明确执行 8 次细步。相机仍每 12 外层步采图，未为了显示帧率改变物理节奏。四相机中 Newton 物理计时总量约 15.401 秒、采图 0.432 秒；PhysX 物理约 8.188 秒、采图 0.456 秒，主要开销仍在物理阶段。PhysX 四相机短测较不采图短测快，属于不同运行的负载/短测波动，不能解释为相机改善物理速度。本轮观测到的速度差异不能推广为 VBD 与 PhysX 算法的通用排名。

**运动与物理限制**：两引擎使用相同输入网格和请求参数，各项输出 11 个 720 点样本；Newton 初始最低点 1.010 m、最终约 0.76186 m。PhysX 在初始化后的首个读取最低点约 1.00716 m，比 authored 初始高度低约 2.84 mm，未重写节点位置来隐藏启动差异。PhysX 最终最低点约 0.78000 m、最高点约 0.93995 m；人工检查最终正视图，衣物明显鼓起，相比 Newton 的平铺形态不同。材料/静止形状/接触实现尚未等价，PhysX 未被认定为正确平铺或可直接替代 Newton 的生产配置。该验证不含机械臂、夹持、完整衣物任务或浏览器遥操。

**视频与证据**：两项四相机各输出 `base.mp4`、`top.mp4`、`side.mp4`、`wrist.mp4` 和最终 JPG，逐文件解码确认 960×720、10 帧；原始采集每路 10 张不同图像。MP4 按仿真 10 Hz 播放，只是 1 秒仿真短片，不能作为墙钟流畅性的证据。视频入口分别为 `/tmp/newton-workstation-performance/cloth-solver-compare/gpu0/newton-four-camera/base.mp4` 和 `/tmp/newton-workstation-performance/cloth-solver-compare/gpu0/physx-four-camera/base.mp4`；同目录保存完整命令、GPU 快照、日志、结果与节点轨迹。总汇为 `gpu0/summary.json`，输入一致性、轨迹与视频解码检查为 `gpu0/comparison-verification.json`。

**命令与验证**：`/home/zhanghejun/miniconda3/envs/isaaclab/bin/python -B /tmp/newton-workstation-performance/cloth-solver-compare.py --gpu0`；四项 `verified_run=true` 仅表示有限执行、有限坐标和无日志 Error，不表示物理质量通过。检查请求参数一致、实际 GPU 标记、时间戳递增、视频可解码，脚本 AST 与文档差异/空白检查通过；本轮诊断进程已清理。没有 commit。

## 指标与比较条件

| 指标 | 定义与用途 |
| --- | --- |
| 实际控制 Hz | 墙钟时间内完成的控制周期数；不同于配置目标和 Episode 声明帧率 |
| 物理步/秒 | 墙钟时间内完成的外层物理步数；子步属于同一个外层步 |
| 实时因子 RTF | 推进的仿真秒数 / 墙钟秒数；1 表示实时 |
| 阶段耗时 | 物理、场景同步、视口刷新、相机采集、IK、展示遥测的总耗时、均值和近期 P95 |
| 图像更新与延迟 | 新帧而非重复状态广播的频率；浏览器输入到动作/显示的延迟单独测量 |
| 数据与操作质量 | 浮点状态有限、相机帧数匹配、图像与位姿对应、跟踪偏差、夹爪与接触表现 |

比较必须注明 GPU 型号及是否独占、CPU/软件环境、衣物网格规模、子步与迭代、自碰撞设置、渲染模式、相机数量/分辨率、是否录制、是否启用 WebRTC。计时诊断同步 CUDA，会引入额外开销；与关闭计时的正常运行分开报告。修改驱动、系统调频、多 GPU 或迁移工作站属于独立范围。

## 2026-10-13：基线调查与仿真预算入口

- 用户长裤为 GarmentCodeData 导入模型，10,459 个顶点。工位为 Newton MJWarp + VBD 双向耦合，Isaac RTX 渲染；四相机 960×720，Balanced 渲染。
- 原用户 GPU 0 会话目标控制 10 Hz；只读采样实际约 0.2 Hz，12 秒推进 22 个物理步；JPEG 编码约 8 ms 且无队列积压。调查当时 GPU 0 与另一进程共享，利用率 85%～100%。这些是历史采样，不代表后续资源状态。
- GPU 4 独立 RTX 5090、`--headless --livestream 0` 对照：快速档最终约 0.6 Hz，平衡档约 0.2 Hz，精细档约 0.1 Hz。因此远程网络和 WebRTC 不是当前全部低频的原因。关闭 livestream 仍保留 RTX 相机与 Kit 渲染，不能将其称为仅物理基线。
- UI 已提供快速/平衡/精细/自定义数值入口，Episode 保存具体值。精度预算能改变速度，尚未解决工程瓶颈。详见 [开发日志](EXPERT_AGENT_DEVELOPMENT.md)。
- 证据：`/tmp/newton-workstation-performance/verification.json`，各档 `report.json` 与短 Episode。短控制检查标为 failure，未认定完整布料任务成功。

## 2026-10-13：渲染与遥测调度优化

### 证据和实施内容

原循环每个外层物理步调用 `sim.step()`，当前 IsaacLab 默认同时渲染，另外按 stream cadence 调用 `_pump_kit_frame`。展示遥测也逐步读取双臂关节、夹爪和末端位姿到 CPU，并重复查找右手部件。

修改限定在 `gello-remote/src/gello_remote/isaaclab_gello.py` 的 Newton 衣物运行路径：

1. 物理步使用 `sim.step(render=False)`，按已有显示节奏显式 `sim.render()`，替换额外 Kit pump；非 Newton 衣物路径保留原行为。
2. 相机采集前调用 `sim.render(skip_app_pumping=True)` 同步机械臂和衣物场景状态。相机 renderer 自行渲染和读回，四路原分辨率/录制频率保留，不用旧图像代替新帧。
3. 相机时间从每控制周期只增加一个物理 dt，改为增加自上次采集以来实际经过的物理时间。相机配置周期为 0.1 秒，原更新间隔只传 1/120 秒，约 12 次控制采样才有一张新图；诊断发现并修复该问题。该修改限定 Newton 衣物遥操路径。
4. 展示用 GPU 读回改为控制周期更新，缓存右手部件索引；控制器、安全限制、watchdog 和录制状态读取保持原流程。
5. 添加可选分段计时和 `legacy` / `scheduled` / `physics-only` 诊断模式。计时只有明确传入报告路径时才同步 CUDA。`physics-only` 不采集/显示图像且拒绝录制相机 Episode，不能用它的速度冒充完整遥操速度。

没有改衣物网格、材料、子步/迭代、自碰撞开启状态或安全阈值。BVH 重建、VBD 求解与数值差分 IK 仍需依据计时确定后续优先级。

### 验证记录

本轮在空闲 RTX 5090 GPU 4、端口 18080 重测原循环，不采用旧环境的 0.6 Hz 作为直接提速基线。全部使用同一双臂 ClothForge 场景、导入长裤及快速档 4 子步/10 迭代/每子步首次刷新自碰撞，livestream 关闭。

| 对照 | 实际控制 Hz | 外层物理步/秒 | RTF | 图像说明 |
| --- | --- | --- | --- | --- |
| `runtime-legacy` 原循环 + 计时 | 1.4 | 16.55 | 0.138 | 18 帧，每路仅 2 张不同图像；图像新鲜度检查失败 |
| `runtime-scheduled` 调度优化、尚未修相机时间 + 计时 | 1.6 | 19.03 | 0.159 | 21 帧，每路仅 2 张不同图像；图像新鲜度检查失败 |
| `runtime-physics-only` 无循环图像采集/显示 + 计时 | 1.5 | 18.07 | 0.151 | 不录制、不作为完整遥操速度；保留控制/状态获取开销 |
| `runtime-fresh-final` 调度及相机时间修复 + 计时 | 1.5 | 18.25 | 0.152 | 20 帧，四路各 20 张不同图像；数组有限、采集时间戳递增 |

这是有限短流程，不是稳态多次重复统计。CUDA 计时会同步，各启动的图捕获/预热开销也计入累计均值；仅物理较短，不能把其累计均值直接与完整流程作严格排名。修复相机后实际计算了更多新帧，最终版本与错误缓存图像的旧循环也不属于等工作量对比。先期 `runtime-fresh-cameras` 未正确命中最终采集调用点，仍属旧相机时间，未作为通过证据；后续仅以 `runtime-fresh-final` 验收。早期 `runtime-normal` 关闭计时的结果也先于相机时间修复。

最终带计时运行：物理平均 47.834 ms/步（近期 P95 49.312 ms），物理阶段总计 14.398 秒，占 16.493 秒测量窗口约 87%；相机采集平均 27.202 ms/四路，视口平均 3.605 ms/次，场景同步平均 4.024 ms/次。IK 平均 29.157 ms/调用、近期 P95 254.615 ms（包括无位移快速返回，不能解读为每次运动求解耗时）。尚未区分物理阶段内 CUDA 内核、碰撞、刚体与 CPU 驱动的各自占比，不能声称 BVH 或某个具体内核已确定是根因。

目标物理频率 120 Hz 对应约 8.33 ms 外层步预算，当前稳态仍约 45～49 ms，达不到目标控制 10 Hz。工程修复减少了额外显示/读回并解决新帧错误；没有解决主要的物理速度瓶颈。

最终带计时 Episode 四路各 20 张，轨迹浮点数组全部有限，左右末端存在约 0.15/0.20 m 的 Z 范围变化；检查了录制首/末正视图，双臂与布料可见且形态变化。结束左臂最大跟踪误差 0.006975 rad。检查只是运动、图像与数据流验证，未认定完整衣物抓取任务成功，也未量化图像与位姿的几何配准误差。

临时验证脚本为 `/tmp/newton-workstation-performance/run.py`，各运行分别保存完整命令、worker 日志、`timings.json`、阶段状态和录制结果；仅管理本轮诊断子进程。性能结果需保留失败与限制，不以退出码单独判定通过。


### 命令与后续

- 命令前缀：`/home/zhanghejun/miniconda3/envs/isaaclab/bin/python -B /tmp/newton-workstation-performance/run.py fast`，依次参数 `runtime-legacy legacy`、`runtime-scheduled scheduled`、`runtime-physics-only physics-only`、`runtime-fresh-final scheduled`。诊断线程与子进程结束后清理自己的进程组。
- 关闭计时的最终正常流程：`runtime-fresh-normal scheduled unprofiled`，单独记录结果，不能与同步计时混算。
- 检查：Python AST、两仓库 `git diff --check`、计时器关闭时不调用 CUDA 同步、录制数组/帧数/单调时间戳、运动期间图像内容变化；没有新增测试文件或依赖。
- 临时证据：`/tmp/newton-workstation-performance/runtime-verification.json`，各对照目录 `command.json`、`worker.log`、`timings.json`、阶段状态、Episode。临时路径可能被清理，因此关键参数和数字在本文保留。
- 下一步优先做 Newton 物理内部的 CUDA 内核与 CPU 时间线分析，区分 VBD 自碰撞、双向刚体接触、MJWarp 与主机开销。未改共享 IsaacLab/Newton 依赖、未关闭碰撞、未粗化衣物网格、未降低物理频率。浏览器 WebRTC 实际帧率和端到端延迟尚未验收，不能据此宣布网络无问题。

**关闭计时的最终正常复验**：`runtime-fresh-normal` 实际控制约 1.5 Hz、结束左臂最大跟踪误差 0.007387 rad；四路各 20 帧，每路 20 张不同图像，所有轨迹浮点数组有限，采集时间戳递增。与带计时最终结果接近，额外诊断同步不是当前低速的主要解释。诊断模式没有暴露为 UI 预设；新建 Newton 衣物 worker 默认使用修复后的调度和相机时间。既有运行进程不会自动热更新。真实浏览器/公网 WebRTC 和完整衣物操作未验收。

下一轮拟使用本机已有 `/usr/local/bin/nsys` 做 CUDA graph 内核及 CPU 时间线分析，无需安装。尚未执行该命令，未修改共享 IsaacLab/Newton 求解器；只有确认最耗时内核后才制定数值/碰撞/求解路径修改范围。

## 2026-10-13：Nsight 内部时间线采样（CPU/NVTX 部分有效）

**范围**：使用已有 `/usr/local/bin/nsys`（2024.2.3.38），不安装工具、不改求解器。GPU 4、同一双臂 ClothForge 场景和导入长裤，快速档 4/10/0、`physics-only`、关闭分段计时 CUDA 同步。运行环境仍为既有 IsaacLab Python，诊断脚本复用现有 Kit 库路径。

**实施**：仅修改 `/tmp/newton-workstation-performance/run.py`。诊断 worker 在图捕获预热后的外层步 25～121 标记 `studio_newton_steady`，共 96 步；在采样后正常退出。生产 worker 和求解器没有追加改动。Nsight 将目标置于独立进程组，清理改为只核对本轮日志记录的目标 PID/诊断命令，不影响其他会话。

**尝试与结果**：

- `runtime-nsys`：启动器嵌套进程及 `--wait=all` 阻止正常导出；遗留自有诊断进程已确认身份后清理。
- `runtime-nsys-primary`：前次自有诊断进程占用 18080，新 worker 启动失败；该运行没有有效采样。
- `runtime-nsys-direct`：直接使用同一 Python worker，但结束流程未完整刷新采集报告；未作为通过证据。
- `runtime-nsys-bounded`：worker 正常结束、Nsight 退出码 0，但 CUDA profiler API capture 没有生成报告；显式记为失败，不能用退出码判定采样成功。
- `runtime-nsys-timed`：改用延迟 15 秒、最长 30 秒的定时采集，成功导出约 9.5 MB `trace.nsys-rep` 和 `trace.sqlite`。NVTX 与 OS runtime 数据有效；CUDA kernel/API 数据为空，结论标记为 `PARTIAL_CPU_ONLY`。
- 工具导出检查 `nsys-cpu-check`：0.2 秒 CPU-only 目标能正常生成报告。沙箱阻止工具打开运行资源，使用相同命令提升权限后成功。未改系统 perf 配置。

**有效数据**：预热后 NVTX 窗口为 5.131316952 秒 / 96 个物理步，约 53.451 ms/步。该数字包含采样工具开销，不替换先前关闭计时的正常速度测量。NVTX 所在线程在此窗口仅记录到约 0.59 ms 的 OS runtime 调用；这不代表剩余全部是 GPU 计算，也不能排除用户态 CPU、未记录的 CUDA 等待或驱动开销。其他后台线程等待时间累计不能当作主循环耗时。

**CUDA 采样失败的直接证据**：SQLite `DIAGNOSTIC_EVENT` 记录：

```text
Installed CUDA driver version (12.8) is not supported by this build of Nsight Systems.
CUDA trace will be collected using libraries for driver version 12.5
EnableActivity(handle, kind) returned 39: CUPTI_ERROR_MULTIPLE_SUBSCRIBERS_NOT_SUPPORTED
No CUDA events collected. Does the process use CUDA?
```

`nsys stats` 对 `cuda_gpu_kern_sum` 和 `cuda_api_sum` 明确报告无数据。因此不能给出 VBD、自碰撞、MJWarp 内核的耗时排名，也不能把旧工具兼容错误当成仿真卡顿的根因；仿真不运行 Nsight 时同样慢。驱动版本不受支持与 CUPTI 订阅冲突均已观察，尚未定位另一订阅者。

**命令与证据**：

- 运行：`/home/zhanghejun/miniconda3/envs/isaaclab/bin/python -B /tmp/newton-workstation-performance/run.py fast runtime-nsys-timed physics-only unprofiled nsight`。
- Nsight 参数：`--trace=cuda,nvtx,osrt --cuda-graph-trace=node --sample=none --cpuctxsw=none --capture-range=none --delay=15 --duration=30 --kill=none --wait=primary`；目标及全部场景参数见该目录 `command.json`。
- 导出：`nsys stats --report cuda_gpu_kern_sum,cuda_api_sum,osrt_sum,nvtx_pushpop_sum --format csv --output /tmp/newton-workstation-performance/runtime-nsys-timed/stats /tmp/newton-workstation-performance/runtime-nsys-timed/trace.nsys-rep`。
- 有效窗口分析、失败诊断及数据覆盖范围：`runtime-nsys-timed/analysis-summary.json`；NVTX 主线程 OS runtime 统计：`cpu-steady-summary.json`。报告元数据已改为分别记录 `report_exported` 与 `cuda_data_verified`，避免文件存在被误判为 CUDA 采样通过。
- Python AST、文档本地链接及两仓库 `git diff --check` 检查；18080 端口与 GPU compute 进程检查确认自己的采样已清理。

**下一步拟议，尚未执行**：在 `/tmp/newton-workstation-performance/tools/` 隔离解包新版 Nsight Systems CLI，用其重试同样的采样。不替换系统工具、驱动、CUDA、IsaacLab 或 PyTorch，不运行系统包管理安装。先确认 CUDA 事件实际存在，再依据内核排名制定求解路径优化。新版工具不保证自动解决 CUPTI 订阅冲突，仍需核对采集诊断。

官方依据：[NVIDIA RTX 50 系列工具说明](https://developer.nvidia.com/blog/?p=95580)介绍 Nsight Systems 2025.1 的 Blackwell GPU 指标支持；[官方下载页](https://developer.nvidia.com/nsight-systems/get-started)当前提供独立 Linux x86_64 CLI 包。采样能力和仿真运行能力分开验收。

## 2026-10-13：无机械臂 ClothForge 自由下落对照场景

**入口**：新建 Isaac Sim 会话，选择“ClothForge 自由下落 · 无机械臂”（`clothforge_free_drop`）。自动使用 Scripted 观察模式、Newton 和实验台四相机 v5；选择已注册衣物/版本、外观、仿真预算与最低点距桌面高度。页面不要求机器人 Episode 配额，Collector 为独立观察页面，支持暂停、继续、重置与四视角切换，诊断参数默认折叠。默认下落高度 0.25 m，可调 0.02～1 m。

**物理隔离**：同一 IsaacLab / Isaac Sim 6.0.1 Newton 环境，使用 `NewtonVBDManager` + `SolverVBD`，保留自碰撞和静态桌面接触，不创建 Franka、不创建 MJWarp、不添加悬挂固定点。复用版片原始静止度量、缝合结构、材料/PBR、v17 桌面/HDRI 和相机参数，未改共享 SDK。纯衣物配置的 `integrate_with_external_rigid_solver=False`，实际模型无动态刚体。

**文件与行为变化**：

- Studio `backend/src/robot_data_studio/adapters/isaac_sim.py` 注册新场景、下落高度与观察控制；衣物解析扩展为支持两个 ClothForge 场景，预设数值仍只有一份声明。新增 Scripted 模式只允许新场景，其他 Isaac 场景保留原控制范围。自由下落命令不传 Franka USD，并关闭 livestream，使用观察页面的四路 JPEG。
- Studio `app/sessions/new/page.tsx` 复用衣物/外观/仿真配置，选择观察场景时自动选 Newton/Scripted/v5，隐藏机器人控制选项和 Episode 配额，展示下落高度。UI 采样频率不冒充物理实际频率。
- `gello-remote/src/gello_remote/isaaclab_gello.py` 增加 CLI 场景与 Scripted 分流；在机器人模块初始化前进入观察 runtime。曝光配置沿用 v17 相机 profile；原双臂运行流程保留。
- `gello-remote/src/gello_remote/isaac_clothforge.py` manager factory 新增 `coupled` 选择，默认仍为原双向耦合。纯 VBD 同样在 builder finalize 前恢复版片度量/缝合，避免变成不同材料模型。
- 新增 `gello-remote/src/gello_remote/isaac_cloth_drop.py`：静态场景、衣物、纯 VBD、相机、观察命令、真实速度/接触容量/颜色组统计和诊断产物。相机按经过的物理时间刷新，重置恢复当前/前一状态并重置相机缓存。先初始化 RTX 传感器再应用成像参数，解决无机器人启动时 tone-map 设置尚未初始化的问题。
- 新增 `gello-remote/src/gello_remote/web/cloth_drop.html`：独立观察 UI，单个主画面及四视角按钮，无 Franka 键盘面板。参数折叠，显示平均物理步/秒与平均 RTF。
- 本文及开发日志记录条件、通过项和限制。没有新增依赖或机器人 Episode 协议。

**产物与长会话**：会话目录写入 `cloth_observation_config.json`，结束时写入 `cloth_observation_result.json` 和 `cloth_observation.npz`（衣物粒子状态、采集时间、reset epoch），不生成机器人 Episode。粒子诊断缓存最多 120 个样本；普通观察只保存首帧与最终四路图像，避免持续写入全帧数据。有限 smoke 验证才保存每个采样图像。四路预览采用后台 latest-frame 编码，不让浏览器显示排队旧帧。

### 验证与现场资源条件

- 新建页 `npm --prefix robot-data-studio run build` 成功；现有引擎 descriptor 检查 5 passed；内联检查 scene schema → launch 参数与纯观察命令一致、没有 Franka USD。
- 最初 GPU 4 有其他实验显存占用，运行期间利用率达到 100%、剩余显存约 2.6 GB；中止自己的诊断，没有停止其他作业。用户追加批准将验证与双臂对照移至 GPU 7。GPU 7 初始利用率约 5%、可用显存约 9.9 GB；它也不是独占卡。
- 初始启动发现并修复 Scripted CLI 注册、Newton 扩展先启用、输出路径类型、预览 stats API 和 RTX 成像初始化顺序问题。失败尝试不计为通过。GPU 4 中止运行和失败启动没有纳入速度对照。
- `/tmp/newton-workstation-performance/cloth-drop-gpu7/command.json`：同一导入长裤 10,459 顶点，快速档 4 子步/10 迭代/自碰撞间隔 0，120 Hz 外层物理目标，四路 960×720、Balanced，无 livestream，180 个有限物理步。
- 该运行正常结束，15 次采样、四路各 15 张不同图像、所有粒子坐标有限；最低点从 1.010 m 落到 0.760221 m，最终最高点约 0.790142 m，桌面高度 0.76 m。检查了最终正视图：衣物落在桌面，画面无机械臂。
- 第二轮 `cloth-drop-gpu7-controls` 为 360 步；HTTP 观察页面与 WebSocket 控制检查通过。暂停 0.5 秒期间物理步保持不变，继续推进 23 步，暂停状态下重置最低点恢复 1.010 m，再继续落到桌面。31 次采样对应 30 张不同图像（重置恢复相同初态会重复一次），epoch 为 0/1，数组有限，时间戳递增。控制检查结果存于 `cloth-drop-gpu7/controls-verification.json`，它验证的是第二轮独立控制运行。

| 条件/指标 | 纯衣物自由下落 | 同 GPU 7 双臂 + 衣物 |
| --- | --- | --- |
| 粒子数 | 10,459 | 10,459 |
| 颜色组 | 9，组大小约 1,090～1,198 | 相同 |
| 碰撞形状 | 2（静态桌面/地面） | 24 |
| 动态刚体 | 0 | 24（双臂链接） |
| 软接触容量 | 20,918 | 251,016（12 倍） |
| 本轮平均外层物理步/秒 | 14.17 | 3.72 |
| 本轮 RTF | 0.118 | 0.031 |
| 物理阶段累计均值 | 64.696 ms | 213.178 ms |

**表中速度不构成可靠提速倍数**：两轮虽在同一 GPU，但共享负载在双臂测试期间上升，GPU 7 后续利用率达 100%，相机与物理 P95 都出现明显尖峰。纯衣物控制复验约 14.42 步/秒、RTF 0.120，包含暂停和重置；不与无暂停基线混算。两轮都有同步计时和图像记录开销，尚未取得独占条件的稳态重复统计。

双臂对照 `cloth-drop-coupled-gpu7` 使用临时诊断 wrapper 将初始衣物最低点同样设为桌面 + 0.25 m，并匹配衣物、材料、外观、预算及相机；未修改生产双臂场景的初始高度。协议运动、夹爪和短录制能推进，16 帧四路一致、数组有限，但最终跟踪误差约 0.262 rad，记录标为 failure，不作为完整操作任务成功。诊断清理也处理 Kit 可能忽略 SIGTERM 的子进程组，仅针对本轮自有目标。

### 当前结论与下一步

1. 自由下落功能与观察/重置链路已打通；无机械臂仍未实时，不能把全部开销归于 MJWarp 或机器人耦合。
2. 点数和颜色分组相同时，双臂增加的形状使默认软接触容量放大 12 倍；这是具体的实现开销候选，尚不能把容量比当作耗时比。自碰撞、粒子求解、接触及 CPU/驱动开销仍需有效 GPU 时间线区分。
3. 独占或稳定共享条件下重复这两个场景，再结合有效 CUDA 内核记录判断；新版 Nsight 下载/解包仍未执行。
4. 本轮没有确认所有衣物资产都物理稳定，没有证明真实材料精度，也没有宣布双臂遥操可流畅运行。

汇总证据：`/tmp/newton-workstation-performance/cloth-drop-verification.json`。统计清楚区分外层物理步与控制 Hz；原始命令、状态、配置、图像、NPZ 与计时保留在上述各诊断目录。源码语法、文档链接及两仓库 `git diff --check` 通过；未 commit / push，用户已有 README 修改保留。
