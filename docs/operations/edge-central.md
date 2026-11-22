# 树莓派本地运行、服务器统一保存

本方案用于当前需求：树莓派运行用户网页、API、语音桥接、量表采集和本地分析 worker；服务器运行 PostgreSQL 与只读管理员报告网页/API，不运行语音和分析 worker。

用户在树莓派自身打开 `http://127.0.0.1:3000/login`。页面及本地 API 不需要 HTTPS。数据库通过 SSH 加密隧道访问服务器回环端口，不开放公网 5432；管理员网页也可通过单独受限隧道访问。之后可以为管理网页配置正常 HTTPS 域名。

## 数据与权限

- `ROBOT_CARE_DEPLOYMENT_ROLE=edge` 强制使用 PostgreSQL，拒绝 SQLite 回退。账号、对话、逐项答案、进度、结果、风险标记和报告文字保存在服务器。
- 终端只在 RAM 中暂存尚未确认保存的文字，收到服务器提交确认才显示保存成功。新终端模式不创建本地业务 SQLite 队列。
- 网络中断或数据库不可用时报告保存失败／待确认；进程仍运行时可重试内存队列。设备断电或进程退出可能丢失未确认数据，不承诺离线持久采集。
- SEGA 特征提取的敏感临时文件限定为 Linux `/dev/shm` tmpfs，任务音频与结果仍保存在服务器数据库。没有该内存工作区时不启用自动特征提取。
- 终端数据库账号只能写业务表及注册普通用户，不能授予管理员权限或改写已有账号密码。设备仍属于受信任的应用后端，须保护操作系统与私有设备配置；普通浏览器不接触数据库凭证。
- 管理服务使用独立只读账号，只额外允许插入访问审计。管理端与终端使用不同的 JWT 签名密钥，禁止交叉使用登录 token。
- 中央服务只允许管理员登录和读取报告，拒绝注册、语音 WebSocket、普通业务操作和模型生成接口。分析 worker 拒绝在 `central` 角色启动。

## 本机已配置的入口

- 本地用户端：`http://127.0.0.1:51078/login`。普通启动器已读取活动运行目录中的 edge 配置，先建立加密数据库隧道，再启动本地 API、worker 和页面。
- 本机隧道启动工具会在后台监督连接并自动重连。注册、登录仍需服务器可达；数据库断开时返回明确的 503，不创建本地业务库作为回退。
- 服务器管理员端：运行根目录 `Open-ServerReports.cmd`，通过加密隧道打开 `http://127.0.0.1:53111/login`。实际网页、认证和数据库位于服务器，localhost 是加密转发入口。
- 私有配置保存在 `runtime/edge-central`，包括受限 SSH 密钥和连接设置；不提交到仓库。原本地 SQLite 留作历史备份，不再承接 edge 模式的新数据。

## 树莓派安装包

若用户端注册失败，先检查本地 API 的 `/health`：`storage=server_unavailable` 表示服务器存储连接不可用。恢复隧道后重试；管理员入口不开放用户注册。注册字段不符合要求时，网页会显示具体校验消息。

使用本次生成的私有终端安装包，解压后运行：

公开源码中的实际服务器地址已移入私有 `connection.env`（终端）和 `connection.json`（管理员启动器），模板位于 `deploy`。安装包需由负责人提供，或用 `tools/package_edge.py` 配合授权私有配置重新打包；不能仅下载公开源码便连接现有服务器。

```bash
sudo bash deploy/edge/install-edge.sh
```

要求 64 位 ARM Raspberry Pi OS 和可联网的包管理环境。脚本安装 Python 3.13、所需依赖和 Node.js，构建本地网页，安装数据库隧道、API、worker、网页四个 systemd 服务。服务仅监听本机回环地址。

```bash
systemctl status robot-care-edge-tunnel robot-care-edge-api robot-care-edge-worker robot-care-edge-web
journalctl -u robot-care-edge-api -u robot-care-edge-worker -n 80 --no-pager
```

安装后在树莓派浏览器打开 `http://127.0.0.1:3000/login`，首次允许麦克风，并选择、测试实际音频设备。若需开机全屏打开页面，在树莓派桌面配置该网址的浏览器自启动。

安装包包含设备连接凭据和豆包配置，只交付给目标设备，不作为公开源码发布。新设备应单独发放、登记和撤销设备 SSH 密钥。SEGA 作者权重、特征模型和推理环境不随通用安装包跨平台复制；Windows 虚拟环境不能直接用于 ARM。需在目标树莓派配置合适的 ARM 模型环境，再核验速度与内存占用。

## 服务器位置

新版中央应用：`/opt/robot-care-central/app`；服务配置：`/etc/xinyi/central.env`。服务为 `robot-care-central-api` 和 `robot-care-central-web`，分别监听 127.0.0.1:8011、127.0.0.1:3011。PostgreSQL 数据库为 `robot_care`，旧 `/var/lib/xinyi/xinyi.db` 是迁移前保留的 SQLite 副本。旧 `/opt/xinyi` 项目没有覆盖。

迁移工具 `backend/tools/migrate_to_postgres.py` 仅向空目标数据库导入一致性 SQLite 快照，逐表校验行数并设置主键序列；已有目标数据时拒绝覆盖。23 项隔离 PostgreSQL 测试与端到端虚构量表验证不等于树莓派硬件、真人语音或 SEGA 临床效果验收。
