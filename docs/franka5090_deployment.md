# 双 FR3／双 GELLO：通过 GitHub 部署

本指南采用 Git clone／pull 交付代码，用固定版本的 Release 附件交付必要资产。准备脚本只下载、校验、整理文件和路径，不安装包、启动仿真、修改串口权限或操作真机。

## 1. 在 5090 上新建工作区

此前直接复制到 `/home/zhanghejun/{robot-data-studio,gello-remote,IsaacLab,isaacsim_6.0.1}` 的目录保留原样。它们不是 Git clone，不要在其中执行 git pull，也不要为本次部署删除它们。建议先使用独立工作区：

```bash
mkdir -p ~/cloth-teleop
cd ~/cloth-teleop
git clone --branch feat/genesis-ipc-isaac-teleop git@github.com:codeofwhite/robot-data-studio.git
cd robot-data-studio
bash scripts/prepare_franka5090.sh
```

两个个人仓库需要 GitHub 访问权限。准备脚本通过现有 Git SSH 身份拉取 gello-remote；Release 附件可以通过已登录的 `gh`，或仅限本仓库的 API token 下载。默认可读当前用户的 `~/.config/cloth-teleop/github-release.token`（仅本人可读，权限600），也可用 `--github-token-file` 指定文件；凭据不会复制到部署目录或Git。跨主机下载重定向不会转发 Authorization 头。SSH 推送身份不能代替 Release API 身份。不要在聊天中粘贴 token。没有这两种授权时，可以先在有权限的电脑下载同名附件，再传入：

```bash
bash scripts/prepare_franka5090.sh --archive /absolute/path/franka5090-assets-v1.tar.gz
```

这不是复制源服务器的工程快照：代码仍来自 GitHub 固定版本，只有已发布、带 SHA256 的资产附件可离线传入。

## 2. 版本与准备行为

唯一版本入口是 `deploy/franka5090/manifest.json`：

- Studio：当前部署分支，必须包含 FR3／双 GELLO 功能提交 ed4d17b。
- gello-remote：固定功能提交 7880e9d，作为同级 Git checkout。
- IsaacLab：官方上游 28a37cecdd433c22d9eabd6a5954add9f13a8951，另应用本地已使用版本中的两个启动相关补丁。原本地提交 4d241526b 不在官方仓库，不能直接要求另一台机器 clone 它；本包没有携带无关的方块抓取任务。
- Isaac Sim：参考运行版本为 6.0.1-rc.7+release.42383.32955d8d.gl，单独取得和安装；不在 Git 或资产附件中分发，也不自动换成其他版本。

准备脚本检查整包和包内每个文件的大小与 SHA256，只写清单指定的相对路径；拒绝路径穿越、链接及未知成员。已有同内容文件可复用，不同内容会报错并保留。已有其他版本的仓库也不会被 reset、clean 或覆盖。

新 clone 的 gello-remote 与 IsaacLab 处于 manifest 指定的 detached HEAD；这是依赖锁定，不要在其中盲目 git pull。升级入口是 Studio 分支中的新版 manifest：先审阅 git pull --ff-only 的变化，再显式更新依赖到指定提交。

Release 附件包含：v17 工作台 USD／清单、HDRI、原布料 USD、FR3 USD／schema、Marble006 注册记录与三张贴图、匹配的 Collector 构建产物，以及最小 IsaacLab 启动补丁。不包含 SDK、Conda 环境、数据集、模型权重、录制结果、账号凭据或 GELLO 标定。

## 3. 生成的本机配置

```bash
source data/deploy/franka5090/env.sh
```

该文件只包含根据实际 workspace 生成的路径和本机显示开关，没有凭据。它将 Studio 指向同级 gello-remote、IsaacLab、本地 FR3 USD、独立 Collector 构建及本项目资产目录，不依赖源服务器的 `/data/zhanghejun` 路径。

AssetRegistry 使用生成的 `asset_sources.local.json`，只声明本场景实际使用的三个来源。已有全量资产源配置未改写。

Python 环境预留为 `WORKSPACE/.venvs/isaaclab`；必须完成后续明确批准的环境安装后才能启动 worker。兼容 SDK 放在同级目录后，也需要核对 IsaacLab/_isaac_sim 的相对链接。准备成功不等于依赖安装成功或 GPU 运行成功。

## 4. 先验证资产，再现场试用

以下检查无需设备、GPU或依赖安装：

```bash
bash scripts/prepare_franka5090.sh --verify-archive /absolute/path/franka5090-assets-v1.tar.gz
```

只下载／整理资产、暂不 clone 依赖时：

```bash
bash scripts/prepare_franka5090.sh --assets-only --archive /absolute/path/franka5090-assets-v1.tar.gz
```

本机试用还需要：独立 Python 依赖环境、对应 Isaac SDK、支持 Web Serial 的浏览器、登录操作者自己的图形桌面，以及两套独立 USB 的串口权限。不得向其他实验室用户桌面注入窗口。

环境就绪后选择双 FR3／PhysX、双 GELLO、相机配置 isaac_fr3_dual_wrist_v1、960×720、本机显示。先分别校准左右主臂与夹爪，再看完整动作和录制三路图像。流程细节见 `docs/franka_5090_teleop.md`。

已验证边界：服务器上创建过双臂场景与四路预览，三路保存接口有静止记录；双 GELLO 实物连接与端到端延迟尚未验证。当前布料 PhysX 初始化警告未解决，不能把部署、相机连通或静止录制称为成功夹布／成功示范。
