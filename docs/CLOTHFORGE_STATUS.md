# ClothForge / Robot Data Studio 阶段总结

当前完成的是基础布料动力学工作台。实物材料尚未到位，公司设备尚待交付；实物标定、真机接触和 sim-to-real 验证暂缓，不作为本阶段阻塞项。

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

现阶段可继续丰富明显不同的版型和提高对比操作体验；PPF/其他求解器、真实材料辨识、真机抓取和 sim-to-real 均未完成。待公司设备及实物材料到位后，再制定实测与真机验证计划。

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

## 本次提交前复核

从 Git 暂存区导出独立目录进行检查：41 项资产/布料后端及契约测试通过，TypeScript `tsc --noEmit --incremental false` 通过；ClothForge `unittest discover -s tests -v` 17 项通过。未启动新的 GPU 仿真。既有第三方依赖的弃用告警保留，不在本次更新依赖。

对应独立 ClothForge 源码提交：`758baff532c9c606e248df8fe8566cde430ecc46`。
