# 横杆、收纳筐和覆盖任务

沿用原写实 L 形工作台与单 Franka，新增五类任务，各三个初态。cuRobo 规划机械臂路径，Genesis FEM / IPC 解算布料，夹爪使用已授权的局部辅助约束。释放后不将布料粘在横杆、筐或盒子上。

目录：

- `assets/sources/robot-cloth-scenes-v1/scenes/fixtures_v4/<task>/<variant>/`：冻结 USD、道具参数、初态来源和登记。
- `data/expert_demos/curobo-cloth-v1/fixtures_v4/tasks/<task>/<variant>/runs/<run-id>/`：每次独立运行，包含规划、物理轨迹、逐步指令、事件、来源快照、双视角视频、Episode 和证据包。
- 同批 `reports/` 保存检查与日志，`diagnostics/` 保存可达性探测，`index.html` 汇总视频和数据链接。

横杆长 44 cm、直径 3 cm、中心高 1.01 m；筐 34 × 28 × 12 cm；盒子 22 × 16 × 9 cm。它们是参数化合成道具。敞口筐的底板与四壁分别作为闭合实体导入，不对整个筐做会封住开口的凸包。

取下挂布和从筐取布先读取对应放置任务成功运行的末态，保存父轨迹哈希和时间步。该初态是位置相同、速度归零的独立新仿真，不宣称连续物理 checkpoint。材料参数未做真机标定。

用户已允许使用其他空闲 GPU，本批物理运行使用 `CUDA_VISIBLE_DEVICES=2,3`（内部 0 / 1 对应物理 2 / 3）或 `CUDA_VISIBLE_DEVICES=4` / `CUDA_VISIBLE_DEVICES=6`（内部 0 分别对应物理 4 / 6）。cuRobo 默认使用第一张可见卡；IPC 按内部设备分配。RTX 的 Vulkan 设备使用对应物理编号。单独使用 GPU 4、5 或 6 渲染时，分别设置 `CUDA_VISIBLE_DEVICES=4`、`CUDA_VISIBLE_DEVICES=5` 或 `CUDA_VISIBLE_DEVICES=6`、内部设备 0。旧批次 GPU 配置保持原约定。

从 `/data/zhanghejun/robot-data-studio` 运行，复用现有环境，不安装依赖：

```bash
CUDA_VISIBLE_DEVICES=2,3 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover -s expert_demos/curobo_cloth_v1/fixtures_v4/tests -v
CUDA_VISIBLE_DEVICES=2,3 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B expert_demos/curobo_cloth_v1/fixtures_v4/pipeline.py --stage build --task hang_on_rod --task place_in_basket --task cover_box
CUDA_VISIBLE_DEVICES=2,3 PYTHONDONTWRITEBYTECODE=1 /data/zhanghejun/miniconda3/envs/genesis/bin/python -B -u expert_demos/curobo_cloth_v1/fixtures_v4/pipeline.py --stage run --task hang_on_rod --device 0
```

其他阶段：preflight、render、export、verify、publish。all 执行物理运行、渲染和导出；实际看过保存的帧后才填写视觉检查。每次失败保留原始诊断，重跑创建新目录，不修改已发布证据。一个放置任务成功后才能构建对应取布初态。

每条完整示范提供主视角 5 Hz、俯视角 2 Hz 和保留全部源帧的四倍速总览；物理指令 100 Hz，状态快照约 50 Hz。视频只回放保存的关节和布料顶点，法线平滑不改变运动。每条视觉检查记录实际看过的代表帧及局限。

验收着重完整动作、释放后的可见效果与数据可追溯性，允许残余褶皱；不声称纯接触抓取、真机成功率或训练 QA 自动接受。结果标记为 `scripted_assisted_simulation`、`SELF_REVIEWED_PROVISIONAL`。

追溯范围：运行保存任务源码、场景、轨迹、图像和命令哈希，以及所查询的环境版本与 GPU 映射。没有提供完整的引擎安装目录快照。首两条已冻结示范的 README 中“引擎文件哈希”是说明文字错误，应按本段理解；冻结证据和数据不改写。

多 GPU 渲染通过 `pipeline.render_queue(device)` 按整条运行获取文件锁，包含两视角和导出，防止两个工作进程写入同一示范。当前先完成的媒体仍须实际视觉检查和最终核验才登记。

取布任务按“回到接收台面并展开”检查：台面附近节点比例至少 88%、投影展开面积至少 72%，至少实际调整两个布角，并在松手后保持。中心偏差继续记录，但用户没有要求对齐中心或标线，因此不作为这两个取布任务的失败条件；其他对齐任务不变。首条筐中取布曾仅因中心偏差约 10 cm 被拒，原评价和原评价源码已保留，重评不改写轨迹或图像。最终仍须实际检查双视角图像。

覆盖任务保留低位跨桌搬运；放下后先调整盒外两处布边，每次向外移动 2 cm，避免把立体覆盖强拉成平铺矩形。前一次大幅拉角导致覆盖率下降的轨迹保留为诊断。取杆上布的初态若原候选角点不可达，会在实际观测的布料边界中按高度继续探测，优先使用保存的可达抓取点，不改碰撞体。

取布拉角使用贴台拖拽：夹持后仅抬高 3 mm，TCP 最低保持桌面上方 23 mm。每次重新观察布角；若前四次仍未展开，最多再复查两次。接收台上的接近高度按当地台面与道具距离选择，cuRobo 始终使用完整原场景碰撞体。该策略用于新增重跑，历史运行的冻结代码和评价不变。

展开位置预检：第三初态的名义最外角 (.54,-.515) 在低位被真实cuRobo拒绝。新增运行会先检查四角的接近、拖拽和释放高度；若原矩形不可达，则检查向内平移 (-.02,+.015) m 的矩形，仍须完全处于接收台面区域。名义目标、实际目标、全部未执行探测及选择原因保存在 spread_target_probes / spread_target_selection 事件和 plans/ 中。原场景配置不覆写，且这两个取布任务不要求对齐中心。

覆盖第三初态补充：原运行落布后横向偏心约2cm，四次向外整理将盒顶覆盖从84.1%逐步降至67.7%，保留为诊断。cover_box.py 新增松手前按真实布料重心做最多3cm的横向夹爪修正，实际候选向左1.76cm已通过cuRobo；随后固定执行两次短幅布边整理，避免额外两次继续带偏。只移动夹爪，不改布料节点或物理参数；失败门槛不变。移除该文件不再使用的measure/satisfactory导入，新版10项测试通过，独立物理重跑验证效果。

GPU补充：检测到GPU1空闲后，runner.py与pipeline.py为fixtures_v4增加显式CUDA_VISIBLE_DEVICES=1（内部0→物理1）；环境映射和CUDA运算见reports/environment_gpu1.json。刚启动的GPU6覆盖重跑正常中断、保留记录，再从原初态在GPU1重新执行，减少争用。不改其他批次的0,1约定、不修改其他用户进程；28项既有回归检查再次通过。

待后续重跑使用的初始抓取修正：retrieve_from_rod.py 从实际布料拓扑提取边界，先按当前高度探测上方边点，借鉴已完成第三变体；原抓取种子仍保留在候选中。retrieve_from_basket.py 先按高度探测四个材料角，再探测边中点。真实预检中横杆v001节点13、v002节点328，以及筐中v002/v003节点315的悬停和抓取均可达，其余被拒候选保留。候选顺序与每次规划结果进入事件记录；不改道具碰撞体、物理参数或正在执行的冻结轨迹。此修改先作语法和实际位姿预检，完整效果须由新的独立运行验证。
