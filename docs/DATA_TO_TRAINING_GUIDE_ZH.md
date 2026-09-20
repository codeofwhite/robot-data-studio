# RoboData Studio 中文操作手册：从数据采集到训练与闭环评测

本文面向在本机使用 RoboData Studio 的操作者，说明如何把 Genesis、Isaac Sim 或 RoboVerse 产生的数据，经过扫描、QA、导出和训练前检查，变成可供模型训练的数据，并沿当前仓库已经实现的入口完成训练、微调和原生环境闭环评测。

本文依据 2026-09-17 的当前代码编写。项目仍在迭代；执行 GPU 训练或仿真前，应再次确认工作树、环境、GPU、数据集和 checkpoint。

## 1. 先理解“完成”有哪几个层级

整个链路是：

```text
引擎原生观测、动作和图像
  → Canonical Episode v1
  → 格式与时序校验
  → SQLite 索引，QA=pending
  → 人工 accepted / rejected
  → accepted-only 导出
  → 真实 consumer loader / processor smoke
  → 训练或微调
  → 离线指标
  → 原生环境闭环 rollout
```

这些结果不能互相替代：

| 层级 | 能证明什么 | 不能证明什么 |
|---|---|---|
| Episode 保存成功 | 数据写入了完整目录 | 数据质量合格 |
| 扫描通过 | schema、数组、时间和图像数量通过基础校验 | 图像内容正确、任务成功 |
| QA accepted | 操作者认可这条 Episode 可进入候选训练集 | 导出格式一定兼容 |
| Export completed | 派生训练格式写出成功 | 下游真实 loader 一定可读 |
| Consumer smoke passed | 实际 loader、图像解码和 processor 能组成一个 batch | 模型已学会任务 |
| Train completed | 生成了 checkpoint，训练过程没有直接报错 | checkpoint 有闭环能力 |
| Offline evaluation passed | teacher-forced 或离线阶段指标通过 | 环境中的真实状态分布下会成功 |
| Native closed loop passed | 当前 checkpoint 在原生环境完成了任务 | 未测试场景或真实机器人也能泛化 |

项目的事实源是 Raw Canonical Episode。LeRobot、OpenPI LeRobot、RLDS 和 Robomimic 都是可重建的派生格式，不应反向覆盖 Raw Episode。

## 2. 当前仓库支持到什么程度

| 路径 | 数据生成 | 训练格式 | 仓库内训练入口 | 原生闭环入口 |
|---|---|---|---|---|
| Genesis / Isaac → OpenPI | 已实现 | OpenPI LeRobot v2.1 | 已实现，pi0.5 Franka joint8 LoRA | 已实现，Genesis/Isaac policy worker |
| RoboVerse PickCube → State BC | 已实现 | Canonical Episode + checksummed native payload | 已实现，小型 action-chunk MLP | 已实现，ManiSkill `PickCube-v1` |
| LeRobot v3 → FastWAM | 已实现 | LeRobot v3 | 本仓库未提供完整训练编排 | 本仓库未提供正式闭环评测 |
| RLDS | 已实现导出 | TFDS/RLDS | 本仓库未提供训练器 | 未接入 |
| Robomimic | 已实现导出 | HDF5 | 本仓库未提供训练器 | 未接入 |

因此，第一次完整走通项目时，优先选择以下任一条：

1. 视觉策略：Isaac/Genesis → OpenPI v2.1 → pi0.5 LoRA → 仿真闭环。
2. 状态策略：RoboVerse PickCube → state BC → ManiSkill 原生闭环。

## 3. 目录和环境边界

主要目录：

```text
/data/zhanghejun/robot-data-studio/
├── backend/                         # FastAPI、SQLite、扫描、导出、smoke
├── packages/robot-data-contracts/   # Canonical Episode schema/writer/validator
├── consumers/
│   ├── openpi_franka_joint8/        # OpenPI 数据、训练、评估和服务桥接
│   └── roboverse_state_bc/           # RoboVerse PickCube state-BC
├── data/
│   ├── studio.db                     # 控制面索引，不是原始数据本体
│   ├── datasets/<dataset>/raw/       # Raw Canonical Episodes
│   ├── datasets/<dataset>/exports/   # LeRobot/RLDS/Robomimic 派生格式
│   ├── training/                     # checkpoint、norm stats、训练报告
│   └── evaluations/                  # 闭环评测报告
└── docs/
```

不同阶段使用隔离环境：

| 阶段 | 默认解释器或环境 |
|---|---|
| Studio backend | `backend/.venv/bin/python` |
| Genesis/ClothTwin | `/home/zhanghejun/miniconda3/envs/genesis/bin/python` |
| Isaac Sim/Isaac Lab | `/data/zhanghejun/IsaacLab/isaaclab.sh` |
| RoboVerse/ManiSkill | `/data/zhanghejun/envs/roboverse-maniskill/bin/python` |
| OpenPI export/训练 | `/data/zhanghejun/openpi/.venv/bin/python` |
| FastWAM smoke | `/data/zhanghejun/envs/lerobot-fastwam/bin/python` |
| Robomimic export | `/home/zhanghejun/miniconda3/envs/softmimicgen/bin/python` |

Studio 不会隐式安装缺失依赖。导出失败时，应先确认对应格式配置了正确解释器，不要直接在 backend 环境里混装所有模拟器和训练框架。

## 4. 启动 Studio

### 4.1 首次配置

如果项目根目录还没有 `.env`：

```bash
cd /data/zhanghejun/robot-data-studio
cp .env.example .env
```

检查 `.env` 中以下路径是否仍然存在：

- Studio 数据库和数据根目录；
- ClothTwin、GELLO Remote、RoboVerse、Isaac Lab；
- Genesis、RoboVerse、OpenPI、FastWAM、Robomimic 解释器；
- OpenPI base/fine-tuned checkpoint；
- GPU 编号和 Isaac 端口。

不要把 `.env` 中的本机绝对路径直接复制到另一台机器后假设仍然有效。

### 4.2 启动后端

终端 1：

```bash
cd /data/zhanghejun/robot-data-studio
set -a
source .env
set +a
PYTHONPATH=packages/robot-data-contracts/src \
  backend/.venv/bin/python -m uvicorn robot_data_studio.main:app \
  --app-dir backend/src --host 127.0.0.1 --port 8010 --reload
```

健康检查：

```bash
curl http://127.0.0.1:8010/api/health
```

API 文档：`http://127.0.0.1:8010/docs`。

### 4.3 启动前端

终端 2：

```bash
cd /data/zhanghejun/robot-data-studio
npm run dev -- --host 127.0.0.1
```

浏览器打开 `http://127.0.0.1:3000`。

远程使用时，通常需要保持本地端口号不变并转发：

- `3000`：Studio 前端；
- `8010`：Studio API；
- `8080`：默认 Collector；
- Isaac 使用的 signaling/media 端口按 `.env` 配置处理。

## 5. 启动采集前检查

### 5.1 检查工作树

```bash
git -C /data/zhanghejun/robot-data-studio status --short --branch
git -C /data/zhanghejun/gello-remote status --short --branch
```

如果执行的是可复现实验，还应记录 ClothTwin、RoboVerse、OpenPI 等依赖仓库的 commit。不要为了“干净”而清理不属于当前任务的修改。

### 5.2 检查 GPU

```bash
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used \
  --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory \
  --format=csv,noheader
```

训练、policy server 和仿真可以使用不同 GPU。例如 OpenPI server 使用物理 GPU 7、Isaac 使用物理 GPU 6。具体编号必须以当时空闲情况为准，不能照抄示例。

### 5.3 预先确定实验合同

至少先写清：

- dataset 名称；
- simulator、scene、control source；
- FPS、seed、相机配置；
- 需要多少 accepted Episodes；
- train/validation/held-out 如何按 Episode 或 seed 划分；
- 成功判据和停止条件；
- 输出、checkpoint、报告目录；
- 哪些参数在本轮必须固定。

不要先批量采集，再事后决定哪些数据算成功。

## 6. 新建 Session 并产生 Raw Episode

在 Studio 中打开“新建采集会话”。填写：

1. `Dataset`：同一实验使用稳定、可识别的名字。
2. `Simulator`：Genesis、Isaac Sim 或 RoboVerse。
3. `Scene`：选择后端 descriptor 提供的场景。
4. `Control`：keyboard、GELLO 或 scripted；可选项由引擎决定。
5. `Target Episodes`：本 Session 计划采集的数量。
6. `GPU`：当前可用的物理 GPU 编号。
7. `Dataset FPS`：训练数据保存频率，不等于墙钟采集吞吐。
8. `Sensor Profile`：必须与实际相机/仿真相机配置一致。
9. 高级参数：scene 参数、桌面高度、任务阈值等。

创建 Session 后不会自动执行机器人动作。进入 Session 页面，再显式点击“启动 Worker”。

### 6.1 Genesis / Isaac 交互式采集

1. 等待 Worker 状态从 `starting` 变为 `running`。
2. 打开嵌入式 Collector，或在新标签页打开。
3. GELLO 模式下，在 Collector 中显式选择串口并连接。
4. 确认实时视图、dataset cameras、状态和控制数据持续刷新。
5. 执行一个完整任务过程。
6. 明确保存 Episode；失败样本如果需要分析也可保存，但后续应 Reject 或单独路由。
7. 达到计划数量后停止 Worker。

安全、joint limit、slew limit 和 watchdog 保留在引擎 worker；Studio 只负责编排和索引。

### 6.2 RoboVerse scripted batch

RoboVerse 当前支持 PickCube、PushCube、StackCube 的原生 ManiSkill demonstration replay：

1. 选择 RoboVerse 和对应场景。
2. 控制方式为 `scripted`。
3. 每个 Session 生成 1–10 条 Episode。
4. 启动 Worker 后等待批任务退出；RoboVerse 不提供 Collector 页面。
5. Worker 完成后点击“扫描 Episodes”。

PickCube demo 已在本机缓存。PushCube 或 StackCube 缺失时，先在明确批准的情况下下载对应官方 demo，不要把下载成功等同于采集成功。

## 7. Raw Canonical Episode 里有什么

典型目录：

```text
data/datasets/<dataset>/raw/<session_id>/episode_000000/
├── manifest.json
├── trajectory.npz
├── base_rgb/000000.jpg
├── wrist_rgb/000000.jpg
├── top_rgb/000000.jpg               # 视场景而定
├── side_rgb/000000.jpg              # 视场景而定
├── native_trajectory.npz            # 某些引擎附带
└── native_payload.sha256            # 某些引擎附带
```

写入过程先使用 `episode_XXXXXX.tmp`，完成后再重命名，扫描器不会把正常的临时目录当成完整 Episode。

`manifest.json` 记录：

- task、robot、control source、FPS、帧数；
- feature 的 key、role、dtype、shape、names、units；
- action profile；
- 相机名、内参和外参；
- scene、seed、resolved parameters、assets；
- simulator、worker、Git revisions、dependency versions；
- evaluator、operator outcome、failure reason；
- generation method、parent Episode、随机化 lineage。

Franka Canonical Episode 的核心数组：

| 数组 | 形状 | 含义 |
|---|---:|---|
| `native_state` | 18D | 7 关节位置、2 手指位置和相应速度 |
| `policy_state` | 16D | 7 关节、总夹爪宽度、7 关节速度、夹爪速度 |
| `operator_action` | 来源相关 | GELLO、键盘或上游 demo 原始动作 |
| `requested_action` | 8D | 请求的 7 关节绝对目标 + 总夹爪宽度 |
| `safe_action` | 8D | 安全过滤后的目标 |
| `applied_action` | 8D | 实际提交给环境的动作，默认训练目标 |

同一帧的时序语义是：先捕获 `observation_t`，再提交 `applied_action_t`。训练或新增 consumer 时必须保持这一约定，不能无说明地把 state 和 action 错位一帧。

## 8. 扫描和 QA

### 8.1 扫描

在 Session 页面点击“扫描 Episodes”。扫描器会检查：

- manifest/schema 是否有效；
- 必需数组是否存在；
- 数组是否等长、有限；
- `frame_index` 是否连续；
- `episode_time_s == frame_index / fps`；
- simulation/capture timestamp 是否单调；
- 每个相机的 JPEG 数量是否和帧数一致。

通过后 Episode 被写入 SQLite 索引，初始 `qa_status=pending`。QA 不会重写 Raw `manifest.json`。

### 8.2 人工 QA

进入 Episodes 页面，过滤当前 dataset、simulator 和 `pending`。逐条检查：

1. 所有相机都有图像，画面不是重复、冻结、全黑或错相机。
2. 机器人、目标物和关键抓取/接触阶段可见。
3. 动作序列与任务阶段一致，例如 open → close → transport → release。
4. `Operator` 和自动 evaluator 结果是否一致；不一致时先诊断。
5. task、scene、seed、control source、engine version 正确。
6. 没有碰撞、穿透、误抓、滑落、提前结束或 watchdog 异常。
7. 没有重复 UUID、重复 seed 或重复 source trajectory 混入计划外数据。

处理方式：

- 合格：`Accept & next`。
- 不合格：填写可搜索的原因后 `Reject`，如 `grasp_slip`、`stale_camera`、`collision`、`wrong_gripper_phase`。
- 需要修复但不能可靠修复：保留 Raw 数据并 Reject，不要手动改 NPZ 冒充原始采集。

只有 `accepted` Episode 会出现在标准导出候选集中。

## 9. 导出训练数据

打开“导出中心”：

1. 选择 Dataset。
2. 用 Simulator 过滤，避免无意混合不同域。
3. 明确勾选本次导出的 Episode。
4. 选择格式和 training profile。
5. 填写新的输出名称。
6. 先点击“兼容性预检”。
7. 检查 robot、FPS、action profile、相机、可选观测和 warnings。
8. 预检通过后再提交导出。

推荐命名：

```text
<profile>_<scene>_<seed-or-split>_<episode-count>_<date>
```

例如：

```text
openpi_isaac_cube_lift_seed0_train20_20260917
fastwam_roboverse_stackcube_train3_20260917
```

如果输出已存在，导出器会拒绝覆盖。不要随意删除旧输出；使用新名字保留实验谱系。

### 9.1 格式选择

| 目标 | 格式 | Profile | 备注 |
|---|---|---|---|
| 通用 LeRobot / 物理 Franka | LeRobot v3 | `physical_joint8` | 16D state、8D absolute action |
| FastWAM | LeRobot v3 | `fastwam_franka_joint8` | 8D proprio/action，32-step horizon |
| OpenPI pi0.5 | OpenPI LeRobot v2.1 | `openpi_franka_joint8` | 要求 base+wrist；夹爪转换为 closed fraction |
| TensorFlow/RLDS consumer | RLDS | 固定 physical view | 当前没有自动 consumer smoke |
| Robomimic | Robomimic HDF5 | 固定 Robomimic view | 同时保存归一化和 absolute action |

“保存图片而不是 MP4”主要用于调试或兼容特定 loader。正常视频训练优先保留 MP4，除非目标 consumer 明确要求逐帧图片。

### 9.2 导出预检实际检查什么

被选 Episode 必须：

- 属于同一 Dataset；
- QA accepted；
- 不重复；
- Session 未进入 trash；
- Raw 路径仍在 Dataset 的 `raw/` 内；
- robot、FPS、action profile、相机顺序一致；
- `ee_pose`、`object_pose` 等可选观测存在性一致。

OpenPI 还要求 `base` 和 `wrist`。其他相机可以保留为 QA/provenance 相机，但当前 Franka OpenPI consumer 只消费 base+wrist。

### 9.3 Consumer smoke

OpenPI v2.1 和 FastWAM v3 导出成功后会自动启动 smoke。检查导出页面中的两个独立状态：

- Export：`completed`；
- Consumer smoke：`passed`。

报告位于：

```text
<export>/consumer_smoke/openpi.json
<export>/consumer_smoke/fastwam.json
```

Smoke 会真实解码图像、读取 task、加载数据集、组成 batch 并经过实际 processor。OpenPI smoke 还可以加载配置的 checkpoint 做一次 forward，但报告中的 `closed_loop_validated` 在离线阶段必须仍为 `false`。

## 10. 训练前强制门槛

在启动训练前确认：

- [ ] 训练 Episode 全部是 QA accepted。
- [ ] Episode 列表、UUID、seed 和 split 已保存。
- [ ] 没有按 frame 随机拆分同一 Episode 到 train/validation。
- [ ] 导出 preflight 通过。
- [ ] 对应 consumer smoke 通过。
- [ ] 图像能够真实解码，state/action finite。
- [ ] 动作的单位、绝对/增量语义、夹爪语义明确。
- [ ] 训练目录是新的，或明确使用受支持的 resume。
- [ ] base checkpoint 与模型配置匹配。
- [ ] GPU 空闲且有足够显存。
- [ ] 预先写好离线门槛和闭环门槛。

如果这些条件没有满足，不要通过加 try/except、跳过校验或改写原始数据强行开始训练。

## 11. 路径 A：OpenPI Franka joint8 微调

详细的 Isaac cube-lift 固定实验还可参考 [ISAAC_CUBE_OPENPI_PILOT.md](ISAAC_CUBE_OPENPI_PILOT.md)。下面给出通用操作模板。

### 11.1 定义本轮路径

以下命令不会自动选择正确数据，请替换所有路径和名称：

```bash
cd /data/zhanghejun/robot-data-studio

OPENPI_EXPORT=/absolute/path/to/openpi_v21_export
OPENPI_TRAINING=/data/zhanghejun/robot-data-studio/data/training/<run_name>
PI05_BASE=/home/zhanghejun/.cache/openpi/openpi-assets/checkpoints/pi05_libero
OPENPI_PYTHON=/data/zhanghejun/openpi/.venv/bin/python
OPENPI_PYTHONPATH=/data/zhanghejun/robot-data-studio:/data/zhanghejun/openpi/src:/data/zhanghejun/openpi/packages/openpi-client/src
OPENPI_GPU=7
EXPECTED_EPISODES=20
EXPERIMENT_NAME=<scene>_seed0_overfit20_step500
```

不要使用宽泛的 `HOME`、裸 `python` 或裸 `pip` 替代这些明确路径。

### 11.2 Dataset pilot check

```bash
PYTHONPATH="$OPENPI_PYTHONPATH" "$OPENPI_PYTHON" \
  -m consumers.openpi_franka_joint8.pilot_check \
  --dataset-root "$OPENPI_EXPORT" \
  --expected-episodes "$EXPECTED_EPISODES" \
  --report "$OPENPI_TRAINING/reports/pilot_check.json"
```

只有报告 `status: passed` 才继续。重点查看：

- LeRobot 是否为 v2.1；
- Episode 数和 frame 数；
- base/wrist 是否存在；
- state/action shape 和 finite；
- provenance；
- open/close/release 阶段是否合理。

### 11.3 计算 norm stats

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.run stats \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --report "$OPENPI_TRAINING/reports/norm_stats.json"
```

确认 state/action 的 mean、std、q01、q99 均有限。近似常量的关键动作通道通常意味着数据分布或动作记录有问题。

### 11.4 真实训练 batch preflight

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.run preflight \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --report "$OPENPI_TRAINING/reports/preflight.json"
```

当前模型 contract 期望：

- batch 后 state 为 32D padded tensor；
- action 为 `[batch, action_horizon, model_action_dim]`；
- 图像、mask 和 tokenized prompt 均存在。

### 11.5 先做短训练 smoke

建议先用独立 experiment name 跑 10 step，确认 checkpoint 和指标能正常产生：

```bash
SMOKE_EXPERIMENT=<scene>_seed0_step10_smoke

CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.run train \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --experiment-name "$SMOKE_EXPERIMENT" \
  --num-train-steps 10 \
  --report "$OPENPI_TRAINING/reports/train_step10_smoke.json"
```

这只证明训练入口、数据和 checkpoint 写入正常，不证明收敛。

### 11.6 固定数据过拟合或正式微调

第一阶段建议固定 seed、scene、camera、prompt 和数据集，跑 500 step：

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.run train \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --experiment-name "$EXPERIMENT_NAME" \
  --num-train-steps 500 \
  --report "$OPENPI_TRAINING/reports/train_step500.json"
```

如需阶段平衡采样，显式增加：

```text
--sampling-strategy phase_balanced
```

它只改变采样概率，不修改 OpenPI 模型损失。不要同时改变数据、horizon、采样、场景和随机化，否则无法判断收益来源。

只有在 loss 有限且下降、数据/夹爪阶段门槛没有暴露基础错误时，才考虑独立运行 2,000-step 实验。推荐使用新 experiment name 保留 500-step 证据，而不是覆盖旧目录。

### 11.7 离线阶段评估

假设 500-step checkpoint 为：

```bash
OPENPI_CHECKPOINT="$OPENPI_TRAINING/checkpoints/pi05_franka_joint8_lora/$EXPERIMENT_NAME/499"
```

运行阶段指标：

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.evaluate_val \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --checkpoint "$OPENPI_CHECKPOINT" \
  --experiment-name "$EXPERIMENT_NAME" \
  --num-train-steps 500 \
  --report "$OPENPI_TRAINING/reports/offline_phase_step499.json"
```

关注 joint MAE、approach-open specificity、close recall、transport/grasp/lift close recall、release 阶段和 chunk 时间偏移。总体 MSE 很低但夹爪时序错误时，不能晋级闭环。

也可以执行单样本 checkpoint inference：

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.run infer \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --checkpoint "$OPENPI_CHECKPOINT" \
  --experiment-name "$EXPERIMENT_NAME" \
  --num-train-steps 500 \
  --report "$OPENPI_TRAINING/reports/checkpoint_inference.json"
```

Inference 通过仍然不是闭环成功。

### 11.8 启动 OpenPI policy server

终端 A，选择空闲 GPU：

```bash
CUDA_VISIBLE_DEVICES="$OPENPI_GPU" \
PYTHONPATH="$OPENPI_PYTHONPATH" \
"$OPENPI_PYTHON" -m consumers.openpi_franka_joint8.serve \
  --dataset-root "$OPENPI_EXPORT" \
  --training-root "$OPENPI_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --checkpoint "$OPENPI_CHECKPOINT" \
  --experiment-name "$EXPERIMENT_NAME" \
  --host 127.0.0.1 \
  --port 8000
```

服务输出动作 contract 为：7 个绝对关节目标 + gripper closed fraction。仿真 worker 负责转换为物理 Franka joint8，并继续执行 joint-limit 和 slew-rate safety。

### 11.9 Isaac 原生闭环 rollout

终端 B。下面示例使用另一个空闲 GPU，并创建全新的输出目录：

```bash
ISAAC_GPU=6
ROLLOUT_ROOT=/data/zhanghejun/robot-data-studio/data/evaluations/<new_isaac_rollout_name>

env CONDA_PREFIX=/home/zhanghejun/miniconda3/envs/isaaclab \
  PYTHONPATH=/data/zhanghejun/gello-remote/src:/data/zhanghejun/openpi/packages/openpi-client/src:/data/zhanghejun/robot-data-studio/packages/robot-data-contracts/src \
  /data/zhanghejun/IsaacLab/isaaclab.sh -p -m gello_remote.isaaclab_gello \
  --control-source openpi \
  --scene rigid_cube_lift \
  --gpu-id "$ISAAC_GPU" \
  --enable_cameras \
  --rollout-count 20 \
  --max-episode-frames 400 \
  --policy-host 127.0.0.1 \
  --policy-port 8000 \
  --policy-checkpoint "$OPENPI_CHECKPOINT" \
  --data-dir "$ROLLOUT_ROOT"
```

正式 held-out 评测应增加经过泄漏检查的：

```text
--evaluation-plan /absolute/path/to/heldout_plan.json
```

先用 `--evaluation-limit 1` 做有界 runtime smoke，但 smoke 目录不要和正式 paired batch 混用。Isaac worker 会拒绝覆盖已有 `batch_report.json`，因此每次正式评测使用新目录。

检查输出：

```text
<rollout_root>/episode_XXXXXX/
<rollout_root>/rollouts.csv
<rollout_root>/batch_report.json
```

报告 grasp、lift、hold、release 和最终成功率；不要只报告平均 loss。

### 11.10 Genesis 原生闭环 rollout

Genesis 使用 `gello_remote.genesis_policy_rollout`，同样连接上面的 WebSocket server。先查看当前 checkout 参数：

```bash
PYTHONPATH=/data/zhanghejun/gello-remote/src:/data/zhanghejun/ClothTwin \
  /home/zhanghejun/miniconda3/envs/genesis/bin/python \
  -m gello_remote.genesis_policy_rollout --help
```

典型调用需要至少明确：

```text
--scene <scene>
--output-dir <new_output_dir>
--policy-host 127.0.0.1
--policy-port 8000
--policy-checkpoint <checkpoint>
--max-steps <bounded_steps>
--seed <seed>
```

Genesis rollout 同样会记录 requested/safe/applied action、推理时延、相机、原生 evaluator 和视频。以输出 Episode 和 evaluator 为准，不要只看 policy server 是否返回了动作。

## 12. 路径 B：RoboVerse PickCube State-BC

这条路径不使用视觉 OpenPI。它从 Canonical Episode 及其 checksummed ManiSkill native payload 读取 28D state，训练输出 8-step × 8D `pd_joint_delta_pos` action chunk 的小型 MLP。

详细说明见 [RoboVerse State-BC README](../consumers/roboverse_state_bc/README.md)。

### 12.1 数据要求

- 只读取 Studio 中 QA accepted 的 PickCube Episode；
- native evaluator 必须成功；
- 必须有完整 `maniskill_source_episode_seed` provenance；
- native payload 必须是 pre-action schema；
- 使用精确的 `state[t] → action[t]` 对；
- train/validation 在 Episode 层拆分；
- normalizer 只拟合 train Episodes。

历史 post-action-only Episode 会被新 loader 拒绝，不能通过人为移位后无说明地复用。

### 12.2 先运行 consumer 测试

```bash
cd /data/zhanghejun/robot-data-studio
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m unittest discover -s consumers/roboverse_state_bc -t . -p 'test_*.py' -v
```

### 12.3 单 Episode 过拟合门

先采集并 QA accept 一条 v2 PickCube Episode，再运行：

```bash
cd /data/zhanghejun/robot-data-studio
CUDA_VISIBLE_DEVICES=7 \
MPLCONFIGDIR=/tmp/robot-data-studio-mpl \
XDG_CACHE_HOME=/tmp/robot-data-studio-cache \
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.overfit_one \
  --dataset-name roboverse_p2b1_pickcube_overfit \
  --sim-backend physx_cuda \
  --rollouts 3
```

晋级门槛：

- non-saturated teacher-forced action MSE ≤ `1e-6`；
- 恢复同一训练初始状态的 3/3 原生闭环成功。

这只证明 state/action/control 对齐，不证明 held-out 泛化。

### 12.4 训练 20-Episode 数据集

所有源 Episode QA accepted 后：

```bash
cd /data/zhanghejun/robot-data-studio
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.train \
  --dataset-name roboverse_p2b1_pickcube_v2 \
  --run-name pickcube_bc_v2
```

输出：

```text
data/training/roboverse_state_bc/pickcube_bc_v2/
├── checkpoint.pt
├── normalizer.npz
├── config.json
├── split.json
└── train_report.json
```

训练器拒绝复用非空 run directory。需要重新训练时使用新 run name，不要删除旧证据后覆盖。

### 12.5 ManiSkill 原生闭环评测

```bash
cd /data/zhanghejun/robot-data-studio
MPLCONFIGDIR=/tmp/robot-data-studio-mpl \
XDG_CACHE_HOME=/tmp/robot-data-studio-cache \
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.evaluate_maniskill \
  --checkpoint data/training/roboverse_state_bc/pickcube_bc_v2/checkpoint.pt \
  --sim-backend physx_cuda \
  --output data/evaluations/roboverse_state_bc/pickcube_bc_v2.json
```

正式 capability gate：

- 20 个 held-out seed 中至少 10 个 policy success；
- policy success 多于同 seed 的 zero-action；
- one-sided exact paired p-value < 0.05。

未通过时，只能表述为“训练和闭环管线已完成”，不能表述为“策略学会 PickCube”。Official-demo replay 会恢复 recorded initial state，因此只是 ceiling，不是分布匹配的 policy baseline。

## 13. FastWAM、RLDS 和 Robomimic 怎么使用

### 13.1 FastWAM

选择：

```text
Format: LeRobot v3
Profile: fastwam_franka_joint8
```

导出完成后自动运行 FastWAM consumer smoke，检查：

- LeRobot v3 metadata；
- 8D proprio；
- 32 × 8 action horizon；
- 图像时间窗口；
- processor 输出视频 tensor。

当前仓库没有 FastWAM 完整训练命令和原生闭环 worker。因此 `fastwam smoke passed` 只能证明训练数据接口兼容。真正训练前需要另行固定 FastWAM checkpoint、训练配置、split 和闭环 consumer。

### 13.2 RLDS

RLDS 导出生成 TFDS episode/step 结构，包含：

- 16D physical state；
- 8D action；
- RGB images；
- reward、discount、first/last/terminal；
- language instruction；
- engine、scene、seed、evaluator metadata。

当前没有自动 loader smoke 或训练脚本。导出 `completed` 后仍应使用目标 TensorFlow consumer 做真实 decode/batch 测试。

### 13.3 Robomimic

Robomimic 导出为一个 HDF5：

```text
data/demo_i/states
data/demo_i/actions
data/demo_i/actions_absolute
data/demo_i/rewards
data/demo_i/dones
data/demo_i/obs/*
data/demo_i/next_obs/*
mask/train|valid|test
```

`actions` 是按 Franka joint limits 归一化的动作，`actions_absolute` 保留物理绝对目标。当前没有自动 Robomimic 训练和闭环入口，必须在目标 Robomimic 环境中补做 loader、训练和 native evaluation。

## 14. 建议保存的实验产物

每次训练至少保存：

- 精确 Episode UUID、session、seed 和 QA 状态；
- export job ID、format、profile 和输出路径；
- `robot_data_provenance.jsonl`；
- train/validation/held-out split；
- norm stats；
- 完整配置和命令；
- Git commit/dirty state；
- Python、CUDA、依赖版本；
- 训练指标和 checkpoint；
- 离线评估报告；
- 原生闭环的逐 Episode 结果、失败类别和视频。

推荐目录：

```text
data/training/<run_name>/
├── assets/                   # norm stats 等
├── checkpoints/
├── reports/
│   ├── pilot_check.json
│   ├── preflight.json
│   ├── train.json
│   ├── offline_eval.json
│   └── checkpoint_inference.json
└── experiment_contract.md    # 可选但推荐

data/evaluations/<run_name>/
├── episode_*/
├── videos/
├── rollouts.csv
└── batch_report.json
```

## 15. 常见故障

### 15.1 Worker 显示 failed 或 orphaned

1. 在 Session 页面查看 worker log path。
2. 确认 child PID、heartbeat、GPU 和端口。
3. `orphaned` 表示持久化 PID identity 不再匹配；不要盲目 kill 该 PID。
4. 先确认进程和资源，再创建新 Session 或重新启动。

### 15.2 扫描显示 invalid

常见原因：

- `manifest.json` 不符合 schema；
- `trajectory.npz` 缺数组或长度不同；
- NaN/Inf；
- frame index 不连续；
- 时间戳倒退；
- JPEG 数量不等于 num_frames。

不要直接把 invalid Episode 改成 accepted。应定位 worker 写入问题，并用新 Episode 验证修复。

### 15.3 导出 preflight 失败

常见原因：

- 混合了不同 FPS、robot、action profile 或相机集合；
- OpenPI 缺少 base/wrist；
- optional observation 不一致；
- Episode 不属于当前 Dataset；
- Episode 未 accepted；
- Raw 目录已经移动或回收。

优先缩小到一个同源 Episode 做 preflight，再逐步增加，不要放松校验。

### 15.4 Export completed，但 smoke failed

检查：

- `<export>/consumer_smoke/*.json`；
- export/smoke log；
- 目标解释器是否包含正确 LeRobot、PyAV、Pillow 或训练框架版本；
- 导出 codebase version；
- 图像 codec 是否能解码；
- state/action/camera key 是否匹配 consumer。

不要因为目录已经生成就把它交给训练。

### 15.5 OpenPI 报 LeRobot 版本错误

OpenPI 使用 vendored LeRobot v2.1，不能直接把普通 LeRobot v3 目录当作输入。重新选择：

```text
OpenPI LeRobot v2.1 + openpi_franka_joint8
```

### 15.6 训练 loss 下降但夹爪不工作

分别检查：

- approach 阶段是否保持 open；
- close transition 是否及时；
- grasp/lift 期间是否保持 closed；
- release 是否发生；
- closed-fraction 和 width 的转换是否一致；
- action chunk 的第一步和事件偏移；
- 数据里静止 hold frame 是否占比过大。

低 arm MAE 或有限 loss 不能替代夹爪事件门槛。

### 15.7 离线通过、闭环失败

优先诊断：

- covariate shift；
- 初始状态和训练数据不匹配；
- 视觉延迟或图像错配；
- action chunk 执行/重规划频率；
- joint/gripper action 语义；
- safety filter 是否大幅改写 requested action；
- task evaluator 是否过严或过松。

保留失败 rollout，并比较 requested/safe/applied action，而不是立即增加训练步数。

## 16. 从 Studio 运行首个布料任务

首个已接通任务是 `CFG-textile_feeding__light`（送料工位 · 轻薄布料）的 Genesis 笛卡尔双夹爪筛查：

1. 打开“资产与材料 → 资产索引”，进入该配置。
2. 点击“发布新版本”，只修改需要试验的参数并填写变更说明；保存后旧版本和旧验证均保留。
3. 在新版本详情点击“启动运行”。页面展示运行编号、进度、日志和失败原因。
4. 运行结束后，Studio 自动登记与该配置精确版本关联的验证记录，并返回验证概览。
5. 在概览中展开这一配置，可查看单次判定和轨迹回放；即使仿真进程失败，日志也会作为 `unavailable` 证据保留。

运行产物位于 `data/cloth_runs/<run-id>/`，包括配置快照、`trajectory.npz`、评价、最终帧、视频和日志。`trajectory.npz` 记录布料顶点、夹爪实际/目标位置、施加力、反力估计、操作阶段和时间戳。

> 边界：这是笛卡尔双夹爪场景筛查，不验证 Franka 机械臂可达性，也不会自动进入训练导出。只有后续完成机器人动作语义映射、Canonical Episode 转换和 QA 后，才能把它称为可训练机器人数据。

## 17. Isaac Renderer Profile

新建 Isaac Sim 会话时可以选择版本化 Renderer Profile：

- `isaac_performance_v1`：优先交互帧率，适合控制链路调试。
- `isaac_balanced_v1`：兼顾画质与交互，也是旧 API 的兼容默认值。
- `isaac_quality_v1`：使用 Isaac Lab 的 `quality` 模式，但不会自动改善场景模型、纹理或灯光。

Studio 会同时把 profile 文件和对应的 `rendering_mode` 传给 worker。两者不一致时拒绝启动，避免界面选择与实际渲染不一致。Episode 的 scene parameters 保存完整 renderer profile、profile version、源文件路径和 SHA-256，因此后续可以判断一帧图像采用了哪个精确配置。

当前只允许 `performance / balanced / quality`。Path Tracing 属于后续离线重渲染流程，不能填写到 `rendering_mode`。Renderer Profile 只描述视觉渲染配置，不改变碰撞、质量、摩擦或其他物理参数。

## 18. 最小完整验收清单

第一次跑通一条新任务时，按顺序完成：

- [ ] 1 条 Episode 保存并扫描通过。
- [ ] 人工回放图像、状态、动作和 evaluator。
- [ ] 3 条 Episode 验证重复采集稳定性。
- [ ] 全部合格样本 QA accepted。
- [ ] 训练/验证按 Episode 或 seed 分割。
- [ ] accepted-only export preflight 通过。
- [ ] 真实 consumer smoke 通过。
- [ ] 单 Episode 或小数据过拟合门通过。
- [ ] 多 Episode 训练生成可加载 checkpoint。
- [ ] 离线阶段指标通过预注册门槛。
- [ ] 原生环境运行有界 smoke。
- [ ] 正式 held-out 闭环评测。
- [ ] 报告成功率、阶段指标、安全过滤、失败分类和视频。

只有最后几项通过后，才可以宣称策略在该任务和评测分布上具有闭环能力。

## 19. 相关源码和专项文档

- 项目概览：[README.md](../README.md)
- Isaac/OpenPI 固定 pilot：[ISAAC_CUBE_OPENPI_PILOT.md](ISAAC_CUBE_OPENPI_PILOT.md)
- Canonical manifest：[episode.py](../packages/robot-data-contracts/src/robot_data_contracts/episode.py)
- Episode writer：[writer.py](../packages/robot-data-contracts/src/robot_data_contracts/writer.py)
- Episode validator：[validation.py](../packages/robot-data-contracts/src/robot_data_contracts/validation.py)
- Export service：[export_service.py](../backend/src/robot_data_studio/services/export_service.py)
- OpenPI bridge：[run.py](../consumers/openpi_franka_joint8/run.py)
- OpenPI policy server：[serve.py](../consumers/openpi_franka_joint8/serve.py)
- RoboVerse State-BC：[README.md](../consumers/roboverse_state_bc/README.md)
