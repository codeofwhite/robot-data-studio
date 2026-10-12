# GarmentCode 服装组件与接入清单

核对日期：2026-10-12。依据本地 ClothForge 的 GarmentCode 固定提交 `d449629979028123a5c4dc9e732a2ec19b7fce31`。本文是代码能力清单与接入建议，不是运行参数 schema，也不代表每个组件已通过 Studio 验证。

## 全局结构

GarmentCode 用可组合的版片程序生成缝合图样。它把“类别、部件选择、尺寸参数、人体测量”组合起来，而不是为每一种服装名称单独保存一个固定网格。

```text
MetaGarment（组合服装）
├─ 上身：Shirt / FittedShirt / 无
│  ├─ 衣身版片：普通 / 合体
│  ├─ 前后领口：分别选择曲线
│  ├─ 领部件：高领 / 翻领 / 兜帽 / 无
│  └─ 袖子：无袖 / 参数化袖子 → 可选袖口
├─ 腰带：StraightWB / FittedWB / 无
└─ 下身：Pants / 七种裙组件 / 无
```

上身与裙子可缝合成连衣裙，上身与裤子可组合成连体服；这些是组件组合，不是两个额外的独立生成器。调用完整服装组件时通常需要人体测量及派生测量，不能只传 Studio 当前的几个平铺尺寸。

来源：[本地组合入口](../../ClothForge/third_party/GarmentCode/assets/garment_programs/meta_garment.py)、[本地设计参数](../../ClothForge/third_party/GarmentCode/assets/design_params/default.yaml)、[上游固定版本](https://github.com/maria-korosteleva/GarmentCode/tree/d449629979028123a5c4dc9e732a2ec19b7fce31)。

## 可选择的服装与部件

| 部分 | 实现名称 | 轮廓／结构与可调内容 | 本地源码 |
| --- | --- | --- | --- |
| 普通上衣 | `Shirt` | 普通衣身，可组合领口和袖子；长度、宽松度、下摆展开、左右不对称 | [bodice.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bodice.py) |
| 合体上衣 | `FittedShirt` | 合体衣身与省道；支持无肩带选项；与普通上衣的参数作用不同 | [bodice.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bodice.py) |
| 领口边界 | `CircleNeckHalf`、`VNeckHalf`、`SquareNeckHalf`、`TrapezoidNeckHalf`、`CurvyNeckHalf`、`CircleArcNeckHalf`、`Bezier2NeckHalf` | 圆领、V 领、方领、梯形、曲线、圆弧、二次 Bezier；领宽、领深及对应角度／曲线参数；前后分别配置 | [collars.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/collars.py) |
| 领部件 | `Turtle`、`SimpleLapel`、`Hood2Panels` | 高领、简化翻领、双片兜帽；部件深度、翻领站立选项、兜帽深度与长度 | [collars.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/collars.py) |
| 袖子 | `Sleeve` | 无袖开关、袖长、连接宽度、末端宽度、袖角、立肩、袖根褶量 | [sleeves.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/sleeves.py) |
| 袖窿 | `ArmholeSquare`、`ArmholeAngle`、`ArmholeCurve` | 方形、折线、曲线连接轮廓；用于衣身与袖子的连接 | [sleeves.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/sleeves.py) |
| 袖口／裤口 | `CuffBand`、`CuffSkirt`、`CuffBandSkirt` | 带状收口、裙状展开、两者组合；长度、褶量、展开比例 | [bands.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bands.py) |
| 裤子 | `Pants` | 裤长、宽松相关参数、裤脚展开／收窄、腰位、可选裤口部件；长短裤可由长度参数区分 | [pants.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/pants.py) |
| 腰带 | `StraightWB`、`FittedWB` | 直腰带与贴合腰带；腰部松量、带宽 | [bands.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bands.py) |
| 组合服装 | `MetaGarment` | 选择上身、腰带和下身，并通过接口连接及缝合 | [meta_garment.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/meta_garment.py) |

### 七种完整裙组件

| 实现 | 对应结构 | 主要可调内容 | 本地源码 |
| --- | --- | --- | --- |
| `Skirt2` | 简单双片裙；无褶且零展开时为直轮廓，增加展开量可形成 A 字轮廓 | 裙长、腰位、腰褶、裙摆展开、侧边开口 | [skirt_paneled.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/skirt_paneled.py) |
| `PencilSkirt` | 合体铅笔裙，包含臀部塑形和省道 | 裙长、腰位、下摆收放、下摆角度、前后左右开衩、装饰切口 | [skirt_paneled.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/skirt_paneled.py) |
| `SkirtCircle` | 扇形／圆裙 | 裙长、腰位、展开圆量 `suns`、可选开口 | [circle_skirt.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/circle_skirt.py) |
| `AsymmSkirtCircle` | 前后不等长的圆裙 | 前部长度比例；实现中的非对称分支使用整圆构造 | [circle_skirt.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/circle_skirt.py) |
| `SkirtManyPanels` | 多片拼接展开裙 | 片数、展开量、裙摆曲率、裙长与腰位 | [skirt_paneled.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/skirt_paneled.py) |
| `GodetSkirt` | 在 `Skirt2` 或 `PencilSkirt` 基础上缝入三角插片 | 插片数量、宽度、深度、切口间距；构造时关闭基础裙开衩 | [godet.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/godet.py) |
| `SkirtLevels` | 多层接长裙，各层沿边界缝合 | 层数、基础层与后续层类型、层间褶量、总长、基础层长度比例 | [skirt_levels.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/skirt_levels.py) |

`SkirtLevels` 是接长结构，不应理解为已实现内衬或多层厚度材料。

### 内部版片、接口与辅助实现

这些是构建部件的底层实现，不需要全部变成 Studio 的独立款式选项。

| 模块 | 内部实现 | 用途 |
| --- | --- | --- |
| [tee.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/tee.py) | `TorsoFrontHalfPanel`、`TorsoBackHalfPanel` | 普通上衣的前后半片 |
| [bodice.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bodice.py) | `BodiceFrontHalf`、`BodiceBackHalf`、`BodiceHalf` | 合体衣身版片，以及领口／袖子组装 |
| [skirt_paneled.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/skirt_paneled.py) | `SkirtPanel`、`ThinSkirtPanel`、`FittedSkirtPanel` | 双片裙、多片裙、合体裙的单片构造 |
| [circle_skirt.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/circle_skirt.py) | `CircleArcPanel`、`AsymHalfCirclePanel` | 扇形与非对称裙版片 |
| [pants.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/pants.py) | `PantPanel`、`PantsHalf` | 裤片与单侧裤腿组装 |
| [sleeves.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/sleeves.py) | `SleevePanel` | 袖片构造 |
| [collars.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/collars.py) | `NoPanelsCollar`、`SimpleLapelPanel`、`HoodPanel` | 领口边界接口、翻领片、帽片 |
| [bands.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/bands.py) | `StraightBandPanel` | 腰带及收口使用的带状片 |
| [godet.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/godet.py) | `Insert` | 三角插片 |
| [base_classes.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/base_classes.py) | `BaseBodicePanel`、`BaseBottoms`、`StackableSkirtComponent`、`BaseBand` | 通用接口、腰位换算与可连接组件约定 |
| [shapes.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/shapes.py) | `Sun`、`SIGGRAPH_logo`、`SVGFile`、`sample_arc` | 装饰切口形状与曲线采样；SVG 形状需提供文件，默认配置未提供通用 SVG 文件入口 |
| [stats_utils.py](../../ClothForge/third_party/GarmentCode/assets/garment_programs/stats_utils.py) | `count_panels`、`bottom_length`、`sleeve_length`、`top_length`、`vertical_len`、`garment_type` | 版片统计、长度与类别分析；不是新款式 |

PyGarment 底层还提供 Edge、Panel、Component、Interface、Stitches、曲线和几何操作。ClothForge 已使用这些基础接口输出原生缝合描述，但这与复用完整 `Pants` 或 `Shirt` 程序是不同层级。

## 参数与单位：不能直接照搬 YAML 数字

默认 YAML 中的 `v` 是当前值，`range` 是上游配置器的采样／选择范围，`type` 是参数类型；它们不是 Studio API 的 schema。完整组件会根据人体尺寸换算或重写一些参数，再传给单片构造函数。

| 参数例子 | 实际含义／单位 | 接入时的处理 |
| --- | --- | --- |
| `SkirtPanel(waist_length, length, flare)` | 单片顶部长度、裙长、每侧展开量，原生厘米；底宽 = 顶宽 × `ruffles` + 2 × `flare` | Studio 米制平铺尺寸先乘 100；无褶时 `flare = (裙摆宽 - 顶宽) / 2` |
| `CircleNeckHalf(depth, width)`、`VNeckHalf(depth, width)` | 原生厘米；`width` 是完整领口宽，函数返回一半轮廓 | 当前短袖生成器将米乘 100，调用后再转回米并镜像 |
| `skirt.length`、`flare-skirt.length` | 腿长比例；完整裙组件还结合臀线深度求总长 | 不是米，也不是直接的最终裙长 |
| `pants.length` | 腿长比例 | `PantsHalf` 会乘人体 `_leg_length` |
| `rise` | 腰位插值比例，无量纲 | 在臀围／腰围及对应高度间插值 |
| `skirt.flare` | 单片每侧增加的长度，厘米 | 与 `pants.flare` 的倍率含义不同 |
| `pants.flare`、`pencil-skirt.flare` | 根据人体腿围／臀围计算下摆变化的无量纲系数 | 不能直接当成裤脚宽或裙摆宽 |
| `ruffle`、`level_ruffle`、`top_ruffle` | 褶量／接口长度比例，无量纲 | 需要网格与缝合支持对应的长度差；目前 Studio 简化版片链尚未验证该能力 |
| `flare-skirt.suns` | 展开圆量，1 表示一整圆的展开量 | 不是角度，也不是裙摆宽 |
| `sleeve_angle`、领口角度、`low_angle` | 角度参数，配置中使用度 | 曲线构造内部按需转换为弧度 |
| `waistband.width` | 相对臀线深度的比例 | 完整腰带构造时乘 `hips_line`，不是厘米值 |
| `n_panels`、`num_inserts`、`num_levels` | 数量，整数 | 影响版片数量或缝合结构，需要真实重新生成 |

其他参数的单位以调用处为准；相同名字在不同组件中不保证含义相同。人体围度与“单片平铺宽”也不是同一种测量，必须在适配层明确换算。

## 当前 ClothForge／Studio 接入情况

核对依据：[ClothForge 生成器](../../ClothForge/src/clothforge/generate.py)、[长裤配置](../../ClothForge/configs/trouser_styles_v1.json)、[短袖配置](../../ClothForge/configs/tshirt_styles_v1.json)、[演进记录](CLOTHING_EVOLUTION.md)。

| 当前能力 | 实际复用层级 | 尚未接入的上游能力 |
| --- | --- | --- |
| 八类基础库 | ClothForge 自建简化平片轮廓，使用 PyGarment 版片、边、接口与缝合描述 | 不是八种完整上游服装程序；毛巾／餐巾也是本地矩形版片 |
| 直筒／阔腿／收口长裤 | 本地裤片轮廓与真实网格再生成 | 未调用完整 `Pants`，没有其人体拟合、省道和裤口组件 |
| 圆领／V 领短袖 | 直接调用上游 `CircleNeckHalf`／`VNeckHalf`，采样后接回本地衣身 | 未调用完整 `Shirt`；前后领型相同；独立袖片与领部件未接入 |
| 半身裙基础库 | 本地双片梯形；已有裙长、腰部平铺宽、裙摆平铺宽 | 未调用 `SkirtPanel`／`Skirt2`；未开放款式预设与连续调参 UI |
| 其他上衣、外套与短裤 | 已有尺寸资产选择、PBR 预览和保存／工位入口 | 未接入对应完整衣身或裤子程序；没有原生门襟、扣件流程 |

上游生成缝合图样、ClothForge 生成可用网格、Newton 运行、Studio 预览与录制是几个不同步骤。上游有代码不等于本地网格适配与机器人任务已经验证。PBR 外观、物理材料配置继续由现有 Studio／ClothForge 流程提供。

## 推荐接入顺序

| 顺序 | 候选工作 | 复用方式与取舍 | 状态 |
| --- | --- | --- | --- |
| 1 | 直裙／A 字裙 | 复用 `SkirtPanel`；两款只改变裙摆展开，先无褶；开放裙长、腰部平铺宽、裙摆平铺宽 | G006 待讨论，未批准实现 |
| 2 | 方领短袖、前后领深分别调整 | 沿用现有领口部件接入方法；只扩展对应参数与采样 | 候选 |
| 3 | 长袖长度与袖口变化 | 简单轮廓调参可沿用现有衣身；独立 `Sleeve`／收口部件需要新缝合结构适配 | 候选 |
| 4 | 合体直裙、圆裙、多片裙 | 分别接 `PencilSkirt`、`SkirtCircle`、`SkirtManyPanels`；引入人体测量或明确的几何适配 | 候选 |
| 5 | 插片裙、分层裙、兜帽与连衣裙 | 增加版片数量、曲线及缝合拓扑，分项打通网格和正常运行流程 | 候选 |

第一项拟用 `ruffles=1`：直裙取 `flare=0`，A 字裙取正值。建议复用同一个部件而不是复制两套生成器。这里的直裙是桌面任务用的简化直轮廓双片裙；如果目标是穿着拟合，应另接包含臀部塑形与省道的 `PencilSkirt`。具体范围、尺寸上下限和验证命令需在 G006 批准前确定。

## 版本、许可与维护

- 固定版本的代码许可为 [MIT](../../ClothForge/third_party/GarmentCode/LICENSE)；复用时保留相应版权与许可声明。外部数据集、人体资产及材质另按各自许可处理。
- 本次只阅读源码与整理文档，没有运行全部上游组件，也没有更新依赖或上游版本。
- 本清单覆盖本地 `assets/garment_programs` 的服装组件、主要版片和辅助模块；不逐项罗列 PyGarment 全部底层 API。
- 将来更换上游提交时，重新核对组件、参数单位与本地适配；已批准工作与结果继续记录在 [衣物演进文档](CLOTHING_EVOLUTION.md)。
