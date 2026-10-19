# RoboData Studio

[English](README.md) | [简体中文](README.zh-CN.md)

本地优先、支持多引擎的仿真数据采集平台。Genesis/ClothTwin、Isaac Sim/Isaac Lab
和 RoboVerse 在独立 worker 中运行。Studio 管理会话、worker 生命周期、统一 Episode
契约和索引；各引擎保留原生仿真、渲染与安全实现。版本化 schema 及轻量数据写入器、
校验器位于 `packages/robot-data-contracts`，worker 依赖该包，不导入 Studio。

从哪里开始：参见 [`docs/START_HERE.md`](docs/START_HERE.md)，了解仓库结构、不同任务的入口和证据等级。

## 能力与环境要求

| 范围 | 仓库提供 | 额外条件 |
| --- | --- | --- |
| 数据采集 | 会话、独立 worker、键盘／GELLO 入口 | 兼容引擎环境、worker 仓库和场景资产 |
| 数据审核 | Episode 索引与人工 QA | 已录制的原始 Episode |
| 导出与训练接入 | LeRobot／OpenPI 数据视图及消费端检查 | 对应导出器、模型和训练环境 |
| 双 FR3 部署 | 固定版本代码与资产准备 | 单独安装 Isaac SDK／环境并上机验证 |

后端需要 **Python 3.12+**，前端需要 **Node.js 22.13+**。Studio 环境运行界面和 API；
仿真器、导出器及策略可分别使用独立环境。全新 clone 不包含已采集 Episode、
模型权重、仿真 SDK 或已下载的资产库。

- [仓库导航](docs/START_HERE.md)
- [数据到训练流程](docs/DATA_TO_TRAINING_GUIDE_ZH.md)
- [双 FR3／GELLO 部署](docs/franka5090_deployment.md)

### 安装界面与 API 依赖

以下是安装说明，不会自动配置仿真器。在仓库根目录中使用新建或明确选定的环境执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e './packages/robot-data-contracts' -e './backend[dev]'
npm ci
```

先检查 `.env.example`；没有本机配置时再复制为 `.env`，并填写所需引擎的工作区路径。
下方启动命令通过 shell 加载配置，示例中的 `${...}` 变量依赖 shell 展开。
启动界面／API 不会安装或启动仿真 worker。

## 本地启动

后端（终端 1）：

```bash
cd /absolute/path/to/robot-data-studio
test -f .env || cp .env.example .env
set -a
source .env
set +a
PYTHONPATH=packages/robot-data-contracts/src \
  backend/.venv/bin/python -m uvicorn robot_data_studio.main:app --app-dir backend/src --host 127.0.0.1 --port 8010 --reload
```

前端（终端 2）：

```bash
cd /absolute/path/to/robot-data-studio
npm run dev -- --host 127.0.0.1
```

打开 `http://127.0.0.1:3000`；API 文档位于 `http://127.0.0.1:8010/docs`。
通过 SSH／VS Code 远程使用时，按需转发 `3000`（前端）、`8010`（API）和
`8080`（默认 Collector）端口。保持本地端口一致即可沿用这些浏览器地址。

## 数据采集流程

1. 新建会话，选择引擎、场景、控制源和 Sensor Profile。
2. 确认适用的 GPU、Collector 端口、控制频率及可选场景参数。
3. 在会话页启动允许列表中的引擎 worker。Studio 同时只管理一个仿真 worker。
4. Genesis/Isaac 交互会话需要打开 Collector。GELLO 模式在 Collector 中连接 Web Serial；Studio 不代理控制数据包。
5. RoboVerse 无头会话等待脚本批次完成，不提供 Collector 端口。
6. 保存交互 Episode 或完成无头批次，然后扫描会话目录。
7. 将 QA 标记为 accepted/rejected。导出默认只使用 accepted Episode。

启动器构建 argv 数组，不拼接 shell 命令。Genesis 和 Isaac worker 从 `gello-remote`
启动。Genesis 使用独立解释器，加载 ClothTwin 场景并接收 `CUDA_VISIBLE_DEVICES`。
Isaac 使用 Isaac Lab 启动器、`--gpu-id` 和单设备 `CUDA_VISIBLE_DEVICES`：
RTX/Vulkan 使用选定物理 GPU，Isaac Lab/PhysX 使用屏蔽后的逻辑 `cuda:0`，
避免在其他 GPU 上创建上下文。旧版 ClothTwin manifest 和引擎无关的
`robot_data_episode` v1 均经过校验后入索引；QA 不改写原始 manifest。

### Isaac 双 Franka 工位与 ClothForge 衣物

v17 工位复用已有 USD 桌面、双 Franka、材质与灯光。在 **Isaac Sim** 中选择：

| 场景 ID | 内容 | 物理后端 |
| --- | --- | --- |
| `bimanual_tabletop_v17` | 工位与刚体物体 | PhysX |
| `bimanual_tabletop_v17_cloth` | 工位与已有矩形布料 USD | PhysX |
| `bimanual_tabletop_v17_clothforge` | 工位与可选 ClothForge 衣物 | PhysX 或 Newton |

1. 新建会话并选择 v17 场景。页面默认选择 **GELLO**、**PhysX** 和 **960×720** 相机。
   FR3 部署选择 `isaac_fr3_dual_wrist_v1`；其他部署选择
   `isaac_bimanual_tabletop_visual_v5`。需要键盘时手动选择 Keyboard。
2. ClothForge 场景选择已注册衣物及 `light`、`medium`、`heavy` 材料预设。
   页面加载对应预设值，可覆盖面密度、摩擦、拉伸、面积约束、弯曲、缩放、
   桌面旋转、X/Y 偏移和布料求解迭代数。
3. 使用 Newton 时，在 **Physics Backend** 中选择 Newton。衣物路线采用
   **MJWarp＋VBD 双向耦合**处理机器人与布料接触；其余 v17 变体目前要求 PhysX。
4. 选择 worker GPU，启动 worker 并打开 Collector。让键盘控制区域获得焦点，
   按 **Tab** 切换主力臂，使用 Collector 的移动、夹爪、录制和重置控制。
5. 保存并扫描 Episode，然后进入正常 QA 流程。

衣物参数在 worker 启动时生效。更新会话参数后重新启动，或新建会话，以应用修改。
衣物通过 Studio Asset Registry 选择；worker 加载对应 ClothForge 源网格和材料配置，
不改写原始资产。源目录由 `ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT` 配置，请填写自己的 ClothForge checkout 路径。此路线使用已有 Isaac Lab worker 环境；选择 Newton
时该环境需要已有 Newton 集成。仅安装后端 Python 环境不提供仿真运行能力。

PhysX 将 ClothForge 材料值转换到自身可变形材料模型；Newton 使用原生布料系数、
平面纸样静止度量及缝线信息。相同输入预设不代表两种求解器物理等价。
Episode 保留衣物、材料参数及物理配置，便于检查。

2026-10-10 的本机 Newton T 恤验证覆盖启动、桌面接触、双臂和夹爪控制、重置，
以及 167 帧录制，状态值均为有限数。12 次布料迭代时实测控制频率约 10–11 Hz，
该结果仅对应这次配置。稳定抓取提起和衣物任务成功尚未验证。本机证据位于
`data/verification/clothforge_newton_v17_20261010/verification_summary.json`，
这些验证产物不随全新仓库检出提供。

### RoboVerse ManiSkill 批量采集

RoboVerse worker 在独立无头批次中运行 PickCube、PushCube 或 StackCube。
每个会话按固定 20 Hz 生成 1–10 个 Episode，使用官方 ManiSkill Panda
`pd_joint_delta_pos` 示范。任务描述符选择示范 H5/JSON、原生任务、50 步时长、
actor 映射、任务状态 schema 和评估器。`episode_steps` 可缩短重放以验证失败路径；
`demo_offset` 选择另一段连续的成功示范。

每个 Episode 记录官方示范轨迹、ManiSkill 元数据中的原始 `episode_seed`、
两份源文件的哈希及任务评估指标。恢复完整示范状态保留原始随机初始条件，
不会把本地递增计数当作新任务种子。PickCube 诊断抓取、目标和静止失败；
PushCube 诊断目标和表面失败；StackCube 诊断抓取、对齐、释放和稳定性失败。

worker 接收 `CUDA_VISIBLE_DEVICES`，GPU 选择仍然生效，但该路线无 Collector
端口，不支持 GELLO 或键盘控制。进程结束后扫描会话，使用同样的 QA、
accepted-only 导出和消费端 smoke 流程。

按任务下载所需官方示范到配置的缓存目录；已有本机缓存不随 clone 提供。例如：

```bash
"${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m mani_skill.utils.download_demo PushCube-v1 \
  -o "${ROBOT_DATA_STUDIO_ROBOVERSE_DEMO_ROOT}"
"${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m mani_skill.utils.download_demo StackCube-v1 \
  -o "${ROBOT_DATA_STUDIO_ROBOVERSE_DEMO_ROOT}"
```

### PickCube state-BC 消费端

`consumers/roboverse_state_bc` 提供 RoboVerse 数据的小策略训练路线。
它仅加载 QA accepted 且具有完整 P2 种子溯源的 PickCube Episode，使用带校验和的
原生 Panda 状态、任务状态和动作数据，按 Episode 划分 15/5 训练与验证集，
保存 checkpoint、仅由训练集生成的归一化器、配置、划分 UUID/种子、Git 状态及训练报告。
不使用 rejected Episode，也不把同一 Episode 的帧拆到两个集合。
`roboverse_maniskill_native_v2_pre_action` 在每次动作前记录状态，提供准确的
`state[t] -> action[t]` 配对。加载器拒绝旧版仅动作后状态的数据；历史原始 Episode
及其 P2-B 0/20 评估保持不变。

学习策略从新的 `reset(seed)` 状态直接进入原生 `PickCube-v1` 评估，输入 Panda
qpos/qvel、方块姿态和目标位置，输出有界的 8 维 `pd_joint_delta_pos` 动作块。
策略不恢复示范状态或重放示范动作。同样 20 个留出种子运行零动作基线；
官方示范重放上限恢复录制初始状态，因此不作为分布匹配的策略基线。
命令和证据门槛见 [`consumers/roboverse_state_bc/README.md`](consumers/roboverse_state_bc/README.md)。

单 Episode 对齐诊断使用独立门槛：非饱和 teacher-forced 动作 MSE 不超过 `1e-6`，
且恢复训练初始状态后原生闭环成功 3/3。报告保留饱和、非饱和及总体 MSE。
该检查不能替代 20 个留出种子的能力评估。

## Worker 运行可靠性

Studio 通过持久化 supervisor 启动引擎。每次启动生成 run UUID，在 SQLite 中记录
supervisor/child PID、Linux boot ID、进程启动身份、就绪状态、心跳、退出状态、
日志路径和资源锁。Genesis/Isaac 的控制 TCP 端点开始监听后才就绪；RoboVerse
完成原生任务初始化后写入本次 run 的 ready marker。API 重启时核对这些持久记录，
不依赖内存中的 `subprocess.Popen` 对象。

受管 worker 原子锁定全局仿真名额、选定 GPU、适用的 Collector/signaling/media
端口及会话输出根目录。退出后释放锁，保留不可变运行记录。`failed` 表示受监督进程
报告启动或运行失败；`orphaned` 表示 PID 身份消失或不匹配，Studio 拒绝向该 PID 发信号。

Sensor Profile 描述相机角色和挂载。实体设备序列号与逐设备标定应保存在本机配置中。
缺少内参的配置仍标记为 `nominal_pending_intrinsics`；使用自己的设备并完成标定后，
才能声称匹配真机相机。本次文档整理未迁移已有 profile 文件。

每个 v1 Episode 记录原生与策略状态、操作者/请求/安全过滤/实际提交动作、
控制/仿真/采集时间戳、相机标定、场景/资产/种子溯源、软件版本与依赖，以及评估器
版本和指标。`franka_empty` 没有任务评估器，自动结果明确为 `unavailable`；
操作者标记的成功或失败独立保留。

## 验证

在装有对应测试依赖的环境中执行；使用已配置的引擎解释器前，在当前终端加载 `.env`。
这些命令是验证入口，不表示新机器上的所有引擎都已通过验证。

```bash
cd /absolute/path/to/robot-data-studio
PYTHONPATH=backend/src:packages/robot-data-contracts/src \
  backend/.venv/bin/python -m pytest -q backend/tests

PYTHONPATH=packages/robot-data-contracts/src \
  "${ROBOT_DATA_STUDIO_COLLECTOR_PYTHON}" \
  -m pytest -q packages/robot-data-contracts/tests

PYTHONPATH=. "${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m unittest discover -s consumers/roboverse_state_bc -t . -p 'test_*.py' -v

cd /absolute/path/to/robot-data-studio
npm run lint
npm run build
```


硬件/Genesis 运行取决于 `ROBOT_DATA_STUDIO_COLLECTOR_PYTHON` 选择的解释器。
Studio 后端环境不重复安装 Genesis 环境。

此前开发机的依赖快照（不代表新机器环境）：`genesis` 环境可运行采集，但没有 LeRobot 或 TensorFlow Datasets；
`softmimicgen` 有 Robomimic 所需的 `h5py`。导出与消费端解释器独立配置。
Studio 不隐式安装软件包。

导出界面区分当前 LeRobot v3 和 OpenPI 内置 LeRobot v2.1。v3 接受
`physical_joint8`、`fastwam_franka_joint8`；v2.1 要求 `openpi_franka_joint8`。
这些是导出时的显式视图，不覆盖原始 Episode。FastWAM 使用 8 维 proprio/action
和 32 步动作时域。OpenPI 存储绝对 7 关节目标及绝对夹爪闭合比例，消费端将七个
关节通道转换为增量，并将模型张量补齐至 32 维。

OpenPI v2.1、FastWAM v3 成功导出后自动启动消费端 smoke。导出和 smoke 状态独立：
smoke 解码实际图像、加载任务指令、经真实消费端加载器和处理器构建一批状态/动作，
将 JSON 报告写入 `<export>/consumer_smoke/`。导出完成但 smoke 失败，不视为训练就绪。

OpenPI smoke 还会加载配置的 checkpoint，在一个显式选定的 GPU 上执行真实 JAX
策略前向。`pi05_franka_joint8_lora` 集成计算数据集专属归一化参数，训练七关节增量
及绝对夹爪通道，并将输出转回 8 维绝对 Franka 关节目标。报告分别记录模型执行、
动作契约兼容和闭环验证。此前开发 smoke 使用 seed-0、16 Episode、
2,000 步的 Franka joint8 产物。它兼容 worker 安全层接口，但尚不能证明 Isaac
任务鲁棒性或泛化。

闭环验证是独立的双进程评估：OpenPI 环境提供自定义 checkpoint，Genesis 环境运行
`gello-remote` 的纯仿真 worker。worker 根据当前 base/wrist 图像与关节状态重新规划，
所有预测命令经过场景关节限位与变化速率安全层，并记录 EpisodeContract 轨迹及四路视频。
抓取闭合、随后释放、原生任务评估器和十帧目标稳定性全部通过后，Episode 才通过；
离线推理本身不会设置 `closed_loop_validated=true`。

固定 Isaac Sim 方块抬升采集、QA、OpenPI 导出、pilot-check 和短程过拟合流程，参见
[`docs/ISAAC_CUBE_OPENPI_PILOT.md`](docs/ISAAC_CUBE_OPENPI_PILOT.md)。
