# 写实机器人布料场景 v1

依据 YEAR1_MILESTONES.md（M1/M2）与 NEWTON_INTEGRATION.md 第 5 节补充资产：
12 个布料任务布置、3 个刚体对照，归为实验室、裁片工位与家居三类环境。

## 使用入口
在 Studio“资产与材料”中切换到“资产索引”，搜索 robot-cloth-scenes-v1 或 rcloth。
SCN 为场景与预览，MDL 为资源，CFG 为固定静态配置。
MDL-rcloth-complete-pack 提供完整 ZIP；保留目录结构解压后，在 Isaac 打开 scenes/<id>/scene.usda。
USD 引用与贴图是相对路径，OmniPBR.mdl 由 Isaac 运行环境提供。
资源目录：/data/zhanghejun/robot-data-studio/assets/sources/robot-cloth-scenes-v1。
目录中的 index.html 是图库；Studio 场景详情页展示全景，并提供细节图下载。

## 机器人来源
- Franka Panda：复用 simulation-demos/franka-dual-cloth-isaac/assets/franka 的原生 USD。
- G1 + Wuji：复用 simulation-demos/humanoid-cloth-flatten/assets 的原生 USD；原来源与哈希保留在 sources.json。
- Sharpa：官方 sharpa-robotics/sharpa-urdf-usd-xml，固定提交 0d19cac602f46456b819e4b6a2c09a74982c9a3e。
  使用右手 flange USD 及依赖；逐文件验证 Git blob SHA-1，记录 SHA-256。随包保留 Apache-2.0 的 LICENSE.txt 与 NOTICE.txt。
- 工位、织物几何、织纹、木纹和标牌由本批程序生成。
已有本地机器人资源保留原来源，不据此声称获得新的对外再分发许可。

Sharpa 在裁片工位上作为独立法兰夹具安装的灵巧手展示，与 Franka 同处工位。
本批没有经过工程核验的 Franka–Sharpa 转接法兰，不能称为已装配并验证的机械臂末端。
Wuji 出现在原有 G1 双手模型中。

## 场景
corner_lift：布角抬升与释放；edge_pick：桌沿取布；cloth_transfer：单臂布料搬运；
panel_alignment：裁片边缘对齐；table_smoothing：台面铺布与抚平；feed_registration：裁片送料定位；
bimanual_unfold：双 Franka 展布实验台；bimanual_tension：双点张紧；
towel_fold：毛巾折叠；layer_separation：多层单片分离；dexterous_edge：Sharpa 捏边；
g1_laundry：G1 + Wuji 整理；cube_lift、tray_place、object_sort：三个刚体对照。
这是三类环境中的 15 个任务布置，不是 15 套独立建筑。
送料装置是参数化原型，不是实际贴袋机 CAD 数字孪生。

## 写实与物理边界
- 米制，Z 向上；原模型关节坐标、限位和碰撞资源保留。
- 使用关节树正向运动学生成静态姿态。合法角度范围不含零时，在范围内明确选择中立角度并记录。
- 桌面与指定工装含静态碰撞；布料为带包边和背面的静态造型网格。
- 棉布、牛仔、毛巾、亚麻指合成外观，未做实物材料标定。
- 褶皱由程序构造，没有推进布料物理或执行操作回放。
- 未验证动态抓取、全面机器人碰撞、可达性、真机标定或训练能力。
- 静态检查覆盖依赖、SI 单位、网格拓扑、合法关节角度和布料顶点进入桌面的筛查。
- 配置 runnable=false，不自动增加 Collector 白名单，也不声称 Episode 采集闭环已接通。
- 渲染使用 Isaac RTX PathTracing、64 spp、6 次反弹、1440×1080，不推进仿真时间。
审阅状态：SELF_REVIEWED_PROVISIONAL。

## 文件职责与变更
build_scenes.py：从任务规格生成环境、布料、合法机器人姿态、相机和 USD。
render_scenes.py：加载 USD，输出全景、细节等视角和渲染报告。
validate_scenes.py：重开 USD，检查资源、网格、关节限位、布料桌面关系。
prepare_registry.py：解析完整依赖，生成 ZIP、图库和带冻结指纹的登记清单。
robot_scene_importer.py：全量预检哈希与引用，再按依赖顺序通过 AssetRegistry 发布。
asset_cli.py：增加新来源的导入分支；原有分支保留。
config/asset_sources.json：仅增加 robot-cloth-scenes-v1 来源。
test_robot_scene_import.py：测试幂等、无写入预检、篡改拒绝、用户新版本保护和依赖约束。
没有删除旧业务代码。行为由“无此批场景”变为“Studio 可查询预览且可下载本批静态资产”。
导入逐条原子发布；不是整批数据库事务。旧版本不覆盖，同编号内容冲突时报错。

## 命令与复现
在 Studio 根目录，使用现有 backend/.venv，不安装依赖：
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:packages/robot-data-contracts/src backend/.venv/bin/python -B -m robot_data_studio.asset_cli import --source robot-cloth-scenes-v1 --dry-run
同命令去掉 --dry-run 执行登记。

首次构建在新来源目录执行：
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B build_scenes.py --scenes all
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B validate_scenes.py
/data/zhanghejun/isaacsim_6.0.1/python.sh render_scenes.py --scenes all --views hero,detail --gpu 0
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B prepare_registry.py

冻结登记后不要直接重建原目录，否则原文件指纹失效。
继续迭代使用新来源目录和显式新版本。
实际渲染日志、静态校验与各场景报告保留；最终汇总位于 data/verification/robot-cloth-scenes-v1/final_report.json。

