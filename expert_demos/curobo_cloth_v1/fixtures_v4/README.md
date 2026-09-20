# L 形工作台：横杆、收纳筐与覆盖任务

五类任务，各三个初态。沿用原写实 L 形工作台与单 Franka，cuRobo 规划机械臂路径，Genesis FEM / IPC 解算布料，使用用户已批准的局部辅助夹持点。搭杆修订3额外使用已批准的可见止滑夹，单个局部节点固定在夹口；其余任务仍仅用夹爪辅助。

截至2026-09-18的本次检查，其他四类任务的12条示范已完成。搭杆修订2仍处于动作诊断：已有分段执行证据，但尚未获得可接受的杆上展开结果，不能作为成功示范复现承诺。详细失败诊断见 `reports/rod_diagnostics_manifest.json`；止滑夹方案见 `reports/ROD_SUPPORT_OPTION.md`，本轮已获批准并实现动作修订3（连接夹架场景修订4），完整物理和视频验证状态以运行清单为准。

当前完成数量以 `data/expert_demos/curobo-cloth-v1/fixtures_v4/index.html` 和 `manifest.json` 为准。历史失败、旧动作版本和正在运行的记录不计入完整示范。

| 任务 | 实际动作与检查 |
| --- | --- |
| 搭杆悬挂，动作修订 3（夹具辅助） | 慢送布上杆 → 确认杆承托 → 松开 → 第一侧送入可见夹口并夹固 → 换抓另一侧、沿杆拉开 → 机械手松开，夹具保持。最终挂住本身不能替代杆上分段铺开。 |
| 取下挂布并铺开 | 观察上方材料边界、探测可达抓点 → 提离杆 → 转移至接收台 → 多次低位拉角展开。 |
| 布料放入收纳筐 | 提起 → 移至开口上方 → 降入 → 松手 → 退出。 |
| 从筐中取布整理 | 取出 → 搬至台面 → 下降扫放 → 重新观察并逐角展开。后续尝试优先探测材料角点。 |
| 用布覆盖盒子 | 低位跨桌搬运 → 盒上放布，按观测重心作至多 3 cm 横向修正 → 松开 → 两处布边各向外整理 2 cm。 |

三条旧搭杆记录为一次跨杆释放，没有满足用户后来明确的杆上分段铺开要求。它们保持冻结，在图库标记为历史版本，见 `reports/rod_task_revision_2.json`。既有取杆上布场景仍保留其原父轨迹来源，不改写初态。

## 目录与追溯

```text
expert_demos/curobo_cloth_v1/fixtures_v4/       控制、构建、渲染与核验源码
assets/sources/robot-cloth-scenes-v1/scenes/fixtures_v4/<task>/<variant>/
                                             冻结 USD、道具参数、初态来源
 data/expert_demos/curobo-cloth-v1/fixtures_v4/
  index.html / manifest.json                 当前意图下的示范与全部尝试
  tasks/<task>/<variant>/runs/<run-id>/       每次独立物理运行
  diagnostics/<task>/<variant>/              未执行的规划探测与诊断快照
  reports/                                  作业、日志、检查与变更说明
```

每个完整运行保存：

- `trajectory.npz`、`physics.jsonl`、`grasp_constraints.jsonl`：状态、逐步命令与辅助点偏差。
- `plans/`、`events.json`、`task_progress.json`：每次 cuRobo 查询、已执行动作、未执行探测、换抓与阶段指标。
- `config.json`、`scene_binding.json`、`source_manifest.json`、`source_snapshot/`：参数、原场景引用、代码和资产哈希。环境与 GPU 映射另存 `environment_provenance.json`、`launch.json`。
- `pbr_replay/front.mp4`（主视角 5 Hz）、`pbr_overhead/front.mp4`（俯视 2 Hz）：同一轨迹的完整回放。逐帧 tick 和哈希见各视角 `verification.json`。
- `overview_4x.mp4`：原帧全部保留的四倍速总览；不删去换抓或整理阶段。`trajectory_view.html` 提供离线几何回放。
- `evaluation.json`、`visual_review.json`、`delivery_verification.json`：数值检查、实际查看代表帧的观察和最终关联核验。三者通过后才登记证据包 `evidence.zip`。
- `replay/verification.json`：Canonical Episode 的路径及哈希。登记与导出不等同于训练 QA 接受。

物理指令 100 Hz，状态快照约 50 Hz。渲染只回放已记录关节与顶点，法线平滑仅影响光照。运行冻结源码，因此编辑后续任务不会改变正在执行的动作。已发布运行不覆写；重跑创建新目录。

## 场景和验收含义

横杆长 44 cm、直径 3 cm、中心高 1.01 m；筐 34 × 28 × 12 cm；盒子 22 × 16 × 9 cm。均为参数化合成道具，材料没有真机标定。筐的底板和四壁分别碰撞，不用封闭开口的整体凸包。

两个取布任务从对应放置运行的实际末态构建初态，保存父轨迹哈希与时间步；新仿真速度归零，不声称连续 checkpoint。抓点和修正动作读取仿真状态，是脚本专家示范。

检查重视完整动作、释放后的可见效果和可追溯性，允许残余褶皱。取布检查台面附近节点至少 88%、投影凸包面积至少 72%、至少两个实际调整角；中心偏差仅报告，不要求对齐标线。横杆检查杆上支承、两侧下垂、分段换抓，支承宽度另作描述。覆盖检查盒顶实际投影覆盖至少 80% 和至少三个下垂方向。任何最终视频仍需实际查看。

布料未完全展开的运行保留为诊断。辅助夹持可能有毫米至厘米级滞后，逐运行报告偏差。不声称纯摩擦抓取、真机成功率或跨材料泛化；检查标记 `SELF_REVIEWED_PROVISIONAL`。

## 复现

在 `/data/zhanghejun/robot-data-studio` 运行，使用现有环境，不安装依赖：

```bash
CUDA_VISIBLE_DEVICES=5 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover -s expert_demos/curobo_cloth_v1/fixtures_v4/tests -v
CUDA_VISIBLE_DEVICES=2,3 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -u data/expert_demos/curobo-cloth-v1/fixtures_v4/reports/run_rod_clip_r3.py --variant v003
```

执行前检查 GPU 占用。已授权的显式掩码为 `CUDA_VISIBLE_DEVICES=0,1`、`1`、`2,3`、`4`、`5` 或 `6`。`2,3` 内部设备 0/1 对应物理 2/3，`0,1` 内部 0 对应物理 0，单卡掩码内部 0 对应指定物理卡；cuRobo 使用第一张可见卡，IPC 使用 `--device`，RTX Vulkan 使用对应物理卡。每个命令必须显式设置掩码。其他批次的 GPU 配置保持原约定。

`pipeline.py` 另有 build、preflight、render、export、verify、publish 阶段；all 执行物理、渲染和导出，不伪造视觉审核。整条运行加文件锁后再渲染双视角和导出，避免重复写入。应先查看真实保存帧再调用 `media.record_visual_review`，随后核验和登记。

新展开策略会检查名义矩形的四角；第三初态若低位外角不可达，则探测向内平移 (-.02,+.015) m 的矩形，仍须在接收台内。名义与实际目标、所有被拒规划均保留。`evaluate.py` 分别核验已执行路径和未执行的目标探测；规划失败不能伪装成执行成功。

逐文件说明和历史诊断见 `reports/CHANGES.md`。环境追溯包含版本、设备、代码与任务资产，不包含整个引擎安装目录的快照。首两条早期冻结 README 中“引擎文件哈希”的说法不准确，应按本段理解，冻结证据不改写。

杆上换抓在接近前和悬停后重新观察当前杆顶材料边，不追逐已经滑到杆侧的旧编号。候选筛选、重选原因、实际夹持编号和所有规划查询都保存。

杆顶候选来自当前实际支承的整个布料边界，按世界坐标左右排序；两次拉开选择至少相隔10cm材料距离的点。送布距离由半布长、杆半径与放下高度估算，并记录名义值与实际值，仍检查释放后的真实支承。原固定材料边分组在布料旋转后会丢失有效抓点，相关失败保留。

夹具辅助版本使用独立 `rod_clip_r<revision>` 场景目录和资产编号；不得用旧 pipeline 的缓存初始姿态直接启动新版。`fixture_constraints.jsonl` 与夹爪约束日志分开保存，每步可检查节点归属和目标误差。夹具固定外壳参与碰撞；活动夹口是约束状态的可见指示，局部夹固由 IPC SoftPositionConstraint 解算。这不是纯接触夹紧或自由裸杆悬挂。材料、摩擦、速度、力和应变阈值未改变。

夹口的第一侧送入路径提高10mm，再降回原夹持高度，避开实际出现的中间姿态IK拒绝。整段先在当前关节状态和完整碰撞几何中探测；未执行探测单独标记，后续实际路径另存。`physics.jsonl` 的 `cloth_health.fixture_constraint_after_step` 保存每个积分步的实际夹固节点和误差。
