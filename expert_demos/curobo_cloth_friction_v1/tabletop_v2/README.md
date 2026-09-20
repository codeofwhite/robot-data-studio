# L 形工作台布料任务 · tabletop_v2

四项任务各三个初态：桌沿取布并铺开、定向铺平、平移与旋转对齐、翻开折角。复用原 L 形工作台与单 Franka；cuRobo 规划真实关节轨迹，Genesis FEM / IPC 解算布料。辅助夹持已经用户批准，约束只连接闭合夹爪和一个局部布料节点，逐步记录；不使用桌面吸附。

## 目录约定

- 本目录：版本化任务配置、动作实现、场景构建、运行和交付工具。
- `assets/sources/robot-cloth-scenes-v1/scenes/tabletop_v2/<task>/<variant>/`：冻结场景、任务目标、构建来源和 SCN / MDL 登记。已有场景不覆盖。
- `data/expert_demos/curobo-cloth-v1/tabletop_v2/tasks/<task>/<variant>/runs/<run-id>/`：每次运行独立目录，包含状态轨迹、规划、事件、代码快照、物理资产、视频、Canonical Episode 和检查。
- 同批次 `diagnostics/`：场景预检与初始规划；`reports/`：环境、启动记录、日志与批次检查；`index.html` 和 `manifest.json`：聚合索引。

旧 `l-table-assisted-007` 及失败运行保留。成功状态由本次真实动作及观察决定，不从旧结果继承。

## 文件职责

`catalog.json` 定义三种初态、目标和阶段。`build_scenes.py` 生成等距布料网格，继承原场景并注册来源。四个任务模块组合 `actions.py` 中的接近、重新观察、夹持、拉角、释放动作；抓取偏差超出既有局部范围时记录并重试，最多三次。

`metrics.py` 从实际顶点判断任务变化：悬垂减少、面积展开、目标位置与方向、折角对角线展开。检查采用演示级容差；投影凸包面积是粗略指标，不能代替视觉检查。

`pipeline.py` 复用已有环境，逐阶段运行；`render.py` 与 `cached_visual_robot.py` 在原场景渲染记录的顶点和关节；`media.py` 生成交互轨迹、保留所有帧的四倍速视频和索引；`verify.py` 核对原始状态、帧映射、文件哈希和 Episode。

## 命令

从 `/data/zhanghejun/robot-data-studio` 执行。所有 GPU 命令和子进程必须保留 `CUDA_VISIBLE_DEVICES=0,1`，内部设备索引由 `--device` 或两工作进程分配。

```bash
CUDA_VISIBLE_DEVICES=0,1 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B expert_demos/curobo_cloth_v1/tabletop_v2/pipeline.py --stage build --variants v001 v002 v003
CUDA_VISIBLE_DEVICES=0,1 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -u expert_demos/curobo_cloth_v1/tabletop_v2/pipeline.py --stage run --variants v001 --workers 2
```

可用 `--task unfold_corner` 等限制任务。其他阶段：`preflight`、`render`、`export`、`verify`、`publish`。`all` 完成运行、渲染和导出，等待实际视觉检查，不自动填写视觉通过。运行发生已记录的任务中止时保留诊断，其他任务可继续；异常命令退出会明确报错。

```bash
CUDA_VISIBLE_DEVICES=0,1 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B expert_demos/curobo_cloth_v1/tabletop_v2/media.py
PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover -s expert_demos/curobo_cloth_v1/tests -v
```

新视频主视角 5 Hz、俯视角 2 Hz，均覆盖全程；已发布的第一条翻角保留 10 Hz 主视角。四倍速预览保留全部源帧，以 20 fps 播放新视频。原始控制保持 100 Hz，状态快照约 50 Hz，Episode 读取实际主视角频率。交互几何视图读取实际记录，不做轨迹插值。渲染只平滑显示法线，物理顶点保持一致。Canonical Episode 是可追溯源数据；登记示范不等于训练 QA 自动接受。

验收为 `SELF_REVIEWED_PROVISIONAL`。辅助夹持可能出现毫米级到厘米级滞后，材料参数未经真机标定；不声明纯摩擦抓取、真机成功率、跨初态或跨材料泛化。

任务开始前会将动作模块和延迟导入的帮助函数绑定到本次 `source_snapshot/`，`task_code_binding.json` 保存执行路径。评价代码按全部帮助文件的哈希归档。定向铺平至少拉两个不同布角；对齐至少拉两个不同布角，并检查各布角距目标不超过 5 cm。桌沿任务会避开预检中不可达的最终落点，改从其他角展开。

物理仿真与 RTX 渲染分批执行，避免争用。不要用 SIGSTOP 暂停 RTX 进程；若需要重渲，先结束进程，将未发布的旧输出连同哈希移入 `render_attempts/`，再运行渲染。以完整 `verification.json` 判定渲染完成，Isaac 的进程退出码不能单独作为依据。重试日志单独编号；不覆盖已经发布的证据。

反向褶皱初态（定向铺平 v003）在两次拉角后会探测剩余布角的 cuRobo 悬停可达性，记录 `corner_approach_probe`，再选择当前可达的角。评价 1.1 单独核对未执行探测与实际运动：失败探测允许保留，实际执行计划仍必须成功，全部规划请求纳入输入哈希。

GPU 按卡分配：同一卡不同时跑物理与 RTX；一张卡的物理结束后可先渲染，另一张卡继续剩余物理。
