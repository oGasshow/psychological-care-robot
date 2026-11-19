# 部署、升级与数据库操作

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

以下为可评审部署步骤，未连接公司服务器、正式库或 Pi。先核对公司实际提交和私有改动，将本轮 Git 差异逐项合并到同一心翼项目；不可整目录覆盖公司代码。真实心理数据启用前，项目方确认用途告知、有效授权、敏感信息单独同意等适用流程，指定人员审核支持/安全内容及量表解释。此处是项目部署前置要求，不提供法律结论。

语音、采集任务与 SEGA 的后续表使用 robot_voice_ 前缀；下文 robot_record_care_ 表单保留早期分析模块说明。完整结构以 [ORM 主应用加载入口](../../backend/app/main.py)及当前模块定义为准，接口索引见[配置说明](../reference/configuration.md)。

## 数据结构与升级

原 2.4 表结构不变；新增前缀 `robot_record_care_` 的 profiles、input_revisions、corrections、analysis_jobs、analysis_results、support_policies、strategy_deliveries、deleted_references。ORM 定义在 app/care/models.py；analysis_jobs 唯一键包含 owner/record_id/input_revision/engine_kind/engine_version/config_version，结果 job_id 唯一，更正 owner/request_id 和 record/revision 唯一，回执 owner/request_id 唯一。只新增表和索引，不回填心理标签、修改旧正文或重算量表。SQLite create_all 可重复；这是本轮新增表迁移，不是通用的未来列变更工具。

操作公司测试副本时，先停写或约定一致性窗口，在线 backup 使用 SQLite backup API，包含已提交 WAL 内容，不能仅复制活跃 .db 文件。以下在 backend 中，用该部署环境的 python，密钥和 production 配置须先按样例提供：

```powershell
python manage_records.py backup --db C:/xinyi/data/xinyi.db --output C:/xinyi/backups/pre236.db
python manage_records.py restore --source C:/xinyi/backups/pre236.db --db C:/xinyi/test/upgrade-copy.db
python manage_records.py upgrade --db C:/xinyi/test/upgrade-copy.db
python manage_records.py upgrade --db C:/xinyi/test/upgrade-copy.db
python manage_records.py check --db C:/xinyi/test/upgrade-copy.db
python manage_records.py openapi --db C:/xinyi/test/upgrade-copy.db --output C:/xinyi/openapi.json
```

backup/restore 拒绝覆盖目标，必须使用新路径。恢复后分别核查用户/原生消息/量表/2.4/新任务的行数与 FK/integrity，再切换配置。升级前后的业务行逐字段比较及 WAL 备份恢复已由本地 N02/N03 集成测试实际执行，不能外推为公司环境通过。

## 独立服务

backend 中分别启动 API 与 worker，读取同一个持久库、同一密钥与分析配置：

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
python -m app.care.worker --instance-id worker-1
```

worker 可 `--once` 扫描并处理当前可领取任务，正常服务模式持续扫描。崩溃后 pending/running 从持久任务恢复，过期租约旧 token 不能提交。有限重试耗尽保留 failed 状态，不伪造分类；修复配置产生新 config_version，可形成独立新任务。既有 database.py 配置 FK、secure_delete 和 busy_timeout；不会擅自切换已有库的 journal_mode。WAL 备份测试显式开启 WAL；现场是否启用及并发容量须在公司环境另测。

frontend 中执行 `npm ci`，设置 `BACKEND_URL=http://127.0.0.1:8000` 及 `NEXT_TELEMETRY_DISABLED=1`，`npm run build` 后 `npm start -- --hostname 127.0.0.1 --port 3000`。浏览器请求同源 /api，内部 127 地址不发给用户浏览器。改变 BACKEND_URL 要重新构建。

Linux 服务模板在 deploy/*.service 和 nginx.conf.example，填实际域名/证书/账户/持久路径；API、worker、数据库和模型只在内部访问，前端经 HTTPS 对外提供。服务权限、证书、重启与备份恢复属于公司环境待验证，模板不代表已执行。按现场策略保护环境文件和备份，默认日志不记录心理正文或 token。

回退时先停止新 worker 和新入口，用部署前配置/代码或备份副本恢复服务；保留新增表和备份，不 drop 表、不自动删新数据。旧代码本身不知道新派生清理，若回退后仍允许原 DELETE，需先停新增功能并制定对派生内容的清理方案，避免遗留数据；正式回退应由公司测试副本先演练。

## Linux／树莓派运行整套后端时的版本核查

本节用于 2026-11-19 验收。设备运行普通模式，API、分析 worker、网页和 SQLite 均在树莓派上，语音由服务端连接豆包。以下路径与仓库的 systemd 模板一致。已有部署使用其他路径、端口或服务名时，按实际配置替换本节示例。验收应用已在 Windows 完成真实豆包语音联调，树莓派整机仍需现场验收。

### 准备环境

使用 64 位 Raspberry Pi OS。后端按锁文件使用 Python 3.13，由 uv 安装到专用虚拟环境。前端用 Node.js 22 LTS，与本次开发环境的主版本相同。Node 和 npm 应安装到部署账号可访问的系统路径。Next.js 16 的最低 Node.js 版本为 20.9。 [Raspberry Pi OS](https://www.raspberrypi.com/documentation/computers/os.html#use-python-on-a-raspberry-pi) · [uv 安装](https://docs.astral.sh/uv/getting-started/installation/) · [Node.js 下载](https://nodejs.org/en/download) · [Next.js 安装要求](https://nextjs.org/docs/app/getting-started/installation#system-requirements)

```bash
dpkg --print-architecture
sudo apt update
sudo apt install -y git curl ca-certificates
node --version
npm --version
command -v node
```

`dpkg --print-architecture` 应输出 `arm64`。后续以 `xinyi` 账号运行应用。首次安装时创建账号和持久目录，再克隆到空的 `/opt/xinyi`。

```bash
id xinyi >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin xinyi
sudo install -d -o xinyi -g xinyi -m 0750 /opt/xinyi /var/lib/xinyi
sudo -u xinyi -H git clone https://github.com/oGasshow/psychological-care-robot.git /opt/xinyi
sudo -u xinyi -H sh -c 'curl -fsSL https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/opt/xinyi/.tools/bin sh'
```

### 已有设备先备份

已有部署从这一步开始。先用 systemd 核对实际代码目录、环境文件和运行账号。确认现有会话已保存，记下旧提交号及服务配置。下面的备份命令以标准路径为例。环境文件和语音待传目录也应保留，供原部署继续使用。

```bash
sudo systemctl cat xinyi-api xinyi-worker xinyi-web
sudo -u xinyi git -C /opt/xinyi rev-parse HEAD
sudo -u xinyi git -C /opt/xinyi status --short
sudo systemctl stop xinyi-web xinyi-worker xinyi-api
sudo install -d -o xinyi -g xinyi -m 0700 /var/lib/xinyi/backups
backup_path="/var/lib/xinyi/backups/pre-acceptance-$(date -u +%Y%m%dT%H%M%SZ).db"
sudo -u xinyi python3 /opt/xinyi/backend/manage_records.py backup \
  --db /var/lib/xinyi/xinyi.db --output "$backup_path"
sudo -u xinyi python3 /opt/xinyi/backend/manage_records.py check --db "$backup_path"
```

有未提交改动时，先确认其用途并保留原目录。备份检查应返回 `integrity_check: ok` 和 `foreign_key_violations: 0`，再继续更新。

### 固定验收提交并构建

在服务实际使用的克隆目录操作，确认 `origin` 指向 `oGasshow/psychological-care-robot`。已有设备如未安装 uv，可运行上面的 uv 安装命令。

```bash
accepted_rev=4a6d4f254930f83e3e8195c1a68ab9f95c4df07e
sudo -u xinyi git -C /opt/xinyi remote get-url origin
sudo -u xinyi -H git -C /opt/xinyi fetch origin main
sudo -u xinyi -H git -C /opt/xinyi switch --detach "$accepted_rev"
test "$(sudo -u xinyi git -C /opt/xinyi rev-parse HEAD)" = "$accepted_rev"

sudo -u xinyi -H env UV_PROJECT_ENVIRONMENT=/opt/xinyi/.venv \
  /opt/xinyi/.tools/bin/uv sync --project /opt/xinyi/backend --locked --no-dev --python 3.13
sudo -u xinyi /opt/xinyi/.venv/bin/python --version

sudo -u xinyi -H sh -c 'cd /opt/xinyi/frontend &&
  npm ci --include=dev &&
  BACKEND_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1 npm run build'
```

`switch --detach` 将设备锁定在验收提交。两次依赖安装分别使用 `backend/uv.lock` 与 `frontend/package-lock.json`。`npm start` 会直接使用现有构建，因此更新后应重新构建并确认命令成功。

### 配置树莓派上的私有环境

API 和 worker 共用 `/etc/xinyi/backend.env`。首次部署创建环境文件，已有部署直接编辑并保留原 `SECRET_KEY` 和数据库路径。

```bash
sudo install -d -m 0750 /etc/xinyi
sudo test -e /etc/xinyi/backend.env || sudo install -m 0600 /dev/null /etc/xinyi/backend.env
sudoedit /etc/xinyi/backend.env
```

```dotenv
APP_ENV=production
SECRET_KEY=
DATABASE_URL=sqlite:////var/lib/xinyi/xinyi.db
ROBOT_CARE_VOICE_OUTBOX_DIR=/var/lib/xinyi/voice_outbox
ROBOT_CARE_VOICE_RECORD_BASE_URL=http://127.0.0.1:8000

ROBOT_CARE_VOICE_ENABLED=true
DOUBAO_VOICE_API_KEY=
ROBOT_CARE_GUIDED_SCREENING_ENABLED=true
ROBOT_CARE_PURCHASE_NOTICE_VERSION=
ROBOT_CARE_CONCERN_REVIEW_MODE=post_session
ROBOT_CARE_COLLECTION_DEMO=false
ROBOT_CARE_DEMO_DATABASE=false

ROBOT_CARE_ANALYSIS_ENGINE=doubao_realtime
ROBOT_CARE_SENTIMENT_TIMEOUT_SECONDS=45
ROBOT_CARE_LEASE_SECONDS=90
ROBOT_CARE_REPORT_PROVIDER=doubao_realtime
ROBOT_CARE_REPORT_TIMEOUT_SECONDS=45
ROBOT_CARE_ASSESSMENT_PROVIDER=disabled
```

- **`SECRET_KEY`** 为本站 JWT 和游标密钥，至少 32 字符。首次部署可运行 `sudo -u xinyi /opt/xinyi/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'` 后填入。
- **`DOUBAO_VOICE_API_KEY`** 填具备豆包实时语音全双工资格的服务端 API Key。缺少该值时，网页可打开但语音会显示未配置。完整语音配置见[语音说明](../features/voice.md)。
- **`ROBOT_CARE_PURCHASE_NOTICE_VERSION`** 填实际生效的采集用途告知版本。启用自动采集时此值必填。`post_session` 是普通版配置名，启用后仍会在通话中按线索收集，结束后再核对。没有启用采集时可将 `ROBOT_CARE_GUIDED_SCREENING_ENABLED` 设为 `false`，保留普通语音陪伴。
- **`ROBOT_CARE_ASSESSMENT_PROVIDER=disabled`** 关闭旧外部量表输入。对话辅助采集的 PHQ-9／GAD-7 结果仍会显示。此部署流程独立于 SEGA，其作者权重脚本需要 CUDA 环境，现场如需该实验能力按[SEGA 说明](../features/sega.md)配置。

### 启动服务与打开网页

首次部署时安装模板。先核对 [API](../../deploy/xinyi-api.service)、[worker](../../deploy/xinyi-worker.service) 和[前端服务](../../deploy/xinyi-web.service)中的用户、工作目录和可执行文件。前端模板默认用 `/usr/bin/node`。若 Node 安装在其他路径，按实际位置调整前端服务的 `ExecStart`。已有设备可继续使用原服务文件。

```bash
# 首次安装模板
sudo install -m 0644 /opt/xinyi/deploy/xinyi-api.service /opt/xinyi/deploy/xinyi-worker.service /opt/xinyi/deploy/xinyi-web.service /etc/systemd/system/

# 首次安装或更新后执行
sudo systemctl daemon-reload
sudo systemctl enable xinyi-api xinyi-worker xinyi-web
sudo systemctl restart xinyi-api xinyi-worker xinyi-web
sudo systemctl is-active xinyi-api xinyi-worker xinyi-web
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:3000/api/robot-voice/mode
```

三个服务均应为 `active`，健康检查应返回 `status: healthy`，网页端模式检查应返回 `mode: normal`。首次启动会初始化 SQLite 表。已有库可用上面的 `manage_records.py check` 复核。

在树莓派自身浏览器打开 `http://127.0.0.1:3000/login`。从另一台电脑访问时，使用有可信证书的同源 HTTPS，语音 WebSocket 随之使用 WSS。FastAPI 和 Next.js 保持回环监听。浏览器麦克风需要安全上下文。 [浏览器麦克风权限说明](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia#security)

如需从局域网访问，首次配置可复制 [Nginx 模板](../../deploy/nginx.conf.example)。将 `server_name` 与证书路径改为实际值，并让访问电脑信任该证书。已经配置 HTTPS 的设备可核对现有站点是否将请求和 WebSocket 升级头转给 `127.0.0.1:3000`。如果语音入口经反向代理后被拒绝，在 `backend.env` 中将 `ROBOT_CARE_VOICE_ALLOWED_ORIGINS` 设为浏览器实际使用的完整站点源，包含协议和非默认端口，再重启 API。

```bash
sudo apt install -y nginx
sudo install -m 0644 /opt/xinyi/deploy/nginx.conf.example /etc/nginx/sites-available/xinyi
sudoedit /etc/nginx/sites-available/xinyi
sudo ln -s /etc/nginx/sites-available/xinyi /etc/nginx/sites-enabled/xinyi
sudo nginx -t && sudo systemctl reload nginx
```

### 现场验收与常见问题

1. **版本与入口**。在 `systemctl cat` 所列实际服务目录核对 `git rev-parse HEAD`，应为本节的完整验收提交。登录后打开 `/robot-care/voice`。如果看到原首页或旧版界面，核对访问地址和前端服务工作目录，再检查该目录是否重新构建并重启。
2. **语音与保存**。用单独测试账号打开麦克风，确认用户转录、豆包回复和扬声器播放。说「结束吧」后，在「对话记录」看到双方转录。「删除对话」应在测试会话结束后出现，确认后验证该会话及报告不再可见。
3. **计分与报告**。在普通模式测试一段含虚构低落和焦虑线索的对话，给出明确的近两周频率。可说「你可以继续问我」，覆盖后续未确认项。核对 `/robot-care/assessments` 和 `/robot-care/report` 对同一会话的覆盖率和分数，验证打印页。完整验收的判定为 PHQ-9 9/9 项、GAD-7 7/7 项，具体分数由现场实际回答决定。
4. **语音配置或连接故障**。若网页提示语音未配置，检查运行中的 API 单元引用的 `EnvironmentFile`，确认已填全双工密钥并重启 API 与 worker。若语音已启用却无法连接，检查浏览器麦克风授权、HTTPS/WSS 转发以及树莓派到豆包服务的出站连接。查看 `sudo journalctl -u xinyi-api -u xinyi-worker -u xinyi-web -n 100 --no-pager`。

如需回退，使用安装前记录的提交和原服务配置，重新构建对应前端。现有数据库及备份保留在独立目录，先在备份副本上验证旧版读取，再决定是否切换数据。

仅把树莓派作麦克风和扬声器终端时，使用[树莓派终端接口](../features/voice.md#树莓派保留入口)，后台仍运行在另一台机器。
