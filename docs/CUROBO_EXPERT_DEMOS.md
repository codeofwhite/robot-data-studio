# cuRobo 布料专家数据 v1

> 本文是**单批次的纵向设计说明**（模型边界、文件变更、复现命令）。要看**所有批次的横向台账**——哪些任务、多少成功、视频在哪、怎么打开——见 [`CUROBO_DEMO_INVENTORY.md`](CUROBO_DEMO_INVENTORY.md)。本文只覆盖 `curobo_cloth_v1` 那套 8 类候选矩阵，不含 `fixtures_v4` 等后续批次。

本模块把 cuRobo 规划、真实布料物理、独立评价、逐帧回放与 Studio 资产证据连接起来。材料均为合成参数，尚不是实测布料标定；所有结果标记 SELF_REVIEWED_PROVISIONAL。历史成功示范只提供动作设计参考，新运行不会继承其成功标签。

## 能力与实验门槛

候选矩阵为 8 类任务 × 3 组材料 × 3 种初态，共 72 个配置；21 个单变量探针另列。配置数量不是成功示范数量。可执行控制配方目前是角点夹持/抬升/释放和局部折角展开。桌沿回收、整体搬运、边缘对齐、送料、单折及双臂展开仍标为 blocked_recipe_or_profile，不能导出为成功专家数据。

批量执行前必须满足：正常夹持真实抬起并释放布料；同初态不闭合夹爪对照完整运行但无法夹持/抬升；两者执行代码、配置（除对照标记）一致；轨迹、动作、三路视频、原生 Episode 哈希及帧时序通过。任何前置失败都会阻止批处理。每个配置第一轮失败则停止该配置的重复，保留原因，不改阈值。

data/expert_demos/curobo-cloth-v1 内的 evaluation.json、foundation_gate.json 和批次 report.json 是实际状态依据。冻结候选始终保持创建时状态，后续结果独立注册为 VAL 记录。

## 真实执行与模型边界

- 物理：完整关节 Franka、限力位置伺服与重力补偿、Genesis FEM Cloth + IPC 双向接触。
- 布料采用平整参考网格和折角当前形状；仅初始化时设置形状。运行中不设置布料位置、不固定顶点、不使用附着约束。
- 每步保留关节位置/速度/控制力、请求关节目标、实际电机目标、布料健康和积分序号。
- cuRobo 处理机器人和刚性桌面规划；布料形变及夹持结果由物理执行与独立评价决定。
- SIMPLE 的 cuRobo 定制分支需要显式添加全部碰撞连杆，FK 使用 ee_pose 接口。
- 原指尖球模型含过厚膨胀，阻止贴近布面。collision_model.py 用 50 个包围子盒体的球覆盖每个真实接触垫，并保留近端保守球；桌面及自碰撞检查开启。规划夹爪采用张开配置近似，闭合由真实物理检查。
- 预抓取运行从 cuRobo 计算的 0.85 m 安全悬停姿态独立初始化，不是从成功片段恢复。落定后布料最高点必须在桌面 6 mm 内，避免夹爪初态托住折角。初态与来源哈希写入 config.json。
- 接近阶段每个手指目标为 0.035 m，留出实际接触的行程余量；释放目标仍为 0.04 m。硬限位、力矩和成功阈值不变。
- 密度由 gsm / 1000 / thickness 得出。厚度变化应固定 gsm 并重算密度。E、原生弯曲系数、布/桌/夹爪摩擦分开记录。阻尼未验证，不扫描阻尼。
- 双臂尚未通过接触与速度同步核验。Sharpa、Wuji、G1 静态视觉资产保留，当前不能作为已验证布料控制器。

## 数据和视频

trajectory.npz 保存每 5 个物理步及关键事件处的真实关节状态、连杆姿态、布料顶点和有限差分速度。步长 0.004 s，physics.jsonl 记录每一步。tick=t 的观测对应日志中 tick=t+1 的控制。

原生 Episode 和视频为 10 Hz，每帧保存完整 25 个 250 Hz 控制子步：applied_action_substeps、requested_action_substeps、substep_state_after。主 applied_action 是首个子步；复现两帧间运动应使用完整片段。末尾不足完整片段的图像不作为训练帧导出，原始轨迹仍保留末端状态。

前、顶、腕三路相机来自只显示的状态副本，机器人 FK 逐帧核对。capture_timestamp_ns 明确为仿真时钟，不伪称主机实时采集时间。相机内参与逐帧外参均保存。回放不推进副本物理。

额外 RTX 视频使用相同布料顶点与实际关节状态，以布纹、法线和路径追踪光照呈现。MJCF 与 USD 的 link8 / 右手指有固定坐标旋转，记录显式变换并逐帧验证。RTX 只改善显示，不作为新物理轨迹或额外成功样本计数。

## 文件变更

原有静态场景和历史实验没有修改，也没有删除原有实现。

| 文件 | 新增内容及用途 |
|---|---|
| preflight.py | 隔离环境中的 GPU 规划前置检查、失败日志 |
| planner.py | JSON 规划进程、桌面坐标变换、MotionGen 路径和 FK |
| collision_model.py | 指尖实际接触垫的保守球覆盖 |
| profiles.py | 合成材料、初态、单/双臂可用状态与 SI 参数转换 |
| tasks.json | 8 类任务冻结目标；未实现配方不标成功 |
| parameter_sweep.py | 72 候选及 21 单变量探针目录 |
| probe_runner.py | 7 类材料参数的单变量执行入口，固定网格、步长与视觉 |
| reference_actions.json | 历史动作参考及哈希，不复制成功标签 |
| scene_adapter.py | 每次运行独立物理资产、代码快照、共享资产指纹 |
| runner.py | 实测状态到规划到限力物理执行；落定、夹持、抬升、释放 |
| record_episode.py | 每步控制日志、真实状态快照、事件和时序说明 |
| evaluate.py | 独立检验抬升、承载间距、释放回落及持续性；展开额外检查覆盖率 |
| foundation.py | 匹配正/负对照及回放的失败关闭门槛 |
| batch.py | 门槛通过后有限重复参数试验；失败配置停止重复 |
| render_replay.py | 三路精确状态视频、完整动作片段、原生 Episode |
| render_pbr.py | 同轨迹 RTX 回放、逐帧 USD/物理对应验证 |
| encode_video.py | RGB 编码及解码帧数检查 |
| launch.py | 既有 Genesis 环境、限定缓存目录；物理 GPU 可选 |
| launch_replay.py / launch_pbr.py | 完整日志和输出验证，不单凭返回码判断成功 |
| publish.py | 不可变材料/候选/成功/失败证据注册、指纹检查及下载包 |
| tests/test_evidence.py | 错帧、动作对齐、完整子步、抓空误判、质量和接触垫覆盖测试 |
| runtime/scene.py | 冻结真实接触场景；分开布料、桌面、夹爪摩擦输入 |
| runtime/robot.py / safety.py | 复用完整机器人限力执行和硬检查 |
| runtime/prepare_assets.py / table_geometry.py | 平面参考网格、折角、初姿及桌面几何 |
| runtime/ipc_axis_compat.py / ipc_state_sync.py | 带源代码哈希检查的 IPC 轴及速度同步 |
| runtime/camera.py / evaluate.py | 状态副本相机和投影面积算法 |
| runtime/upstream_assets | 共享资产快照，原实验依赖不覆写 |
| config/asset_sources.json | 追加 curobo-cloth-v1 数据源，保留原来源 |
| assets/registry | 新增不可变 MAT / CFG / VAL，历史版本保持 |

之前是静态任务资产及独立历史实验；现在新轨迹具有统一控制/物理/视频证据，能被 Studio 原生合同读取。现有 REST 接口未改，新增数据通过注册表公开。

## 复现命令

在 5090 服务器使用现有环境执行，不安装或升级包。输出目录必须不存在，已发布运行不覆盖。

~~~bash
ROOT=/data/zhanghejun/robot-data-studio/expert_demos/curobo_cloth_v1
DATA=/data/zhanghejun/robot-data-studio/data/expert_demos/curobo-cloth-v1
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover -s "$ROOT/tests" -v
CLOTH_GPU=1 python3 -B "$ROOT/launch.py" runner.py --task corner_lift --pregrasp-start --output "$DATA/runs/NEW_NAME"
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B "$ROOT/evaluate.py" "$DATA/runs/NEW_NAME"
python3 -B "$ROOT/launch_replay.py" "$DATA/runs/NEW_NAME" --gpu 3
python3 -B "$ROOT/launch_pbr.py" "$DATA/runs/NEW_NAME" --gpu 3
~~~

不闭合对照添加 --negative-no-close；材料/初态用 --material 与 --initial。batch.py 用 --positive / --negative 指定已验证匹配对照，再指定任务、材料、初态及最多 3 次重复。GPU7 留给已有工作。

发布使用 backend/.venv/bin/python -B publish.py --catalog 或 --run RUN_PATH。已发布 artifact 不可改写。单次成功不代表泛化；独立进程重复也不等于统计独立随机试验。
