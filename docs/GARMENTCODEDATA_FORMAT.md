# GarmentCodeData v2 格式核对与阶段 1 结果

核对日期：2026-10-12。关联 G007 阶段 1，已验证。范围：第一批次中性人体包、配套元数据与 12 件样本。阶段 1 不修改导入器或 UI，不运行仿真；“格式可读取”不代表“已可在 Newton 中运行”。

## 获取来源与保存位置

官方发布：[v2 记录](https://www.research-collection.ethz.ch/items/9d16a4da-0d30-4963-8842-af20fcf82899)、[官方文件共享](https://libdrive.ethz.ch/index.php/s/4UtC8smtLOGwKoZ)。许可记录为 CC BY 4.0。官方发布元数据标注整套 368 GB；本次只取第一个中性人体包，不获取全量或随机人体包。

本地根目录：`/data/zhanghejun/datasets/GarmentCodeData/v2/phase1/`。

| 下载内容 | 字节数 |
| --- | ---: |
| 第一批次 `default_body/data.tar.gz` | 5,121,727,032 |
| `dataset_properties_default_body.yaml` | 1,798,982 |
| `Dataset_documentation_v2.pdf` | 605,885 |
| `neutral_body/mean_all.obj` | 1,940,521 |
| `neutral_body/mean_all.yaml` | 609 |
| `GarmentCodeData_v2_official_train_valid_test_data_split.json` | 6,074,953 |

6 个文件均已完整下载，字节数与官方目录清单一致，总计 5,132,147,982 字节。完整下载结果、来源 URL、文件大小和本地 SHA256 见 [downloads.json](../../datasets/GarmentCodeData/v2/phase1/downloads.json)。SHA256 用于后续本地追溯，不冒充已与官方公布的哈希比较。

12 件样本共 156 个文件，合计 23,405,419 字节；没有解压整批。样本提取自下载流已经到达的包前部，检查结果先于整包下载结束生成；整包仍单独核对长度并计算 SHA256。

## 批次和样本身份

```text
GarmentCodeData_v2/
└─ garments_5000_0/
   ├─ default_body/
   │  ├─ data.tar.gz
   │  └─ dataset_properties_default_body.yaml
   └─ random_body/              本轮未下载
```

官方文档描述两个人体分组中的同名样本对应同一设计。此关系本轮由官方说明确认，没有下载配对随机人体样本做逐件比较。目录、批次、人体分组和样本 ID 应共同进入来源身份，不能只用 `rand_*` 文件名作为全局唯一 ID。

批次 YAML 包含 `design_file`、`body_default`、`body_samples`、`size`、`name`、`generator`、`sim`、`render` 等字段。`generator.stats.garment_types` 提供 `main` 类别与 `styles` 标签；`panel_count` 提供版片数量；`sim.stats.fails` 保存历史失败原因。

该批次的请求生成数 `size` 为 5000，而分类元数据有 5001 个条目。两者不是压缩包实际可用样本数；本轮只核对提取的 12 件，不把元数据长度当作可用目录数量。历史失败统计也可能相互重叠，不能直接相加当失败样本总数。

官方划分文件使用 `test`、`training`、`validation` 三个数组，成员是 `批次/人体分组/样本ID`。本轮 9 件出现在 `training`，3 件不在该划分清单；未列出者保留空划分，不自行补成训练集。

## 一件样本的实际文件

每件提取样本均包含下列 13 个文件：

| 文件后缀 | 格式／内容 | 后续用途 |
| --- | --- | --- |
| `_specification.json` | 版片、边界曲线、放置变换、缝合关系与单位 | 版片来源、拓扑与物理网格重建依据 |
| `_design_params.yaml` | 完整设计参数，包括组件选择 | 类别属性与后续重新生成 |
| `_body_measurements.yaml` | 人体测量 | 保留适配来源；不是衣物平铺尺寸 |
| `_boxmesh.ply` | 初始组装网格，二进制 little-endian | 初始姿态与视觉几何 |
| `_sim.ply` | 模拟后穿着网格，二进制 little-endian | 穿着外观预览 |
| `_orig_lens.pickle` | 原模拟顶点编号对应的部分静止边长 | 缝合附近材料度量修正，不能直接套 PLY 编号 |
| `_sim_segmentation.txt` | 原模拟顶点的分区／缝合标签 | 重建映射后使用 |
| `_vertex_labels.yaml` | 原模拟顶点的具名标签 | 腰口、领口等部位信息，需恢复编号映射 |
| `_pattern.svg`、`_pattern.png` | 版片可视化 | 调试与来源查看 |
| `_render_front.png`、`_render_back.png` | 前后渲染图 | 原始缩略图与参考 |
| `_texture.png` | UV 图样纹理 | 原始外观参考；不等同于现有完整 PBR 织物包 |

前缀均为样本 ID。全路径、大小与 SHA256 见 [sample_inventory.json](../../datasets/GarmentCodeData/v2/phase1/sample_inventory.json)。没有在这 12 件内发现 OBJ、MTL、GLB 或现有 ClothForge `mesh.npz`；此结论不外推为所有发布样本都只有这些格式。

## JSON、单位与坐标

`specification.json` 顶层：`pattern`、`parameters`、`parameter_order`、`properties`。

`pattern` 包含 `panels`、`stitches`、`panel_order`。每个 panel 有局部二维 `vertices`、`edges`、三维 `translation`／`rotation`，并可包含部位 `label`。边引用 `endpoints`，曲边通过 `curvature.type` 与 `params` 描述圆弧、二次／三次曲线。缝合是版片边的成对引用，例如：

```json
[
  {"panel": "wb_front", "edge": 6},
  {"panel": "wb_back", "edge": 0}
]
```

12 件均声明 `properties.units_in_meter = 100`，即版片和衣物坐标以厘米为单位；`curvature_coords = relative`。不能把曲线相对参数按绝对长度统一缩放。

衣物网格使用 Y-up。中性人体 OBJ 的 Y 范围为 0～1.7199014649，人体 YAML 身高为 171.99；人体 OBJ 是米制，而衣物 PLY／测量 YAML 是厘米制。上游 [garment.py](../../ClothForge/third_party/GarmentCode/pygarment/meshgen/garment.py) 同样使用衣物 `c_scale=1` 与人体 `b_scale=100`。

转换到当前 Z-up、米制时，可明确采用右手旋转 `(x,y,z) → (x,-z,y)`，再将厘米长度除以 100。该变换是后续适配建议，本轮未输出转换网格。人体 OBJ 不应再除以 100；角度、比例与物理参数也不能按长度统一缩放。

## PLY 的 UV 与模拟拓扑不同

两种 PLY 均含顶点坐标 `x/y/z` 与 UV `s/t`，面含 `vertex_indices`。12 件都能读出 UV，均为有限数值；每件的 boxmesh 与 sim 顶点数、面顺序完全一致，可对应观察初始与最终外形。

但这是可渲染网格：UV 接缝会拆分顶点。以 `rand_05H6WP8PJX` 为例：

- PLY 有 11,840 个顶点、22,043 个三角形。
- 初始网格只有 11,161 个不同的三维坐标；分区 TXT 恰好有 11,161 行。
- 679 个重复位置用于不同 UV，不能直接当作独立模拟粒子。
- 12 件均观察到“去重后的初始位置数 = 分区行数”，但这不证明原始编号可由任意去重排序恢复。

上游 [optimize_garment_storage](../../ClothForge/third_party/GarmentCode/pygarment/meshgen/simulation.py) 通过 Trimesh 将 OBJ 转为 PLY，并移除大纹理和 MTL；OBJ 的几何／UV 索引在转换时不再以原文件结构保留。后续需明确区分视觉顶点、模拟顶点与逐角 UV，恢复缝合和标签映射。

仅按当前 PLY 顶点序号套 segmentation、vertex labels 或 orig_lens 已在样本上证实不成立。只看相同位置也不能保证恢复原顶点编号和缝合身份；未经映射证明，不应直接注册为可模拟资产。

## 静止信息能否直接使用

`orig_lens.pickle` 不是全部三角形边长表。上游 [BoxMesh.finalise_mesh](../../ClothForge/third_party/GarmentCode/pygarment/meshgen/boxmeshgen.py) 只对接触缝合顶点的三角形调用 `_store_to_orig_lens`；普通版片内部的度量来自原始平面版片。字典键为原模拟顶点对，值为相应静止长度。

直接用 PLY 面编号查询该字典，12 件均缺失大量边。这同时涉及“字典本身是稀疏修正表”和“原编号与视觉编号不一致”，不能将缺失项补成穿着形状边长，也不能把 boxmesh 的缝合附近几何当成无应力状态。

本轮没有恢复每个三角形的完整静止度量，相关报告字段为未重建；没有据缺失数据宣称静止三角形通过。检查明细见 [sample_summary.json](../../datasets/GarmentCodeData/v2/phase1/sample_summary.json)。

后续建议：先复用上游版片／网格生成逻辑取得原模拟拓扑、版片度量和缝合修正，再确定与现有 PLY 的对应关系；如无法恢复完整旧编号，生成新的物理网格并记录其来源，原始 PLY 保留为视觉参考。新物理网格不能冒充原始模拟网格。

Newton VBD 当前 [newton_worker.py](../../ClothForge/src/clothforge/newton_worker.py) 已支持按 `rest_triangles` 覆盖材料度量，因此不必将衣物全局压平。但挂点依赖现有简化尺寸参数，外部衣物需单独适配。Newton XPBD／其他部分适配还使用 [comparison.initial_state](../../ClothForge/src/clothforge/comparison.py) 的全局平面假设，不能把 VBD 可接入的结论自动推广到所有引擎。

## 12 件固定试导入清单

样本按批次分类元数据选取，避开其已记录的历史失败项；这只是样本选择依据，不是新的物理验证。以下顶点数均为视觉 PLY 顶点数。

| 样本 ID | 类别 | 上游款式标签 | 版片 | PLY 顶点 | 三角形 | 官方划分 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `rand_05H6WP8PJX` | `upper_garment` | with_sleeves, long_sleeve | 10 | 11840 | 22043 | training |
| `rand_05V1M7JE75` | `upper_garment` | sleeveless | 8 | 4753 | 8592 | training |
| `rand_07SXFM3OXA` | `upper_garment` | sleeveless | 4 | 2378 | 4200 | 未列出 |
| `rand_09WQLJ3QED` | `upper_garment` | asymmetric_top, with_sleeves, long_sleeve | 10 | 6758 | 12283 | training |
| `rand_033UAN6C0K` | `pants` | maxi | 12 | 14970 | 28212 | training |
| `rand_0BC49T2K2O` | `pants` | midi | 6 | 10932 | 20702 | training |
| `rand_0CD8GFOYI4` | `pants` | midi | 10 | 12224 | 23026 | training |
| `rand_04IMMO8WDD` | `skirt` | knee_len | 10 | 10899 | 19844 | training |
| `rand_07JYAR0G1P` | `skirt` | mini | 14 | 952 | 1470 | training |
| `rand_07LSZ9ASL3` | `skirt` | maxi | 4 | 10992 | 21116 | training |
| `rand_00YONAPXZE` | `dress` | hoodie, with_sleeves, short_sleeve, midi | 18 | 29784 | 57130 | 未列出 |
| `rand_07EKIQJMNA` | `jumpsuit` | with_sleeves, short_sleeve, maxi | 16 | 21247 | 40194 | 未列出 |

类别分布：上衣 4、裤子 3、裙子 3、连衣裙 1、连体服 1。网格范围为 952～29,784 顶点、1,470～57,130 三角形。包含无袖、长袖、非对称上衣、短／长裙、帽式连衣裙和连体服。

批次概览及材料原值见 [batch_summary.json](../../datasets/GarmentCodeData/v2/phase1/batch_summary.json)。上游材料数值依赖其模拟单位与能量模型；不能直接复制为本地面密度、拉伸／弯曲参数，也不能宣称已对应真实织物。

## 阶段 2 的实际转换结果

2026-10-12 按单独批准范围执行。调用上游 `BoxMesh` 重建共享模拟顶点与原生缝合编号，版片内部边长配合重新生成的 `orig_lens` 修正构成完整 `rest_triangles`；UV 单独保存为 `face_uv`，不把材料度量当成纹理坐标。最终采用原始 1 cm 分辨率。

初始 BoxMesh 仍是待收拢的组装姿态，裙子诊断最大拉伸约 11.23，不能直接用于操作。本轮通过原始 boxmesh 表面上的最近点和重心坐标，把已发布 sim 姿态传递到新网格；姿态映射误差写入 manifest，静止形状仍来自版片，不使用 sim 形状替代。

12 件最终尝试中 8 件生成成功，4 件在姿态映射后产生退化三角形，未注册。这 4 件的原始 sim PLY 均未检出同阈值下的退化三角形，故失败归于重建／映射问题，不能归咎于源衣物本身。3.5 cm 首轮还暴露上游短边警告访问未定义 `Edge.name` 的错误；改用原始分辨率后该错误消失。首轮与后续报告均保留，没有删除版片、放宽门槛或修改上游源码。

选定三件链路调试样本：上衣 `rand_07SXFM3OXA`、裤子 `rand_0BC49T2K2O`、裙子 `rand_07JYAR0G1P`。该选择用于少量链路调试，不是随机抽样或总体通过率评估。三件分别注册一个模型与三种已有合成材料配置；人体测量和来源标签仍保留，未开放上游款式编辑。

| 样本 | Newton 运行 | 全程物理检查 | 原因／关键指标 |
| --- | --- | --- | --- |
| 上衣 | 完成，61 帧 | 失败 | 初始最大拉伸 1.209，超过 1.15；末帧降至 1.036，不能抹去起始失败 |
| 裤子 | 完成，61 帧 | 失败 | 初始最大拉伸 1.979，面积比 0.300～1.862；末帧最大拉伸 1.155 |
| 裙子 | 完成，61 帧 | 通过 | 全程最大拉伸 1.045，无保存帧自交或地面穿透 |

三类的 PBR 预览、Fabric 031 材质切换、保存副本和工位配置跳转均通过。只验证配置传递，没有启动 Isaac 工位 worker、录制图像或机器人任务；不能把浏览器预览视为工位渲染验证。导入衣物显示的是外形包围盒高／宽，不能当成人体尺寸或平铺尺寸。

产物根目录：`/data/zhanghejun/datasets/GarmentCodeData/v2/phase2/native-v2/`。证据：[转换报告](../../datasets/GarmentCodeData/v2/phase2/native-v2/conversion_report.json)、[注册结果](../../datasets/GarmentCodeData/v2/phase2/native-v2/import_result.json)、[浏览器结果](../../datasets/GarmentCodeData/v2/phase2/native-v2/browser_result.json)、[Newton 指标](../../datasets/GarmentCodeData/v2/phase2/native-v2/physics_summary.json)、[完整运行记录](../../datasets/GarmentCodeData/v2/phase2/native-v2/newton_runs.json)。三张预览：[上衣](../../datasets/GarmentCodeData/v2/phase2/native-v2/preview-tshirt.png)、[裤子](../../datasets/GarmentCodeData/v2/phase2/native-v2/preview-trousers.png)、[裙子](../../datasets/GarmentCodeData/v2/phase2/native-v2/preview-skirt.png)。

## 阶段 1 后提出的适配事项（历史快照）

| 内容 | 当前结论 | 下一动作 |
| --- | --- | --- |
| 原始几何与 UV 预览 | 12 件可读取，UV 完整，初始／最终拓扑一致 | 保留视觉拓扑及 UV，应用现有 PBR 材质 |
| 类别与款式 | YAML 已提供标签，不必靠名称推断 | 保留原类别；明确上衣、裙子、连衣裙、连体服映射 |
| 身份与划分 | 批次／人体组／样本身份可明确；3 件未列入官方划分 | 不编造划分，不把不同人体版本合并成同一资产 |
| 静止形状与缝合 | 有来源依据，但不能直接用 PLY 编号连接 | 先解决模拟拓扑与材料度量重建，再注册可模拟状态 |
| 工位运行与挂点 | 本轮未运行，现有挂点仍按简化平铺尺寸选取 | 明确姿态、部位标签／挂点及本地材料配置 |
| 全量导入 | 尚未下载或索引全量 | 少量转换通过后再评估空间、索引和批次 |

## 执行与证据

- 下载与文件清单：`/tmp/garmentcodedata-stage1.py`，标准库网络与 SHA256；目标路径限定为 phase1。
- 样本解析：现有 `/data/zhanghejun/ClothForge/.venv-generation/bin/python`，使用已有 NumPy、PyYAML 和 Trimesh，不安装依赖。
- 156 个样本文件的大小与 SHA256 已复核；12 件 UV 均为有限值。检查环境与范围见 [inspection.json](../../datasets/GarmentCodeData/v2/phase1/inspection.json)。样本报告保留原始类别、版片数、单位、UV、初始／最终拓扑与原编号不兼容结果。
- 本阶段只解析和记录，不生成运行资产、注册模型、迁移数据库、修改应用代码或跑物理仿真。
- 后续执行范围仍以 [导入计划](GARMENTCODEDATA_IMPORT_PLAN.md) 和 [演进记录](CLOTHING_EVOLUTION.md) 的批准记录为准。
