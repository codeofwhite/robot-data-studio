# franka-5090 双 GELLO 仿真采集与上机指南

状态：代码与部署准备完成；目标机尚未安装 Studio/Isaac、尚未接通两套实物 GELLO，实际延迟与夹布效果待上机确认。SELF_REVIEWED_PROVISIONAL。

## 1. 目标机与边界

Codex 项目 franka-5090 对应 SSH 别名 server-245，主机名 lab。2026-10-19 只读检查：RTX5090 32GB，驱动580.126.18，内存60GiB、约51GiB可用，用户所在磁盘约760GiB可用。Node24.21.0在 ~/.local/bin，非交互SSH的PATH需显式加入该目录；Python3.12.3，ROS2 Jazzy。

目标机已有 /home/share/Franka-Controller，包含 GELLO 输入代码及真机动作发布。这轮不修改、不启动它。它的真实机械臂、夹爪、回零与VLA命令不属于仿真采集入口。

当前只发现一个FTDI。第二套由操作者插入，左右身份由操作者分别选择，不能按 ttyUSB 编号自动猜测。当前 zhanghejun 账号没有串口读写权限，FTDI latency_timer=16ms；权限与硬件参数调整另行批准，不在本轮执行。

## 2. 接线与第一次操作

网页创建会话时选择双臂场景的“双 GELLO”（左右各一套USB）；新双腕配置以960×720提交。相同场景也可选择Keyboard，控制方式在启动时确定，不能在运行中直接混发两类命令。

两套USB接在打开Collector的那台电脑上，使用桌面Chrome/Edge访问localhost转发地址；USB输入由该浏览器读取，而不是由远端仿真服务器自动扫描。两侧分别设置主臂零位、对应机器人起始姿态、夹爪开闭端点和关节方向，然后启用控制；任一侧缺少校准时不启用。

这是纯仿真流程：需要的是两套 GELLO 的USB输入，不需要启动真实FR3控制服务。GELLO的编码器、转接器供电方式以实验室实际硬件说明为准；不要把不确定的电源口、总线口当作USB口。附件教程主要讲软件和时序，没有足够的实物接线图，实际接线仍需现场确认。

1. 在自己的实验室桌面会话中打开终端和 Chrome/Edge；SSH部署终端不等于本机图形桌面。
2. 先插第一套USB，运行 `ls -l /dev/serial/by-id` 记下标识；再插第二套，确认新增标识。手动记好左右对应，不写入版本库。
3. Studio启动仿真前确认GPU空闲，选择双臂v17、“双 GELLO”、PhysX及FR3双腕相机配置；部署配置通过环境变量指定FR3资产及本机显示。尚未部署前本步骤不可执行。
4. Collector点击“Connect LEFT GELLO”，选择左USB；“Connect right USB”选择右USB。两路维持原57600 baud /20Hz轮询，无EEPROM写入。
5. 保持控制关闭。左右主臂各放到舒适的起始姿态，分别Capture arm home / Capture right robot home。零位对应各自当前仿真姿态，不强制使用同一个Panda默认姿态。
6. 左右分别采集夹爪完全张开和闭合端点。先小幅移动各关节，核对方向；有反向时关闭控制，再调整对应J1–J7的±方向。不要一次大幅移动。
7. 两路校准完成后Enable control。看本机Isaac窗口操作，浏览器控制窗口保持可见；后台标签或被遮挡的窗口可能触发浏览器定时器节流。若输入停更，超时后两臂目标共同保持，夹爪保持原命令。
8. 填写任务指令，Start Recording；完成后Success/Failure保存；不熟练的试操作不自动认定为成功示范。先回放第一条完整视频，再采5–10条种子。
9. 结束时先关闭Enable control，再停止录制、断开左右USB连接并用Studio停止本次worker。只关闭本次会话，不结束其他进程。

现场遇到串口不可访问、未发现第二USB或看不到仿真窗口，先记录现象并停在该步；这些条件尚未在实物上验证。

## 3. 控制、数据与低延时

路径：两套USB → 本机浏览器各自的GelloSerialReader → localhost WebSocket → 两个关节目标控制器 → 同一个仿真步。Studio后端管理生命周期，不转发关节控制包。控制不绕经训练服务器；画面优先本机Isaac窗口，不等待WebRTC。

GelloCommandV1保持单臂七关节+二值夹爪，新增可选arm=left/right；双臂入口必须显式指定arm。浏览器使用同一个session和全局递增sequence，服务端只允许一个操作者控制两侧，再将命令路由到各自控制器。单臂消息不要求arm，单臂入口拒绝带arm的消息。新双臂客户端需要本轮服务端，不能连接旧版服务端。

限位、速度限制、序列检查与接收时钟看门狗继续生效；一侧过期时另一侧也保持，不用反复发送缓存读数伪装新输入。浏览器发送缓冲积压时关闭控制，避免排队重放旧动作。默认看门狗窗口沿用0.3s，不等于立即急停或真实机器人安全保证。

FR3选项显式使用fr3_joint1..7、fr3_finger_joint1/2、fr3_hand及指定FR3 USD；Panda仍走原路径，不按文件名猜模型。FR3首轮仅开放PhysX双臂v17；没有修改USD碰撞或材料。仿真驱动沿用原High-PD配置，执行器关节表达式映射至FR3，尚未证明与真机动力学一致。

录制沿用Canonical Episode：原生18维双臂关节/双指目标，写入器转换为既有16维训练动作；原生36维实测关节位置/速度由既有适配器转换为32维policy_state。FR3记录显式使用robot_id=franka_fr3_dual和dual_fr3_joint16_physical动作配置，字段名保留fr3，不冒充Panda。operator_action为左右各7关节+1二值夹爪，共16维。不要把夹爪命令0/1与实测米制总宽度相减或互换。保留requested/safe/applied动作区别。

双GELLO附加数组：dual_control_sequence、dual_control_source_timestamp_ns、dual_control_receive_timestamp_ns（均按left/right顺序），dual_coupled_hold、两侧末端姿态；PhysX布料帧附带cloth_particles与cloth_particle_velocities。节点状态不是完整可恢复的求解器检查点；尚未实现SoftMimicGen种子导入。dual_active_arm=-1表示两臂同时操作，不表示切换键盘主力臂。

FR3部署新增独立相机配置 `isaac_fr3_dual_wrist_v1`，960×720，录制频率沿用10Hz。预览四路：主视角、俯视、真实左腕、真实右腕；保存仅三路 `main / left_wrist / right_wrist`。预览线协议继续使用base/top/side/wrist四个ID，映射关系保存在recording_camera_map，side/wrist在本配置中分别是真实左右腕，不再是外部斜视图；旧v4/v5行为保持。原生Isaac窗口仍可自由观察。

Top辅助预览采用接近之前LeHome／FR3的高位斜俯视：eye_world_m=(.55,.37,2.02)，target_world_m=(.55,-.06,.78)，垂直FOV45°；替换原约3m高、FOV52°的近垂直全桌视角，目的是让衣物操作区占更多画面。只调整Top，主视角与双腕以及三路保存映射不变。实际截图需由操作者确认。

新配置把相机挂在实际左右机器人prim的fr3_hand下，ROS相机约定，位置(.08,0,.02)m，局部旋转xyzw=(0,-.229753,0,.973249)。该挂载来自已有LeHome FR3参数并显式从wxyz转换；当前IsaacLab OffsetCfg使用xyzw。标定元数据记录保存流名称、K、prim路径和动态父坐标局部位姿，不能把腕相机局部外参解释为固定世界外参。该配置仍是nominal_pending_intrinsics，尚未运行GPU确认遮挡、视野或手部跟随。

Studio在FR3部署的双臂v17页面默认选择新相机配置，并选用已存在的MAT-ambientcg-marble006 v1三贴图大理石台面外观；保持v17工作台几何、碰撞和双臂布局。此处是现有工作台的大理石外观，不代表已核实与实验室某张石台尺寸一致。启动配置显式携带材质ID/版本，资产闭包需包含该材质三张贴图，不能只复制材料目录。旧场景和已有会话不自动改写。

Canonical Episode仍为原始数据；未来LeRobot导出可对应observation.images.main/left_wrist/right_wrist。此次未导出LeRobot，也未训练。

先测量再调参：

- 真实新USB样本频率、每侧source/receive时间和控制tick时间分别记录；不把重复目标计为新USB采样。
- 网页显示每侧接收到控制tick的p50/p95，使用服务端单调时钟。它不包含USB读取前延迟、图像渲染或显示器延迟，不能称为端到端延迟。
- 端到端输入到画面需现场测量；不同进程/浏览器的时钟未校准前不直接相减。来源时间与接收时间分开保存。
- 当前57600 baud、20Hz轮询和16ms FTDI配置先保持不动。更高波特率、latency_timer和滤波调整须有独立明确范围；不能只提高发送频率后宣称延迟下降。
- 录制和辅助预览分开限速；原生窗口改善视觉路径。不能为了流畅悄悄降低物理精度或丢掉录制帧。

## 4. 实验室教程核对

来源：[Franka真机教程.html](https://ipplab-org.feishu.cn/wiki/Fxrjw3RD1iPtUhkpAX1cGxsRnZd)。已读取用户上传的同名HTML附件；未执行其中任何命令，也未把其中的启动命令当作本次授权。

教程说明：按buffer实际到达时间取样，分别保留generated_stamp和buffered_stamp；采集、推理、重播使用相同取样规则。真机工程以60Hz动作grid运行，但GELLO新读数实测约31Hz，相机约30Hz，grid允许重复沿用已收到的有效输入。这些是教程里的真机测量，不是当前Studio20Hz Web Serial的测量。

教程中的state第8维为实测夹爪总宽度m，action第8维为0=open/1=grasp。教程中的teleop_smoothing_sec默认0.2s，属于输入滤波，不是网络延迟。当前Studio直控没有复用该真机节点的0.2s滤波。

教程也注明有些dry_run模式仍会执行Home。所以仿真手册不复制真实FR3 launch/home命令，不把dry_run一词当作“不运动”的保证。以后要操作真机时单独核对该教程与当前真机工程版本。

## 5. 部署清单与下一阶段

Collector构建产物在独立结果目录；本轮没有替换原有已构建网页。worker可通过GELLO_WEB_CONSOLE_ROOT选择新产物，部署时须将已核对的新网页与新服务端作为一组安装。

本轮只准备代码、测试和部署清单，不在目标机安装包、修改权限或启动服务。目标机原有robot-expert-agent、robot-expert-data及其他用户工程不覆盖。

建议目标目录（当前尚未复制）：

- /home/zhanghejun/robot-data-studio：源代码、config、contracts与选定的台面/布料资产；不复制data、训练权重、数据库、.env、node_modules。
- /home/zhanghejun/gello-remote：源代码与已构建Collector；不复制数据、环境、校准或历史日志。
- /home/zhanghejun/IsaacLab：固定版本的必要源代码。
- /home/zhanghejun/isaacsim_6.0.1：当前可复用的独立Isaac运行时约40GiB；复制前核对许可、依赖和总大小，不复制Conda环境。
- Studio资产目录下的独立FR3资产闭包，以及首件衣物。解析USD相对依赖后再列入复制清单。

不使用rsync --delete；先dry-run审阅精确文件清单。新建目标目录如已存在则先检查差异，不能覆盖未知改动。数据留在目标机本地磁盘，采集结束后另行同步至训练服务器。

环境配置接口（部署后才能启用）：

```
ROBOT_DATA_STUDIO_ISAAC_LOCAL_DISPLAY=1
ROBOT_DATA_STUDIO_ISAAC_ROBOT_MODEL=fr3
ROBOT_DATA_STUDIO_ISAAC_FR3_USD=<verified absolute FR3 USD path>
ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT=/home/zhanghejun/gello-remote
ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER=/home/zhanghejun/IsaacLab/isaaclab.sh
```

后台与worker还需配置目标机自己的Python环境、数据目录和资产目录。准确安装解释器、包、命令以及串口授权命令须在下一轮检查后提出并获批。不要照抄源服务器/data绝对路径。

## 6. 少量示范后如何扩增

- [DexMimicGen](https://arxiv.org/html/2410.24185v2)：每臂子任务分段、协调阶段同步和先后约束。借鉴双手协作时序；主要公开任务不是衣物。
- [SoftMimicGen](https://arxiv.org/html/2603.25725v1)：用柔体节点状态做非刚性配准并变换末端轨迹，在仿真中重新执行。当前项目只验证了原生Panda毛巾生成，不代表已接通本项目FR3扩增。
- [DexGarmentLab](https://arxiv.org/html/2505.11032v1)：人工任务顺序与抓点，借助衣物结构对应迁移抓点并按衣物大小调整轨迹；灵巧手控制不能直接替换为原装夹爪。

建议一条完整短裤对折视频 → 5–10条人工认可种子 →20条自动生成候选并看视频 →确认物理抓取和折后形状后再扩量训练。这里是后续路线，不是本轮已经实现的功能。
