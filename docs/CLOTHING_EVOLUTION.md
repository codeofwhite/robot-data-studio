# 衣物演进计划与变更记录

更新日期：2026-10-12。共同维护人：用户与 Codex。

这份文档记录衣物目前能做什么、下一步改变什么，以及每项工作的执行范围和结果。Studio 负责选择、预览和运行入口；相邻的 ClothForge 项目负责版片、缝合与网格生成。

## 共同约定

- UI 按“类别 → 款式 → 尺寸”组织，默认折叠，需要时展开编辑区域。
- 款式用属性和生成规则描述，不能只改名称。例如阔腿款需要实际改变裤脚轮廓。
- 外观和物理材料分别配置：贴图、颜色、粗糙度改变视觉效果；面密度、刚度、摩擦等改变运动响应。
- 改尺寸或款式时生成真实网格；改外观时更新浏览器材质。预览与保存分开，保存才注册新资产，保留原模型和版本。
- 本文管理计划与记录，不另行定义运行参数。控件范围、预设和接口约束以对应配置及代码为准。
- 验证采用正常使用流程：能生成、能预览、能保存、能进入已有运行流程。按改动需要做类型检查和构建，不另加防御性测试或大规模参数矩阵。

## 分类与参数怎么理解

| 层级 | 含义 | 示例 |
| --- | --- | --- |
| 类别 `category` | 基本结构与用途 | `trousers` 长裤、`towel` 毛巾 |
| 款式 `style_id` | 轮廓或缝合结构的生成规则 | `straight` 直筒、`wide` 阔腿 |
| 尺寸 `parameters` | 同一规则下的实际几何尺寸 | 裤长、腰部平铺宽、单腿裤脚平铺宽 |
| 外观 `appearance` | 应用到网格上的视觉配置 | PBR 材质、原色／染色、法线强度 |
| 物理材料 | 求解器使用的材料参数 | 面密度、拉伸／弯曲刚度、摩擦 |

类别是衣物库的八个分支。款式和尺寸继续往下组织，外观与物理材料作为可选配置，不为每种颜色、贴图重复建立树节点。

## 当前能力

| 类别 | 标识 | 已有基础尺寸 | 自定义款式／尺寸能力 |
| --- | --- | --- | --- |
| 短袖上衣 | `tshirt` | 10 件 | 复用 GarmentCode 圆领／V 领，连续调整衣长、衣宽、领宽与领深 |
| 长裤 | `trousers` | 10 件 | 直筒／阔腿／收口，连续调整裤长、腰宽、裤脚宽 |
| 开襟外套 | `open_coat` | 10 件 | 目前切换已有网格 |
| 毛巾 | `towel` | 10 件 | 目前切换已有网格 |
| 餐巾 | `napkin` | 10 件 | 目前切换已有网格 |
| 长袖上衣 | `long_sleeve` | 10 件 | 目前切换已有网格 |
| 短裤 | `shorts` | 10 件 | 目前切换已有网格 |
| 半身裙 | `skirt` | 10 件 | 目前切换已有网格 |

80 件是基础库规模，不是总资产数量上限，也不代表 80 种独立款式。保存自定义款式后，目录数量会增加；除长裤与短袖外，其余六类尚未接入连续尺寸生成。

八类共用真实网格缩略图、可旋转 PBR 预览、外观保存和工位入口。ClothForge 批量入口生成 Newton 悬挂／落地轨迹；已有 cuRobo 衣物外观批次仍基于其源示范重渲染，两种流程分别保留。

## 执行方式

1. 先选一个任务编号，讨论目标和范围，写清涉及文件及正常流程验证方式。
2. 用户对具体范围回复 `approve` 后，任务标为“已批准”；只有这份范围内的工作可以执行。仅把想法写进文档不等于批准实现。
3. 执行时标为“进行中”。已批准的范围无需重复确认；增加文件、环境或实质行为时，补充范围并再次批准。
4. 完成后标为“已验证”，记录新增／替换行为、验证结果和产物路径。
5. 用户要求 commit 后，记录各仓库提交号，标为“已提交”。commit 与 push 分开记录，只有明确要求才推送。

状态使用：待讨论、待批准、已批准、进行中、已验证、已提交。状态不能代替具体结果；例如“已提交”不代表已推送或机器人任务成功。

## 任务清单

| 编号 | 任务 | 状态 | 结果／下一动作 |
| --- | --- | --- | --- |
| G001 | 八类基础衣物库与批量入口 | 已提交 | 基础 80 件；每类抽一件 Newton 悬挂运行，8/8 通过 |
| G002 | 真实衣物缩略图与 PBR 实时预览 | 已提交 | 材质、已有尺寸切换、外观保存及工位配置跳转通过 |
| G003 | 直筒／阔腿长裤与连续尺寸生成 | 已提交 | 两款正常生成、调参、保存；Newton 短轨迹 2/2 通过 |
| G004 | 长裤收口款 | 已提交 | 16 cm 裤脚预设，生成与保存跳转正常，Newton 短轨迹 1/1 通过 |
| G005 | 复用 GarmentCode 圆领／V 领短袖 | 已验证 | 两款生成、调参和保存跳转正常，Newton 短轨迹 2/2 通过 |

### G001：八类基础衣物库

- **目标**：从三类 30 件扩至八类基础 80 件，复用现有材质、工位与运行入口。
- **变化**：新增毛巾、餐巾、长袖上衣、短裤、半身裙各 10 件；增加独立的多衣物串行悬挂／落地批次。UI 改为默认折叠的类别和变体选择。
- **参数与代码**：[生成配置](../../ClothForge/configs/library_v1.json)、[生成器](../../ClothForge/src/clothforge/generate.py)、[衣物库 UI](../components/asset-library.tsx)、[批量 UI](../components/clothforge-batch-panel.tsx)、[批量服务](../backend/src/robot_data_studio/services/clothforge_batch_service.py)。
- **验证**：新增 50 件几何全部生成，注册 50 模型和 150 材料配置；浏览器分类与选择正常；八类各一件 medium 材料的 Newton 两秒悬挂轨迹，8/8 通过。工位另抽 PhysX 餐巾和 Newton 半身裙确认加载、相机画面与主力臂切换。
- **提交**：Studio `82486be`；ClothForge `447623d`。
- **证据**：[交付说明](../../ClothForge/data/library_v1/DELIVERY.md)、[批次结果](../data/clothforge_batches/batch_result.json)、[浏览器结果](../data/clothforge_batches/browser_result.json)。

### G002：真实衣物与外观实时预览

- **目标**：在折叠衣物库里看到材质缩略图，展开后直接切换材质和已有尺寸。
- **变化**：用真实网格和逐角 UV 替代图库中的 Matplotlib 截图；新增 Three.js PBR 渲染。尺寸选择切换已有网格，保存外观后携带目标资产 ID／版本进入工位配置。其余物理流程沿用原实现。
- **参数与代码**：[网格预览](../components/cloth-garment-preview.tsx)、[衣物编辑器](../components/cloth-garment-picker.tsx)、[复用外观控件](../components/garment-appearance-panel.tsx)、[资产与网格 API](../backend/src/robot_data_studio/routes/assets.py)。
- **验证**：八类缩略图、折叠状态、尺寸切换、PBR 材质更新和保存跳转正常；工位配置保留所选衣物与材质。保存验证使用资产库和数据库副本。类型检查、构建与差异检查通过；该轮未重新运行物理仿真。
- **提交**：合并在 Studio `82486be` 中。
- **证据**：临时验证记录位于 `/tmp/cloth-garment-preview-v1/`，包含 `result.json`、`thumbnails.png`、`live-preview.png` 和 `DELIVERY.md`；临时目录不作为长期唯一证据，代码与提交记录用于追溯实现。

### G003：直筒／阔腿长裤

- **目标**：用一个直观例子打通“选款式 → 调尺寸 → 生成真实网格 → 换材质 → 保存 → 工位”。
- **变化**：增加 `hem_width_m`，改变真实裤脚轮廓；两款仍共用前后版片和缝合结构。停止拖动 600 ms 后调用单件生成器，保存时才注册新模型与三套物理材料配置，并记录父资产 ID／版本。
- **可调参数**：`length_m` 裤长、`waist_width_m` 腰部平铺宽、`hem_width_m` 单腿裤脚平铺宽。当前直筒／阔腿预设分别为 22／30 cm，具体范围与默认值以[款式配置](../../ClothForge/configs/trouser_styles_v1.json)为准。
- **参数与代码**：[单件生成与轮廓规则](../../ClothForge/src/clothforge/generate.py)、[CLI](../../ClothForge/src/clothforge/__main__.py)、[款式服务](../backend/src/robot_data_studio/services/trouser_style_service.py)、[衣物编辑器](../components/cloth-garment-picker.tsx)、[未注册网格预览](../components/cloth-garment-preview.tsx)、[资产 API](../backend/src/robot_data_studio/routes/assets.py)、[现有运行服务](../backend/src/robot_data_studio/services/cloth_run_service.py)、[来源注册](../config/asset_sources.json)。
- **验证**：直筒／阔腿生成不同网格；浏览器调整裤长至 103 cm、切换材质、保存并进入对应工位配置正常。两款各执行一次 medium 材料的两秒 Newton 悬挂轨迹，2/2 通过，各保存 61 帧。类型检查、构建和差异检查通过。
- **提交**：Studio `9b770c4`；ClothForge `a710b90`。记录提交不自动授予 push 权限。
- **证据**：[交付说明](../data/trouser_styles_v1/DELIVERY.md)、[运行结果](../data/trouser_styles_v1/verification.json)、[浏览器结果](../data/trouser_styles_v1/browser.json)、[界面截图](../data/trouser_styles_v1/preview.png)。交付说明中的提交状态是当轮快照，本节记录后续 commit。

### G004：长裤收口款

**状态：已提交。2026-10-12 用户已批准实现范围并要求 commit；实现与正常流程验证已完成。**

- **目标**：长裤款式选择增加“收口裤”，裤脚比直筒更窄，复用已有生成、PBR 预览、保存和工位入口。
- **参数**：`style_id=tapered`，默认单腿裤脚平铺宽 `hem_width_m=0.16`（16 cm），仍使用既有尺寸范围。第一版为裤腿轮廓收窄，不包含松紧带或罗纹结构。
- **涉及文件**：ClothForge `configs/trouser_styles_v1.json` 增加预设；Studio `services/trouser_style_service.py` 将错误提示改为已配置款式；本文件记录执行与结果。
- **产物位置**：预览与生成文件在 `data/trouser_styles_v1/`，保存后进入现有资产注册库；运行轨迹在 `data/cloth_runs/`。
- **正常流程验证**：生成收口裤、确认真实裤脚宽度、浏览器选择与保存跳转、一次 medium 材料 Newton 两秒悬挂轨迹。不新增防御性测试。
- **结果**：生成 817 顶点的收口裤；从版片量得实际裤脚宽度为 16 cm。浏览器自动显示第三款预设，真实网格与 PBR 预览、保存至临时资产副本并跳转所选衣物工位配置正常。正式资产新增一件收口裤及三套材料配置，原始资产保留。一次 medium 材料、两秒 Newton 悬挂轨迹通过，保存 61 帧；未验证松紧带、真实面料或机器人抓取。
- **证据**：[生成与保存记录](../data/trouser_styles_v1/63012dc12bab491884b7c04c3ebd8bf8/g004_selection.json)、[运行结果](../data/trouser_styles_v1/63012dc12bab491884b7c04c3ebd8bf8/g004_run.json)、[浏览器结果](../data/trouser_styles_v1/g004_browser.json)、[界面截图](../data/trouser_styles_v1/g004_preview.png)。配置 JSON 解析、差异检查通过；前端代码未修改，本次不重复构建。
- **提交**：ClothForge `a07e570`；Studio 为本文件首次入库的提交，可用 `git log --diff-filter=A -- docs/CLOTHING_EVOLUTION.md` 查询。未 push。

### G005：复用 GarmentCode 圆领／V 领短袖

**状态：已验证。2026-10-12 用户批准复用上游领口部件，实施与正常流程验证已完成。**

- **目标**：短袖支持圆领与 V 领，调整衣长、衣身宽、领宽与领深后重新生成真实网格；复用 PBR 预览、保存及工位流程。
- **上游复用**：本地 GarmentCode `CircleNeckHalf`、`VNeckHalf` 和 `linearize`。第一版前后片采用相同领口，曲线采样为版片边界，领口边保持未缝合。
- **参数来源**：ClothForge `configs/tshirt_styles_v1.json`；运行参数以该配置及代码为准。
- **涉及文件**：ClothForge `src/clothforge/generate.py`、新增款式配置；Studio `services/trouser_style_service.py`、`routes/assets.py`、`services/cloth_run_service.py`、`config/asset_sources.json`、`components/cloth-garment-picker.tsx` 和本文。
- **产物位置**：`data/tshirt_styles_v1/` 与既有 `data/cloth_runs/`；新资产保留父模型和版本。
- **正常流程验证**：两种领口生成、浏览器调参／材质与保存跳转；每款一次 medium 材料 Newton 两秒悬挂轨迹；类型检查、构建和文档链接检查。不新增防御性测试。
- **结果**：圆领 748 顶点、V 领 720 顶点；两款使用真实上游轮廓，默认领宽 18 cm，领深分别 6／10 cm。浏览器两款切换、领深改为 12 cm、PBR 材质更新、保存副本及对应工位配置跳转通过；原长裤三种预设仍能读取。每款一次 medium 材料、两秒 Newton 悬挂轨迹通过，各保存 61 帧。类型检查、构建、差异与文档链接检查通过；没有新增防御性测试或安装依赖，未验证机器人抓取与实测面料。
- **证据**：[生成资产](../data/tshirt_styles_v1/g005_selection.json)、[Newton 结果](../data/tshirt_styles_v1/g005_runs.json)、[浏览器结果](../data/tshirt_styles_v1/g005_browser.json)、[圆领截图](../data/tshirt_styles_v1/g005_crew.png)、[V 领截图](../data/tshirt_styles_v1/g005_vneck.png)。
- **提交**：尚未 commit 或 push。

G005 的文件与行为变化：

| 文件 | 新增／替换行为与原因 |
| --- | --- |
| ClothForge `generate.py` | 短袖传入领型时调用上游部件并用 `linearize` 采样，按领口段标记未缝合边；旧基础网格生成规则保留。单件生成从请求读取类别，兼容原长裤请求。 |
| ClothForge `configs/tshirt_styles_v1.json` | 新增两种领型、四个尺寸控件及默认值，作为 UI 与生成服务共同读取的参数配置。 |
| Studio `trouser_style_service.py` | 原长裤专用流程扩展为两个类别，共用生成和保存逻辑；按类别选择配置、来源、模型命名及元数据，默认仍为长裤。 |
| Studio `routes/assets.py` | 新增短袖款式配置、预览与保存 API，允许新来源的三维回放；原长裤 API 地址保留。 |
| Studio `cloth_run_service.py` | 允许短袖款式来源通过既有参数准备与 Newton 运行流程。 |
| Studio `config/asset_sources.json` | 新增 `clothforge-tshirt-styles-v1`，保存预览与已注册几何的来源路径。 |
| Studio `cloth-garment-picker.tsx` | 按类别选择短袖或长裤 API，短袖显示领型和四个滑块；生成后复用 PBR 与保存跳转。仅数值控件参数发送给 API，领型字符串由后端预设提供。 |
| 本文 | 登记 G005 的批准、当前能力、实现行为和验证结果。 |

后续候选仍待讨论：直裙／A 字裙。没有批准其实现。

## 后续任务填写模板

```text
编号与名称：
状态：待讨论
目标：用户能看到或操作什么变化
类别／款式标识：
参数与单位：配置或 schema 所在位置
行为变化：新增、替换或保留哪些流程
涉及文件：精确文件清单
产物位置：预览、已保存资产、运行结果
正常流程验证：本项需要走通哪些操作
批准记录：用户确认的范围；需要追加的范围单独记录
结果：实际验证内容、尚未验证内容、报告／截图路径
提交：Studio / ClothForge 的 commit；push 单独记录
```

## 变更记录

| 日期 | 记录 |
| --- | --- |
| 2026-10-12 | 建立共同维护文档，核对并登记 G001–G003 的代码提交与已有结果；G004 保持待讨论。仅批准本次文档建立，不新增款式。 |
| 2026-10-12 | 用户选择长裤收口款并批准 G004 的三文件范围与正常流程验证；开始执行。 |
| 2026-10-12 | G004 已验证：收口裤 16 cm 裤脚、浏览器保存跳转及一次 Newton 短轨迹通过。 |
| 2026-10-12 | 用户要求 commit，保存收口款预设、通用款式提示与共同维护文档；G004 标为已提交，未 push。 |
| 2026-10-12 | 用户批准 G005 复用 GarmentCode 圆领／V 领；八文件范围完成并验证，Newton 2/2 通过，未 commit 或 push。 |

原始报告与媒体在本机 `data/` 和相邻 ClothForge 项目中，通常不随 Git 分发。历史布料求解器与阶段覆盖记录继续保存在 [CLOTHFORGE_STATUS.md](CLOTHFORGE_STATUS.md)，历史通过结果不自动覆盖新增款式，也不代表机器人抓取或真实面料验证。
