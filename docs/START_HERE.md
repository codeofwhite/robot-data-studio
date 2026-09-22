# START HERE — 仓库导航

> **证据分级**：结构测试 < 数据被接受 < consumer smoke < 离线拟合 < 训练 < native 评测 < 闭环 < 真机。
> 当前最高到 **native 评测 + consumer smoke**。没有闭环、没有真机。
> `physics_passed`（布料校验）与 `qa_accepted`（QA 接受）都**不等于**任务成功。

## 这仓库是什么

**Robot Data Studio** = 引擎无关的仿真数据采集平台。Studio 管 session、worker 生命周期、统一 `robot_data_episode` v1 契约与索引；Genesis·ClothTwin、Isaac Sim·IsaacLab、RoboVerse 各跑在隔离 worker 里。worker 只依赖 `packages/robot-data-contracts`，永不 import Studio。

证据链：**采集 → QA 索引 → consumer 导出（LeRobot-v3 / OpenPI）→ 训练 → native 评测**。

Canonical `robot_data_episode` v1 是不可变源数据；QA 接受的 consumer 导出是可重建衍生物。raw manifest 不被 QA 改写。

## 五扇门（按你想干什么进）

| 你的状态 | 进这里 | 第一步 |
|---|---|---|
| 想看有哪些成功案例 | [`data/RUN_INDEX.md`](../data/RUN_INDEX.md) | `ls data/views/physics_passed` |
| 想跑一次采集 | [`README.md`](../README.md) | 起 backend :8010 + 前端 :3000 |
| 想从数据训到评测 | [`docs/DATA_TO_TRAINING_GUIDE_ZH.md`](DATA_TO_TRAINING_GUIDE_ZH.md) | 35KB 全链路手册，**最该先读的一份** |
| 想改代码 / 加引擎 | `backend/src/robot_data_studio/adapters/` + `packages/robot-data-contracts/` | 先看契约再看 adapter |
| 想接着做布料 / expert | [`CLOTHFORGE_STATUS.md`](CLOTHFORGE_STATUS.md) · [`CUROBO_EXPERT_DEMOS.md`](CUROBO_EXPERT_DEMOS.md) | |

## 顶层目录

### 权威代码（别动结构）

| 目录 | 职责 |
|---|---|
| `backend/` | FastAPI：8 个 routes（sessions / episodes / exports / datasets / cloth / assets / consumer_smokes / health）+ 14 个 services + 3 个引擎 adapter |
| `packages/robot-data-contracts/` | 版本化数据契约 |
| `packages/gello-control/` | GELLO 遥操作 |
| `app/` `components/` `hooks/` `lib/` | vinext/React 前端（sessions / episodes / exports / cloth / assets 五页） |
| `consumers/` | 下游适配：`openpi_franka_joint8`、`roboverse_state_bc` |
| `expert_demos/` | ⚠️ **代码**（cuRobo 生成器），不是数据 —— 数据在 `data/expert_demos/` |
| `config/` | `camera_profiles` / `renderer_profiles` |

### 可忽略（构建产物 / 运行时）

`dist/` · `.next/` · `.vinext/` · `.wrangler/` · `node_modules/` · `tsconfig.tsbuildinfo` · `assets/`（服务端写入的注册表数据）

### 工具

`scripts/index_data_runs.py` —— 只读重建 `data/RUN_INDEX.*` 与 `data/views/`（`--dry-run` 先看计数）。

## `data/` —— 三块，别混着看

### A. 管线数据（有权威索引 → [`data/RUN_INDEX.md`](../data/RUN_INDEX.md)）

| 目录 | 体量 | 是什么 |
|---|---|---|
| `studio.db` | 3.8M | SQLite 权威索引：episodes / sessions / exports / smokes |
| `cloth_runs/` | 1.3G | 布料仿真校验 run（含 `state.json` + `output/validation.json`） |
| `datasets/` | 3.2G | consumer 导出数据集 |
| `training/` | 104G | 训练输出（含 ckpt） |
| `evaluations/` | 231M | native 评测 |
| `expert_demos/` | 27G | cuRobo 演示数据（`failure.txt` / `trajectory.npz` 判成败） |
| `rollouts/` `trash/` | 少量 | smoke rollout / 已 trashed session |

### B. 一次性工程验收现场（**不是**实验证据）

`cloth_contact_repair_v1` · `clothforge_coverage_v1` · `clothforge_integration_v1` · `cloth_multisolver_v2` · `cloth_unification_v1` · `verification` · `visual_fidelity`

识别特征：里面有 `audit.py` / `browser.mjs` / `backend-deployment-*.json` / `ACCEPTANCE.md` / `acceptance-summary.json`。
这些是**改代码时的验收留痕**，机器可读证据哈希在 [`docs/clothforge/`](clothforge/)。
**查代码改动验收看这里，查研究结果别看这里。**

### C. 工具产物（可重建）

`views/`（9 个证据分桶 symlink 视图）· `RUN_INDEX.md` / `RUN_INDEX.json`

## `docs/` 路由

| 文件 | 回答什么 |
|---|---|
| [`README.md`](../README.md) | 怎么起服务、采集流程、worker 可靠性 |
| [`DATA_TO_TRAINING_GUIDE_ZH.md`](DATA_TO_TRAINING_GUIDE_ZH.md) | **数据 → 导出 → 训练 → 评测全链路** |
| [`CLOTHFORGE_STATUS.md`](CLOTHFORGE_STATUS.md) | 布料工作流现状 |
| [`CUROBO_EXPERT_DEMOS.md`](CUROBO_EXPERT_DEMOS.md) | expert 演示怎么生成 |
| [`ROBOT_CLOTH_SCENES.md`](ROBOT_CLOTH_SCENES.md) | 布料场景定义 |
| [`ASSET_REGISTRY.md`](ASSET_REGISTRY.md) | 资产注册表 |
| [`NEWTON_INTEGRATION.md`](NEWTON_INTEGRATION.md) | Newton 求解器接入 |
| [`ISAAC_CUBE_OPENPI_PILOT.md`](ISAAC_CUBE_OPENPI_PILOT.md) | Isaac 方块 lift OpenPI 试点 |
| [`YEAR1_MILESTONES.md`](YEAR1_MILESTONES.md) | 一年里程碑 |
| [`clothforge/*.json`](clothforge/) | 验收证据哈希（机器可读） |

## 现在站在哪

**已跑通**：五求解器布料播放与结果复用、XPBD 接触修复、episode 归一、ClothForge 工作流、RoboVerse 多任务批量采集、PickCube state-BC、cuRobo expert 演示、consumer 导出 + smoke 全过。

**没到**：闭环、真机、独立验证的目标机器人闭环提升。汇报时不要冒充。

## 磁盘布局

- `/data`（NFS 10T，共享）—— 所有管线数据
- `/home/zhanghejun/rds-cache`（本地 ext4 16T）—— 可再生 cache
  - `data/cache`、`data/expert_demos/*/cache` 已迁过去，原路径留 symlink；**按路径解析的消费方无需改配置**
  - 丢了能重建（`cache/ov` 是 Omniverse shader 缓存，重建代价是首次启动重编译）
- `data/studio.db` 里存的是**绝对路径**，所以不要物理重排 `data/` 下的 episode / dataset / export 目录
