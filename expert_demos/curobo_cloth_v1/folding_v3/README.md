# 第二批布料与衣物操作

已批准五项任务：展开对折布、毛巾单次对折、折好后 A→B 搬运、衣物整件翻面、衣物里外翻转。默认矩形任务使用 v002、衣物任务使用 v004；采用单 Franka、cuRobo、Genesis FEM / IPC 和已披露的局部夹持辅助。先整件翻面，再验证单袖和整件里外翻转。

v001 保留为初始候选及失败诊断：B 桌远角在低位抓取/放置时超出可达范围。v002 将 B 桌布料/衣物中心移到 [0.32, -0.18]，A 桌源中心移到 [-0.12, 0.27]；尺寸、材料和判定阈值不变。矩形任务执行前检查全部源/目标角的低位与圆弧高度姿态。通过可达性检查仍不等于任务成功。

搬运新增显式选择的 v003：保持 v002 场景参数，以开边两个相邻材料行的四个对应节点形成局部双层辅助夹持。默认仍是 v002。四节点最大直径4cm，接近前及重观察后检查，夹紧后各节点到实测 TCP 不超过3.2cm，底层3.5cm局部检查保留。候选按靠近开边中心排序，规划到当前/目标夹持质心；没有局部可达候选时停止。评价1.6检查层间对应、材料行相邻性、辅助轨迹与抓取事件一致性及独立重算的间距；原有途中7.5cm配对角间距、末态半幅面积/重叠/支撑/位置及安全门槛不变。这是比两节点更强的模拟辅助，不能作为真实接触抓取证据。首个新运行100653在6517步完成A桌折叠，但所有候选四点直径均超40mm（最小40.23mm，中心58.21mm），按计划在抓取前停止。未实际执行四点夹持与搬运，保形假设仍待检验。

衣物 v002 的源网格右袖口存在自交。v003 在 11 个局部顶点做三步 Jacobi 平滑，通过 IPC 初态检查，但留下 1.27 mm 短边，第一物理步触发拉伸停止。v004 将该边对称调整为 3 mm；面片、四个开口和材料参数不变。这是明确披露的参考资产修复，改变了源网格局部参考形状，不是执行过程中的衣物位置修正。独立桌面静置诊断 50 步的最大边长比为 1.028，完整机器人任务仍单独验收。

## 范围与来源

- 矩形布沿用 40 × 30 cm 的材料网格；折叠初态保持边长与平面参考形状。
- 衣物使用本地 DiffCloth 的 `tshirt1900-flattened.obj`：1921 顶点、3726 三角形、领口/衣摆/两袖口四个开口。缩放后的衣长 36 cm。保留源 OBJ、MIT 许可、材料索引与非平面参考几何。
- 里外翻转初态以参考衣物厚度方向镜像构造，保留材料方向和拓扑，初始边长不变。这是人为设置的起始状态，不是已经执行过的翻转动作。
- 正背片配色用于观察整件翻面。里外翻转由固定材料面片相对其对面的位置和方向判断；体积符号仅作为诊断。
- 毛巾使用合成外观，物理仍是已验证的 medium 合成 FEM 参数，尚未标定毛圈织物力学。
- 不使用 ClothTransformer 数据；其下载和后续项目不属于本次变更。

## 实验约定

所有 GPU 进程保持 `CUDA_VISIBLE_DEVICES=0,1`，同一张卡只运行本任务或第一批的一项重负载。旧运行、第一批源码和已登记证据不得覆盖。第二批共享入口改动只增加任务分派、拓扑入口、评价和登记元信息。

复用现有环境：Genesis `/data/zhanghejun/miniconda3/envs/genesis/bin/python`；cuRobo `/data/zhanghejun/SIMPLE/.venv/bin/python`；渲染 `/data/zhanghejun/isaacsim_6.0.1/python.sh`；登记使用 Studio `backend/.venv/bin/python`。不安装包。

从 Studio 项目根目录运行：

```bash
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover -s expert_demos/curobo_cloth_v1/folding_v3/tests -v
CUDA_VISIBLE_DEVICES=0,1 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B expert_demos/curobo_cloth_v1/folding_v3/pipeline.py --stage build
CUDA_VISIBLE_DEVICES=0,1 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -u expert_demos/curobo_cloth_v1/folding_v3/pipeline.py --stage run --task unfold_half --device 0
```

其他阶段为 `preflight`、`render`、`export`、`verify`、`publish`。`all` 执行仿真、渲染和导出；视觉通过必须在真实查看保存的帧后记录。每次物理试验使用新运行目录和源码快照。

## 判定

展开检查面积和材料宽度；对折检查半幅投影面积、两层交并比与角点对应；跨桌搬运单独检查 A 桌先折好、途中配对保持、B 桌释放后形状及距指定中心不超过8cm；整件翻面要求衣身和两袖分别翻面；里外翻转分别检查衣身和两袖。均保存终态释放后的保持段。自动指标不能替代实际视频检查。

单臂里外翻转先尝试局部抽袖，只有实际袖子指标通过才推进衣身；若整件被拖动而袖子未翻正，保留失败诊断，不伪报整件成功。若需要双臂或新夹具，则另行提出具体范围。

结果记录在 `data/expert_demos/curobo-cloth-v1/folding_v3/`，状态以 `evaluation.json`、录像、视觉检查与登记证据为准。所有结论为 `SELF_REVIEWED_PROVISIONAL`，不代表纯摩擦抓取或真机性能。

四节点局部对齐追加实验已批准：v003 在原有角点调整后，只允许一次局部配对节点对齐，再记录 fold_complete。若已有40mm内补丁，不增加动作；否则选择直径最小的相邻行补丁，调整其中更分离的一对上/下层材料点。沿用 align_pair 的抬升、重观察和放置，记录同一补丁调整前后直径，随后仍须通过全部折叠和抓取检查。旧变体不启用此回调。效果以新独立试验为准。

一次局部对齐实测：115922运行确实执行一次314→294，修正补丁直径40.27→25.59mm且折叠仍通过。随后选中邻接行13/14的34.07mm补丁，在接近下降期间扩大至43.80mm；闭爪后的最远TCP距离34.50mm超过32mm，未附着。重观察时45.22mm直径超过40mm，运行按限制停止。原始记录和诊断保留，四点保形仍未得到物理检验。
