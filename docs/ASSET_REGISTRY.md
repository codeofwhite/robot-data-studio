# 资产与材料管理

版本：v2；实施核对日期：2026-09-17。

## 使用入口

Studio 导航中的“资产与材料”，地址为 http://127.0.0.1:3000/assets。远程使用时需要将 GPU 服务器的 3000 和 8010 端口转发到本机同名端口。

资产库支持按名称、固定编号、标签、类型、引擎和验证结果搜索，并筛选引用文件一致或证据过期的记录。列表展示最新版本，详情展示版本历史、参数与单位、引用关系、模型预览、下载链接和验证失败原因。

首批来源为 /data/zhanghejun/simulation-demos/cloth-batch-v1，共 203 个资产：
8 类场景、3 个合成材料预设、24 套几何模型、24 套配置、144 条历史验证记录。验证结果保留 40 条通过和 104 条失败。Newton 可使用相同契约登记，但本次导入不代表已接入 Newton 仿真 worker。

## 固定编号与不可覆盖版本

| 类型 | 编号示例 | 内容 |
|---|---|---|
| 场景 | SCN-textile_feeding | 任务、场景族、几何和夹具描述 |
| 材料 | MAT-cloth-light | 参数、单位、合成/标定状态与后端映射 |
| 模型 | MDL-textile_feeding__light | Blend、GLB、OBJ、网格及预览文件 |
| 配置 | CFG-textile_feeding__light | 完整参数、内容指纹和依赖版本 |
| 验证记录 | VAL-场景-引擎-运行编号 | 原结果、指标、失败门槛、运行与评价器来源 |

发布后编号与资产类型固定。点击“发布新版本”生成 v2、v3 等，原 JSON 版本不会覆盖。修改历史版本前需前往最新版本；并发发布采用期望版本校验，冲突返回 HTTP 409。

引用包含 asset_id、version 和 role。修改材料不会改写已有配置引用，修改配置也不会继承旧验证。配置与结果需要显式关联对应版本。更正历史记录可发布新版本；新的实验运行应登记新的验证编号。

“登记新资产”支持自定义编号或自动生成编号；参数与引用使用 JSON 编辑。材料参数建议保存为 {"parameters":{"gsm":{"value":80,"unit":"g/m2"}}}。来源文件通过注册来源编号与相对路径添加，由服务器读取并计算校验值；不会上传或重写原模型与试验数据。

created_at 是登记/发布时刻，不是历史实验执行时刻。change_note 记录本次变更；原试验时间未知时不推断。

## 存储、指纹与证据语义

注册表位于 [assets/registry](/data/zhanghejun/robot-data-studio/assets/registry)，布局为 <固定编号>/v000001.json。写入在进程锁下进行，使用临时文件与排他创建保存完整记录；API 不提供覆盖或删除版本的操作。

[来源配置](/data/zhanghejun/robot-data-studio/config/asset_sources.json) 是受控目录清单。文件必须位于对应来源内；拒绝路径穿越和越界符号链接。预览与下载只通过已登记版本和文件序号访问；校验不一致时拒绝提供文件。

每个版本保留：
- 登记内容 SHA-256：识别资产元数据与引用变化。
- 参数内容 SHA-256：以排序后的 JSON 计算，忽略键顺序、缩进和空白。
- 原文件 SHA-256 与字节数：保持历史原文件的身份与追溯能力。

检查发现 24 个目录配置与被选中运行配置的 JSON 值相同，但字节校验值不同；导入保留两类指纹，不回写原文件。144 份运行配置及轨迹均按历史校验值核验。

文件一致只说明登记的文件和依赖版本当前吻合，不代表物理试验通过。原验证结果始终独立显示；任一来源或依赖变化，记录标为“证据过期 / 缺失”，旧结果保留。合成预设不计入实物面料标定；笛卡尔夹爪结果不代表完整机械臂可达性。

列表默认仅显示最新版本，历史版本仍可经详情访问。参考关系固定到版本，因此旧引用不随“最新版本”移动。相同源资料再次导入复用已有相同版本；即使用户已经发布新版本，也不会撤回用户修改或将旧验证改绑到用户新版本。

## 导入与核验命令

以下命令在 /data/zhanghejun/robot-data-studio 执行，复用现有 backend/.venv，不安装依赖。

```bash
export PYTHONPATH=backend/src:packages/robot-data-contracts/src
export PYTHONDONTWRITEBYTECODE=1
backend/.venv/bin/python -B -m robot_data_studio.asset_cli import --source cloth-batch-v1 --dry-run
backend/.venv/bin/python -B -m robot_data_studio.asset_cli import --source cloth-batch-v1
backend/.venv/bin/python -B -m robot_data_studio.asset_cli verify
```

导入先检查全部来源，再逐条原子发布；中断后可幂等重试，不将整批导入误称为数据库事务。首次结果 created=203，重复结果 created=0、unchanged=203。

环境变量：
- ROBOT_DATA_STUDIO_ASSET_ROOT：注册表根目录，默认项目 assets/registry。
- ROBOT_DATA_STUDIO_ASSET_SOURCES：来源配置路径，默认 config/asset_sources.json。

资产元数据使用文件注册表，原有 Episode 数据库无需结构迁移。Source 文件不在注册表中复制；迁移时需同时迁移来源资产并调整根目录。资产编号和版本本身不依赖根目录路径。

## API 与代码职责

| 文件 | 职责 |
|---|---|
| packages/robot-data-contracts/src/robot_data_contracts/asset.py | 五类资产、引用、文件与不可缺失的验证字段 |
| backend/src/robot_data_studio/services/asset_service.py | 版本发布、冲突控制、校验、搜索、版本关系 |
| backend/src/robot_data_studio/services/asset_importers.py | 读取现有布料资产和历史验证，保存来源与指纹 |
| backend/src/robot_data_studio/asset_cli.py | 导入预检、导入和完整性核验 |
| backend/src/robot_data_studio/routes/assets.py | API：列表、详情、发布、文件检查及下载 |
| components/asset-library.tsx、components/asset-detail.tsx | 搜索、参数详情、历史与新版本表单 |
| app/assets/page.tsx、app/assets/[id]/page.tsx、lib/asset-types.ts | 路由和前端契约 |

现有文件修改仅增加契约导出、资产存储设置、API 路由和导航入口。移动导航由四列变五列以容纳资产库。其他采集流程继续使用原接口。

主要 API：
- GET /api/assets：q、kind、engine、outcome、integrity、offset、limit。
- GET /api/assets/{id}?version=N：版本详情、历史、正向/反向引用。
- POST /api/assets：draft 与 expected_version。
- GET /api/assets/sources；POST /api/assets/artifacts/inspect。
- GET /api/assets/{id}/versions/{version}/artifacts/{index}。

## 验证与边界

检查产物位于 [data/verification/asset-registry-v1](/data/zhanghejun/robot-data-studio/data/verification/asset-registry-v1)。核心测试覆盖版本保留、并发冲突、失效依赖、越界路径、篡改文件、API 搜索、重复导入及用户新版本保护。测试只使用独立临时目录。

```bash
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m pytest -q --import-mode=importlib -p no:cacheprovider --basetemp data/verification/asset-registry-v1/pytest-final packages/robot-data-contracts/tests/test_assets.py backend/tests/test_assets.py backend/tests/test_asset_import.py
node_modules/.bin/tsc --noEmit --incremental false
node_modules/.bin/oxlint app/assets components/asset-library.tsx components/asset-detail.tsx components/app-shell.tsx lib/asset-types.ts
npm run build
```

现有 FastAPI/Starlette 测试客户端产生 httpx 弃用提示，测试通过；本次没有为此升级依赖。浏览器已核验资产计数、固定编号搜索、材料参数与单位、新版本表单、配置关联、960×720 模型预览，以及 40 条通过 / 104 条失败筛选。浏览器检查未向正式注册表发布测试版本；发布与并发冲突使用隔离 API 测试验证。页面控制台未发现错误。

开发启动器曾报 Cloudflare runner Network connection lost；构建通过后，使用项目已有的 node_modules/.bin/vinext start --hostname 127.0.0.1 --port 3000 成功提供页面。后端在 127.0.0.1:8010 运行；本机已有 VS Code 端口转发可访问二者。服务是本次启动的后台进程，不是已配置的开机自启服务。过程日志与进程信息保存在验证目录。

当前适用于本地研究工作组规模，搜索读取版本文件并核验来源。注册表没有跨主机分布式写入保证，也没有新增公网身份认证；沿用 Studio 本机访问方式。用户登记的验证结果属于提交者的记录，平台不代替重新运行物理试验。

## 本次逐文件变更

| 文件 | 增加或替换的行为与原因 |
|---|---|
| packages/robot-data-contracts/src/robot_data_contracts/asset.py | 新增五类资产、发布版本、依赖和证据契约；拒绝非法编号、非有限参数、缺少证据的验证记录 |
| packages/robot-data-contracts/src/robot_data_contracts/__init__.py | 增加资产类型导出，既有 Episode 导出保留 |
| packages/robot-data-contracts/tests/test_assets.py | 新增编号、参数、路径和验证证据约束测试 |
| backend/src/robot_data_studio/services/asset_service.py | 新增文件注册表、排他发布、乐观并发检查、哈希检查和版本关系查询 |
| backend/src/robot_data_studio/services/asset_importers.py | 新增布料来源预检与分版本导入；格式变化不算物理参数变化，用户后续版本不被导入撤回 |
| backend/src/robot_data_studio/asset_cli.py | 新增 dry-run、导入和 verify 命令，支持重复导入与结果核验 |
| backend/src/robot_data_studio/routes/assets.py | 新增资产 API 和受控文件服务；错误分别返回 404、409 或 422 |
| backend/src/robot_data_studio/config.py | 新增注册表和来源配置路径设置，保持现有路径设置 |
| backend/src/robot_data_studio/main.py | 注册 assets 路由，保持原 API 与生命周期 |
| backend/tests/test_assets.py | 新增不可覆盖、并发、依赖失效、越界和 API 行为测试 |
| backend/tests/test_asset_import.py | 新增幂等导入、用户修订保护与配置内容指纹测试 |
| config/asset_sources.json | 新增 cloth-batch-v1 的受控来源根目录 |
| assets/registry/<编号>/v000001.json | 新增 203 份登记记录；保存明确版本依赖及原文件校验值 |
| app/assets/page.tsx | 新增资产列表路由 |
| app/assets/[id]/page.tsx | 新增资产详情路由 |
| components/asset-library.tsx | 新增计数、搜索、类型/引擎/结果/完整性筛选、分页和登记入口 |
| components/asset-detail.tsx | 新增参数表、来源文件、依赖关系、版本历史及新版本表单 |
| lib/asset-types.ts | 新增前端数据类型、编号前缀、标签与版本链接工具 |
| components/app-shell.tsx | 新增资产导航；移动端导航四列改五列，使新入口可见 |
| docs/ASSET_REGISTRY.md | 新增操作、数据语义、命令和验证说明 |
| docs/YEAR1_MILESTONES.md | 新增完成基础与证据，实物标定和 Newton worker 接入保持待办 |

本次没有删除原有业务代码。整体行为由“资产散落于仿真目录、Studio 无统一入口”变为“资产有固定编号和独立版本，可搜索并沿引用追溯配置与原验证”。验证文件只作读取，未重跑或改写原物理试验。

## v2 验证概览

完成日期：2026-09-17。资产页默认进入“验证概览”，可切换“资产索引”继续管理全部资产。

概览每行对应一个配置的最新版本，展示 Genesis / Isaac 的通过次数、结论、按出现次数排序的前两项失败原因及代表视频。点击“6 次”展开本配置的单次记录，查看全部失败原因、证据状态和固定版本链接；搜索支持名称、配置编号和标签。顶部卡片及结论下拉框用于筛选。

统计规则：
- 同一验证编号仅使用最新修订，补充视频的 v2 不增加实验次数。
- 只汇总显式引用该配置当前版本、角色为 tested_config 的记录；其他配置版本的记录不继承，在展开区提示历史数量。
- 同一引擎的 evaluator_version 和 scope 必须一致；多个规则组分别展示，不合并判定通过。
- 同一规则下至少 3 条记录全部通过且证据完整，才标记该引擎通过；少于 3 次或存在未判定记录均待补验证。
- 两引擎都通过、仅 Genesis 通过、仅 Isaac 通过分别标记。有失败且两者均未通过时归入“需修复”；证据失效、不同评价规则和待验证单独分类。
- 每项失败门槛在同一次运行只计一次；不同失败门槛可以同时出现，次数不可相加当作失败运行总数。
- 代表视频优先展示有录像的失败运行，否则展示有录像的通过运行；每个引擎最多选一个，明确显示该次结果，不把它当作全部重复运行的证明。

当前核验结果：24 套配置、144 条独立验证（40 通过 / 104 失败）；5 套双引擎通过、1 套仅 Genesis 通过、1 套仅 Isaac 通过、17 套需修复。共 16 个已核验回放，覆盖 11 套配置，其余 13 套显示暂无可用视频。历史回放来自已记录轨迹的 Matplotlib 渲染，没有重新进行物理仿真；固定初始条件的笛卡尔夹爪筛查不代表随机扰动鲁棒性、完整机械臂或实物一致性通过。

### 视频登记与 API

16 条历史验证各新增 v2，仅增加 video、video_provenance 文件引用及本次变更说明，结果、配置引用和指标原样保留。登记前检查来源视频、来源说明、已登记轨迹的 SHA-256 和 physical_steps=0；整批预检后逐条发布。命令限定为源码列出的 16 个运行目录，重复执行不增加版本。203 个原 v1 文件逐字节保持不变，当前总计 203 个资产 / 219 个版本。

在项目根目录执行，使用原有环境，无新增依赖：

```bash
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m robot_data_studio.asset_cli link-validation-videos --dry-run
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m robot_data_studio.asset_cli link-validation-videos
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m robot_data_studio.asset_cli verify
```

新增 GET /api/assets/validation-overview，返回 items、summary、minimum_repeats。查询只读，不发布或修改记录。原文件接口对 video 角色的 MP4/WebM 提供正确媒体类型与 Range 分段读取，保留文件哈希检查；失效证据禁止播放。

### 逐文件变更与数据流

| 文件 | Before → After → Reason |
|---|---|
| components/asset-library.tsx | 默认平铺资产索引 → 默认验证概览，可切回索引；减少144条验证对阅读的干扰，原资产操作保留 |
| components/validation-overview.tsx（新增） | 新增汇总组件：读取概览 API → 本地搜索和筛选 → 每行按需展开 → 固定版本证据链接 / 视频弹窗 |
| lib/asset-types.ts | 保留资产类型，增加概览、引擎分组、失败计数和单次记录类型；明确 API 与 UI 数据结构 |
| backend/src/robot_data_studio/services/validation_overview.py（新增） | validation_overview 按验证编号取最新修订、按配置版本及规则分组；link_validation_videos 预检并追加录像引用 |
| backend/src/robot_data_studio/routes/assets.py | 新增概览 GET 接口；原下载接口对已登记视频返回可播放响应，其他类型处理不变 |
| backend/src/robot_data_studio/asset_cli.py | 新增 link-validation-videos 与 --dry-run；原 import 和 verify 命令不变 |
| backend/tests/test_validation_overview.py（新增） | 7项隔离测试覆盖版本隔离、修订去重、规则分组、失败计数、证据失效、录像来源、幂等登记和视频Range接口 |
| assets/registry/VAL-*/v000002.json | 仅对已批准的16条验证新增不可覆盖修订，所有旧版本保留；精确编号见验收目录 video-link.json |
| docs/ASSET_REGISTRY.md | 增加汇总规则、视频语义、命令与逐文件行为说明 |
| docs/YEAR1_MILESTONES.md | 记录验证概览完成依据；首个布料任务运行闭环仍待完成 |

没有删除业务模块或原始记录；资产页原默认索引改为概览入口。对外新增只读 API，原有 API 路径保留；视频文件响应类型从下载改为在线播放。

### 验收

产物：[本次验收目录](/data/zhanghejun/robot-data-studio/data/verification/validation-overview-v1)。23项资产相关 Python 测试通过，前端类型检查、lint 和构建通过。视频重复登记新增0，219个版本完整性检查无错误，203个v1原文件哈希保持一致。

```bash
PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m pytest -q --import-mode=importlib -p no:cacheprovider --basetemp data/verification/validation-overview-v1/pytest-final packages/robot-data-contracts/tests/test_assets.py backend/tests/test_assets.py backend/tests/test_asset_import.py backend/tests/test_validation_overview.py
node_modules/.bin/tsc --noEmit --incremental false
node_modules/.bin/oxlint components/validation-overview.tsx components/asset-library.tsx lib/asset-types.ts
npm run build
```

浏览器验收证据及最终文件哈希见 final_report.json。服务沿用 127.0.0.1:3000 / 8010，当前后台进程记录在 services.json；本次未配置开机自启。测试中的 Starlette/httpx 弃用提示不影响通过，未因此升级依赖。

审查状态：SELF_REVIEWED_PROVISIONAL。本次整理历史证据和界面，没有新增物理实验、生成缺失录像或宣称完成机器人布料数据闭环。
