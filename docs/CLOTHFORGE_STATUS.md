# ClothForge / Robot Data Studio 阶段总结

衣物库、实时外观预览及直筒／阔腿款式的最新进展与后续执行计划见 [衣物演进计划](CLOTHING_EVOLUTION.md)。下文保留各历史阶段的范围和证据，其中早期三类 30 件的覆盖结果不自动适用于后续八类衣物与新款式。

当前已在基础布料动力学工作台上加入统一任务入口、只读数据入库和五求解器切换/比较（新增阶段见文末）。实物材料尚未到位，公司设备尚待交付；实物标定、真机接触和 sim-to-real 验证暂缓，不作为本阶段阻塞项。

## 已完成

- 独立 ClothForge 项目：参数化版片、缝合关系、三角网格、OBJ/GLB、静止形状和可追溯参数。使用 Newton VBD 执行真实轨迹。
- 3 种基础版型（T 恤、长裤、单层开襟外套），每种 10 个尺寸变体；3 种未实测的合成材料。30 个几何不等于 30 种独立款式。
- Studio：选择衣物、选择材料/调参、运行、进度、刷新恢复、播放/暂停、时间轴、旋转缩放、下载、重开不可变参数快照。图库明确显示真实尺寸和版型范围。
- 180/180 个预设组合通过：30 个尺寸变体 × 3 种材料 × 悬挂/落地。原始轨迹复算通过，并逐项匹配当前 UI 默认数值设置。当前矩阵引用 40 条历史记录和 140 条本轮结果。
- 修复 5 个物理失败案例，并保留原失败证据。通过改变数值求解精度处理拉伸/接触问题，未改变材料、网格或放宽门槛。
- 真实浏览器检查全部 30 个变体、180 个选项组合及三类衣物原生运行；11 份下载轨迹哈希匹配。验收时 27 项相关后端测试、TypeScript 和生产构建通过。
- 本轮 157 次原生任务，272.49/300 分钟；审计时 2.42/20 GB。原 644 个注册版本、10 个仿真源码文件的哈希保持不变。

## 范围与后续

通过范围仅为两秒仿真、61 个保存帧的有限值、伸长、面积、穿地、速度及采样自交检查。尚不证明长时稳定、连续无穿插、真实面料参数或机器人操作成功。不同材料使用各自通过的数值配置，响应对比图不构成材料辨识实验。

现阶段可继续丰富明显不同的版型和提高对比操作体验；Genesis IPC 并排对比见下方新增阶段；PPF 接入见最新阶段；真实材料辨识、真机抓取和 sim-to-real 尚未完成。待公司设备及实物材料到位后，再制定实测与真机验证计划。

## Git 保存范围

- ClothForge 为独立本地仓库：保存源码、冻结配置、测试与 README；现有第三方源码、Python 环境和仿真产物不纳入 Git。
- Studio 提交包含布料 UI/API、资产版本契约、最小注册/验证基础服务及其测试。混合文件仅暂存布料所需部分；其他 Isaac 渲染和机器人任务改动保留在工作区。
- [coverage.csv](clothforge/coverage.csv) 保存 180 项结果索引；[acceptance-summary.json](clothforge/acceptance-summary.json) 保存验收摘要；[evidence-sha256.json](clothforge/evidence-sha256.json) 保存原始报告、账本及媒体哈希。
- 大体积原始文件仍在服务器 `data/clothforge_coverage_v1/`、`data/cloth_runs/` 和相邻 `ClothForge/data/`。Git 提交不是这些外部产物的完整备份，单独克隆源码不会自带衣物库/轨迹。

## 环境和复现入口

ClothForge 的环境版本、固定 GarmentCode 提交、生成/仿真/导入命令见相邻仓库 `ClothForge/README.md`。原始试点配置用于复现历史失败；当前通过的默认值由 `NewtonClothRunManager._solver` 和本轮矩阵记录。使用新输出目录，不覆盖历史证据。

Studio 参数通过 `ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT`、`ROBOT_DATA_STUDIO_CLOTHFORGE_PYTHON`、`ROBOT_DATA_STUDIO_CLOTHFORGE_GPU_ID` 等环境变量配置；来源目录位于 `config/asset_sources.json`。当前路径是本机配置，迁移时需要修改。

首期几何/材料可由 ClothForge 的 `export-studio` 导入；历史 48 条修复结果可通过 `robot_data_studio.services.clothforge_importer.import_clothforge(AssetRegistry(), dry_run=True)` 预检后导入。后续运行由 Studio 自动追加配置与验证，不继承旧的物理结论。

当前服务器入口：`http://127.0.0.1:3000/assets?view=cloth`；远程使用既有 3000/8010 端口转发。

## 上一阶段提交前复核（02de210）

从 Git 暂存区导出独立目录进行检查：41 项资产/布料后端及契约测试通过，TypeScript `tsc --noEmit --incremental false` 通过；ClothForge `unittest discover -s tests -v` 17 项通过。未启动新的 GPU 仿真。既有第三方依赖的弃用告警保留，不在本次更新依赖。

对应独立 ClothForge 源码提交：`758baff532c9c606e248df8fe8566cde430ecc46`。


## 2026-09-18：统一入口、只读入库与跨求解器比较

入口：`http://127.0.0.1:3000/cloth`（远程仍通过现有端口转发）。

- **操作成果**：读取 tabletop_v2、folding_v3、fixtures_v4 的交付清单，按任务/初始状态展示真实视频、诊断尝试、失败原因和 Episode 链接。`video_*` 资产角色统一显示，4 倍速概览显式标注。机器人示范带局部辅助夹持，尚不提供此处一键重跑。
- **入库**：完整交付、成功评估、注册完整性、轨迹指纹、Canonical Episode 校验全部通过后入库。导入前 SQLite 一致性备份；按 UUID 幂等；原数据不搬移、不重写。新记录为 pending，旧 QA 不改变。导入会话禁止启动、移入回收站和删除。
- **导出连接**：审核后的只读导入可从严格匹配的已交付目录进入原导出流程；pending 仍被拒绝。隔离数据库的 25 条 LeRobot `physical_joint8` 预检通过；OpenPI `openpi_franka_joint8` 因缺少 base/wrist RGB 全部拒绝。此次未替用户审核、导出训练集或训练模型。
- **求解器比较**：选择 T 恤、长裤、开襟外套的 000 版型；中等合成材料；悬挂/自由落地。Newton VBD 和 Genesis IPC 顺序运行，共用 GPU 锁；状态、不可变配置和验证资产持久化。历史选择、同步播放/时间轴/视角、统一空间比例均由原生顶点轨迹驱动。
- **公平性边界**：加载前核对网格拓扑、版片静止度量、固定点、初始位置、质量和时间轴。IPC 在原生 uipc 几何上设置平面静止度量、永久共享顶点缝合、自由接缝铰链、固定点、体积及质量；接触地面显式创建。两引擎能量、阻尼与接触规律不等价，不宣称材料已标定或 sim-to-real 成功。
- **数值设置**：IPC 8 子步、最多 128 Newton 迭代；Newton VBD 保留此前通过的默认值；各侧均 2 秒、61 帧。本机版本为 Genesis 1.3.1 / pyuipc 0.0.25；IPC 单次监督超时为 600 秒（Newton 保持 300 秒）。不是同算力基准，物理验收门槛未放宽。页面耗时来自 worker 报告的仿真与检查阶段，不含初始化；资源预算按整进程壁钟时间计。

文件与数据流：

| 文件 | 变化及作用 |
| --- | --- |
| `app/cloth/page.tsx`, `components/app-shell.tsx` | 新布料任务页和统一导航入口 |
| `components/cloth-task-center.tsx`, `lib/cloth-types.ts` | 成果目录、视频、入库反馈及接口类型 |
| `components/cloth-solver-comparison.tsx` | 成对运行、历史恢复、同步顶点回放和指标 |
| `config/asset_sources.json` | 保存已有布料成果及其场景依赖的两个来源配置；其他来源变更留在工作区 |
| `backend/src/robot_data_studio/routes/cloth.py`, `main.py` | 新目录、入库和比较 API，并注册路由 |
| `services/cloth_catalog_service.py` | 只读交付清单、注册媒体及数据库索引状态 |
| `services/cloth_episode_importer.py` | 校验、备份、事务入库；不自动接受 QA |
| `services/session_service.py`, `worker_manager.py` | 保护导入会话的原始文件和只读属性 |
| `services/export_service.py` | 保留原 raw 路径规则，增加严格限定的已交付导入来源 |
| `services/cloth_run_service.py` | 原 Newton 原生进程流程扩展为两后端；添加成对监督与初始化校验 |
| `backend/tests/test_cloth_import.py`, `test_clothforge_studio.py` | 入库幂等/保护、视频角色、跨引擎配置、损坏/不匹配轨迹拒绝 |
| 相邻 ClothForge 的 `comparison.py`, `genesis_worker.py`, `__main__.py`, `tests/test_comparison.py` | IPC 原生执行、明确材料映射、选择引擎和静止度量测试 |

未删除既有功能或历史产物。旧入口仍保留。大体积仿真、截图、录屏、备份和验收脚本位于 `data/cloth_unification_v1/` 与 `data/cloth_runs/`，不加入源码 Git。

本阶段检查命令（使用既有环境，未安装依赖）：

```bash
# Studio 暂存快照在 data/cloth_unification_v1/staging/robot-data-studio
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:packages/robot-data-contracts/src \
  /data/zhanghejun/robot-data-studio/backend/.venv/bin/python -B -m pytest \
  -p no:cacheprovider --import-mode=importlib backend/tests/test_assets.py \
  backend/tests/test_cloth_import.py backend/tests/test_clothforge_studio.py \
  backend/tests/test_cloth_run_service.py backend/tests/test_exports.py \
  packages/robot-data-contracts/tests/test_assets.py -q
# Studio 工作目录
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node node_modules/typescript/bin/tsc --noEmit --incremental false
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node node_modules/.bin/vinext build
# ClothForge 工作目录
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:third_party/GarmentCode \
  .venv-generation/bin/python -B -m unittest discover -s tests -v
```

本地浏览器实操脚本为 `data/cloth_unification_v1/browser.mjs`，独立数据库导出预检为 `export_probe.py`，资源及结果汇总为 `audit.py`。检查中修复了视频角色未兼容和导入来源不在 `datasets/raw` 而被导出器拒绝的问题。隔离快照首次因旧测试硬编码仓库目录名而有 4 项失败，改用同名隔离目录后通过；ClothForge 测试必须包含现有 GarmentCode 的 PYTHONPATH。未为通过测试安装依赖或放宽断言。


本阶段最终结果：6 组成对基准、12/12 原生案例通过；另一次浏览器按钮发起的 2 个原生案例通过，并自动加载同步回放。共 18 次原生尝试（含诊断与保留的超时），累计 45.97/60 分钟，保守计入全部共享求解器缓存的新增产物约 0.192/5 GB。25 条已交付示范入库且保持 pending，原 126 条 QA 不变；隔离数据库的 LeRobot 预检全部通过，OpenPI 因缺少 base/wrist RGB 拒绝。

57 项 Studio/契约测试、19 项 ClothForge 测试、TypeScript 和生产构建通过。长裤 IPC 落地初次 300 秒超时，保持相同物理参数延长单次监督等待后通过；失败证据保留。验收采用既有环境、共享 GPU 5，未停止其他 GPU 进程。

结构化证据：[unification-acceptance.json](clothforge/unification-acceptance.json)、[unification-evidence-sha256.json](clothforge/unification-evidence-sha256.json)。ClothForge 对应源码提交为 `d9df7ba`。浏览器截图为 `data/cloth_unification_v1/solver-comparison.png`、`task-center.png`，录屏在同目录 `browser-video/`。


## 五求解器接入（2026-09-18）

入口：`/cloth` → “跨求解器比较”。选择衣物、悬挂/落地后自动读取参数一致的原生历史结果。回放下拉框切换不启动 GPU；可选择单窗口或任意两项并排，时间与相机同步。运行区支持选择 1–5 个求解器；默认复用历史结果，取消勾选才强制重新计算。旧的未指定 `engine_ids` 请求仍运行 VBD + IPC。

新增 Newton XPBD、PhysX Surface Deformable、PPF；保留 Newton VBD 和 Genesis IPC。固定三种 `000` 版型、中等合成材料、两秒/61 帧，没有新增尺寸。

### 原生模型与限制

- XPBD：原生 Newton `SolverXPBD`，512 子步 × 2 迭代。细网格小质量与并行弹簧修正导致此前 64 子步发散，缩小时间步后消除爆炸。仅启用网格边弹簧，排除会跨接自由接缝的对顶点弹簧；`tri_ka`、`tri_kd` 不等价映射。粒子接触不保证三角面无自交，失败轨迹仍可查看，不能计为物理通过。
- PhysX：现有 Isaac Sim 6.0.1 环境，原生 Surface Deformable 和顶点到世界的附件约束。原生验证会拒绝完全重合的平面参考顶点；使用装配厚度的 1e-4 作为参考分离，并逐面验证静止边长误差不超过 1e-6 m。仿真起始顶点保持不变。接触 rest/contact/filter 距离为 0.3/2/0.6 mm；保留物理门槛，接缝弯曲仍为均匀原生模型。质量来自已校验原生参考面积与材料面密度，运行时节点质量缓冲区未独立读回。
- PPF：在官方编译镜像的原生 CUDA 后端执行。镜像清单摘要 `sha256:3be1692bf1cf29f6a4e0435e746ca43382c69ce049c304bf501e9c943062320b`；执行固定镜像 ID `sha256:2a1fdc6da8775c05d5f57e3441e59dde0b7a0f99dfe03676abaf024c80e2e8ae`。现有 clone 仅用于接口检查，未修改；镜像与本地源码版本不混称。每帧 8 子步、最多 2048 Newton 步；接触间隙 0.5 mm、原生应变屏障 10%，地面摩擦显式匹配材料。映射原生重排顶点，并以逐面参考/装配面积比修正密度，保证统一质量。速度由保存帧有限差分估计，不是原生瞬时速度；接缝弯曲与 VBD/IPC 不等价。
- 五个后端的本构、阻尼、接触和弯曲模型不同，数值迭代预算不同。本轮是可追溯效果对比，不是相同算力排名，也不证明实物精度或 sim-to-real。

官方 PhysX 网格验证会检查重复顶点，见 [PxValidateTriangleMesh](https://nvidia-omniverse.github.io/PhysX/physx/5.4.0/_api_build/function__px_cooking_8h_1ac4d006397ab50386ae2913e7d2f4464d.html)。本机原生失败日志和修复后的静止边长误差保存在本轮 QA 目录。

### 文件与行为变化

| 文件 | 变化及原因 |
| --- | --- |
| `ClothForge/src/clothforge/__main__.py` | 原两后端分派扩展为五后端；命令行校验求解器名称。 |
| `ClothForge/src/clothforge/newton_worker.py` | 增加原生 XPBD 路径、面内弹簧静止长度和明确的参数映射；VBD 仍走原有求解器分支。 |
| `ClothForge/src/clothforge/native_io.py` | 新增不可变请求、标准轨迹评测和预览输出；缺帧、固定点漂移及非有限状态均保留失败判定。 |
| `ClothForge/src/clothforge/physx_worker.py` | 新增隔离 Isaac 进程、参考形状映射、原生附件、轨迹及错误导出。 |
| `ClothForge/src/clothforge/ppf_worker.py` | 新增固定镜像 Docker worker、重排/质量映射、原生轨迹与镜像溯源；退出时清理本次容器。 |
| `ClothForge/tests/test_native_io.py` | 验证完整运行不能掩盖缺帧、固定点漂移或 NaN。 |
| `backend/src/robot_data_studio/services/cloth_run_service.py` | 删除固定双后端循环，改为已选择后端顺序调度；新增配置/资产哈希验证后的历史复用；历史回放也校验完整证据；超时终止本任务进程组和 PPF 容器。 |
| `backend/src/robot_data_studio/routes/cloth.py` | 比较请求增加 `engine_ids`、`reuse`；新增只读 `/api/cloth/solver-results`，兼容旧请求。 |
| `components/cloth-solver-comparison.tsx` | 固定两窗口改为选后端运行、缓存切换、单/双窗口与失败日志；同步回放保留，手动刷新也可重新读取其他任务刚完成的结果。 |
| `lib/cloth-types.ts` | 补充后端选择、历史复用、原生运行来源和错误日志字段。 |
| `backend/tests/test_clothforge_studio.py` | 覆盖 1/2/3/5 侧比较、非法选择、参数与门槛保持、缓存配置/轨迹/资产损坏拒绝，以及 PPF 原生进度解析。 |
| `docs/CLOTHFORGE_STATUS.md` | 更新可用范围、验收证据、实际参数与未验证项。 |

原始机器人 Episode、人工 QA 状态和训练导出未修改。布料求解轨迹入资产库的 config/validation 记录，不伪装为含机器人动作的 Episode。

### 验收证据

本轮目录：`data/cloth_multisolver_v2/`。`budget.json` 逐项保留原生尝试与耗时；失败诊断不删除。`report.json` 汇总当前配置的 30 个结果（VBD/IPC 复用上一轮已验证数据）。`browser-report.json` 与浏览器视频保存实际点击验收；`ppf-xpbd-comparison.png` 为页面截图。

自动测试：Studio 布料与资产测试 61 通过、3 个不适用的单侧配对检查跳过；ClothForge 原有 19 项通过，新增原生结果判定测试通过。TypeScript 类型检查与生产构建通过。浏览器已验证无 GPU 的切换、单/双窗口、同步回放与视角、复用运行和刷新恢复。最终覆盖数字见下方本轮结果表。

| 求解器 | 当前配置完整轨迹 | 物理通过 | 未通过原因 |
| --- | ---: | ---: | --- |
| Newton VBD | 6/6 | 6/6 | 无 |
| Genesis IPC | 6/6 | 6/6 | 无 |
| Newton XPBD | 6/6 | 1/6 | excessive_stretch, self_intersection |
| PhysX Surface | 6/6 | 0/6 | self_intersection |
| PPF | 6/6 | 6/6 | 无 |

本轮实际 35/36 次原生尝试，累计 worker 壁钟 32.43/60 分钟；新增仿真记录 144.69 MB（上限 5 GB）。PPF 镜像压缩层约 494 MB，下载/导入中间文件另计约 944 MiB，未改变现有 Python 环境。无任务遗留 PPF 容器，其他进程保留。

VBD/IPC 的 12 个结果复用上一轮验收；三个新后端提供 18 个最终配置结果。诊断、旧配置和失败尝试均保留，但不混入最终 30 格统计。最终的原生新任务浏览器验收为 PPF T 恤落地，`browser-native-report.json` 记录执行成功、物理通过及非缓存启动。六组页面切换、重复手动刷新、单/双窗口和历史恢复均通过；`browser-coverage.json` 每组均为五个求解器。

尚未完成：XPBD/PhysX 在本批衣物上的全部物理通过。不能把“已接入、已跑完”解释为无穿插；当前推荐用于物理通过演示的是 VBD/IPC/PPF。实物材料辨识、真机接触和 sim-to-real 仍未验证。

执行的验证命令（均使用已存在环境）：

```sh
# Studio 根目录，测试结果 61 passed / 3 skipped
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m pytest -q -p no:cacheprovider backend/tests/test_clothforge_studio.py backend/tests/test_cloth_run_service.py backend/tests/test_cloth_import.py backend/tests/test_assets.py
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node node_modules/typescript/bin/tsc --noEmit --incremental false
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node node_modules/.bin/vinext build
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B data/cloth_multisolver_v2/audit.py
/home/zhanghejun/node-v24.18.0-linux-x64/bin/node data/cloth_multisolver_v2/browser.mjs --launch-cached
backend/.venv/bin/python -B data/cloth_multisolver_v2/browser_native_qa.py
# ClothForge 根目录；原有 19 项与新增 1 项（含 4 个子场景）通过
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:third_party/GarmentCode .venv-generation/bin/python -B -m unittest discover -s tests -v
```

审查标签 `SELF_REVIEWED_PROVISIONAL`；原生执行、浏览器和哈希/配置匹配证据均已落盘。ClothForge 本轮本地提交：`26c875a`。


## XPBD / PhysX 物理修复（2026-09-18）

本轮结论见 `data/cloth_contact_repair_v1/report.json`；当前工作是物理修复，不是材料或尺寸扩量。原始衣物网格、材料预设、质量来源和表面验收门槛保持不变。历史试错结果保留，不把运行结束等同于物理通过。

### 改动与数据流

| 文件 | Before → After / 原因与影响 |
| --- | --- |
| `ClothForge/src/clothforge/xpbd_contact.py`（新增） | 原生粒子接触 → 每步增加顶点–面、边–边接触与明确的 1.10 主伸长约束目标（迭代近似，并非严格上界）、材料面积弹性；使用质量加权且共享松弛系数的投影以保留内部线动量。它是 XPBD 扩展，并非未修改的原生 XPBD，也不是经过证明的连续碰撞检测。 |
| `ClothForge/src/clothforge/newton_worker.py` | 接入扩展；修复小时间步从世界坐标 float32 差分重建速度导致的虚假加速/停滞，改用增量速度更新；使用求解器保存的步前位置而非已被修改的输入缓冲；在初始化证据中记录扩展和材料映射。原来的零弹簧阻尼由材料名义阻尼替代，面积使用原 `tri_ka`，不等同 VBD 能量模型。 |
| `ClothForge/src/clothforge/physx_worker.py` | 错误的面密度直接传入体密度接口、无效 stretch/shear 设置 → 按厚度换算体密度、Young 模量及弯曲尺度，并显式写入总质量。移除冗余 API 和额外未记录的启动步；记录 USD、碰撞属性和原生时间。增加掉落前 0.2 秒质心运动检查，超过 5 mm 或缺失数据仍标失败。结果在原运行结束前原子替换，避免独占文件创建冲突。 |
| `ClothForge/tests/test_xpbd_contact.py`（新增） | 覆盖顶点–面/边–边、边界绕序、微小时间步速度、自由落体、面积/拉伸和动量守恒。 |
| `ClothForge/tests/test_physx_material.py`（新增） | 覆盖面积质量/膜参数单位换算，以及形状通过不能掩盖运动异常。 |
| `backend/src/robot_data_studio/services/cloth_run_service.py` | Studio 默认配置写入新的求解参数和修订号；配置哈希变化，使旧失败结果不会被当成当前配置缓存。接口字段及入库流程保持原有契约。 |
| `backend/tests/test_clothforge_studio.py` | 验证接触修复配置不改变材料、网格、验收门槛，并使缓存键失效。 |
| `docs/CLOTHFORGE_STATUS.md` | 保存本轮范围、限制、验证和交付证据。 |

原生 XPBD 的速度钳制在增量更新扩展中不再使用；实际超速仍由原验收门槛拒绝。早期出现“形状通过但几乎静止”的试验不计作修复成功。PhysX 的质量是显式 authored 总质量及原生参考面积检查，当前接口未提供运行时节点质量读回；不声称已测得原生节点质量。PhysX 缝线仍使用统一弯曲设置，材料阻尼尚未实现与 Newton 等价的映射。

PhysX 参数单位依据本机 Isaac Sim 6.0.1 schema 与 [官方变形体说明](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/dev_guide/deformables/deformable_bodies.html)。修正单位并不意味着已消除 PhysX 的自相交或运动异常。

### 验证与边界

- 后端资产/布料相关回归：`pytest ...test_clothforge_studio.py ...test_cloth_run_service.py ...test_cloth_import.py ...test_assets.py`，63 passed、3 skipped；既有 Starlette/httpx 弃用告警保留。
- ClothForge 生成环境：`unittest discover -s tests -v`，22 passed、1 skipped（该环境没有 Warp）；另补结果写入回归并单独执行 PhysX 测试，3 passed。
- 既有 Newton 环境单独执行 `test_xpbd_contact.py`：8 passed，包括质量不均及不同邻接数时的内部动量检查。
- 原生验证限定 GPU 5、最多 36 次/3600 秒累计 worker 验收时间/2 GB 新运行结果，不终止其他任务。未启动的队列不计入原生次数，但保留账本。
- 目标覆盖为 medium 材料、三款 000 衣物、悬挂/掉落、2 秒及 61 个保存帧；不证明其它材料、长时稳定、所有时刻无穿插或 sim-to-real。
- 审阅等级：`SELF_REVIEWED_PROVISIONAL`，未使用外部审阅服务。

### 本轮最终结果

XPBD 最终配置 **6/6 通过**；PhysX 最终配置 **0/4 通过**，另有外套悬挂/掉落两项未在本轮预算内执行。因此 `all_requested_repairs_passed=false`，不能宣称全部修复完成。Newton VBD、Genesis IPC、PPF 的各 6 条历史结果仅复用展示，没有在本轮重新运行或新增物理结论。

| 求解器 | 衣物 / 场景 | 结论 | 最大自交对数 | 额外运动问题 | 运行 ID |
| --- | --- | --- | ---: | --- | --- |
| newton_xpbd | tshirt-000 / hanging | passed | 0 | 无 | `run-20260918t123032z-0110badb` |
| physx_surface | tshirt-000 / hanging | failed | 11 | 无 | `run-20260918t123821z-40b41342` |
| newton_xpbd | tshirt-000 / drop | passed | 0 | 无 | `run-20260918t123432z-3125df01` |
| physx_surface | tshirt-000 / drop | failed | 107 | freefall_motion_mismatch | `run-20260918t124223z-05d942b5` |
| newton_xpbd | trousers-000 / hanging | passed | 0 | 无 | `run-20260918t123852z-c0111ad3` |
| physx_surface | trousers-000 / hanging | failed | 66 | 无 | `run-20260918t124714z-c62a03f2` |
| newton_xpbd | trousers-000 / drop | passed | 0 | 无 | `run-20260918t124321z-a8839ade` |
| physx_surface | trousers-000 / drop | failed | 61 | freefall_motion_mismatch | `run-20260918t124746z-3583aa32` |
| newton_xpbd | open_coat-000 / hanging | passed | 0 | 无 | `run-20260918t122607z-17738b5b` |
| newton_xpbd | open_coat-000 / drop | passed | 0 | 无 | `run-20260918t121757z-2a9e4706` |

36 次原生尝试，累计 3554.84 秒（59.25 分钟），新运行产物 168,734,104 字节；达到次数上限后停止。结果包含正常执行但物理失败；早期写入异常及废弃候选均留在预算账本中。

浏览器实操通过：T 恤悬挂/掉落均可切换五个已保存求解器；XPBD/PhysX 并排/单视图、同步播放/暂停、时间轴、相机重置、刷新恢复、两条缓存结果复用通过；无页面异常。截图 `data/cloth_contact_repair_v1/xpbd-physx-drop.png`，录像在同目录 `browser-video/`。本轮未修改前端说明文字，其中旧的“XPBD 使用粒子接触”简介尚未涵盖新增表面扩展；实际启用设置可在“实际模型与参数”和运行初始化证据中查看。

证据目录：`data/cloth_contact_repair_v1/` 的 `report.json`、`budget.json`、`verification.json`、`browser-report.json`；运行原始轨迹位于 `data/cloth_runs/`。这些大体积/运行时证据不纳入 Git。

报告 SHA-256：`0a4253edc70ec5f6a2279ea84a15cff9581f10ef74724bd21233aa6f30cc939f`。ClothForge 源码提交：`1fd4298`。尚未完成：PhysX 原生 Surface 的自相交、自由落体偏差，以及外套两例最终配置覆盖；未追加 GPU 预算、安装依赖或宣称 sim-to-real 成功。
