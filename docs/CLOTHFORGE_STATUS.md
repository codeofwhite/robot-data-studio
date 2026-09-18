# ClothForge / Robot Data Studio 阶段总结

当前已在基础布料动力学工作台上加入统一任务入口、只读数据入库和 Genesis IPC／Newton VBD 比较（新增阶段见文末）。实物材料尚未到位，公司设备尚待交付；实物标定、真机接触和 sim-to-real 验证暂缓，不作为本阶段阻塞项。

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

现阶段可继续丰富明显不同的版型和提高对比操作体验；Genesis IPC 并排对比见下方新增阶段；PPF、真实材料辨识、真机抓取和 sim-to-real 均未完成。待公司设备及实物材料到位后，再制定实测与真机验证计划。

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
