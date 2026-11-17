# 公司合并与数据库操作

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

树莓派也可以自行部署服务端，但本项目尚未完成整套服务在树莓派上的真机验收。Windows `.cmd`／`.ps1` 启动器不适用于 Linux，不能复制 Windows 的虚拟环境、前端构建或绝对路径当作已部署。

出现“从仓库拉取后像旧版”时，分别核对以下几项，不先清空数据或重建演示库：

1. **源码**：在实际部署目录执行 `git remote -v`、`git branch --show-current`、`git rev-parse HEAD`、`git status --short`、`git ls-remote origin refs/heads/main`。远端应为本项目仓库；完整提交号相同，才表示已提交的源码版本一致。存在未提交修改时先核查，不执行强制覆盖。
2. **入口**：新版工作台是 `/robot-care`，语音页是 `/robot-care/voice`；原首页 `/`、旧聊天等路由保留。它们不是新版机器人入口。登录后仍可直接访问工作台路径。
3. **前端构建**：`npm start` 运行已有构建，不会自动重新编译刚拉下来的源码。更新后应在服务实际使用的 `frontend` 中执行 `npm ci`，用正确的 `BACKEND_URL` 执行 `npm run build`，再重启前端。服务端口、构建目录和反向代理目标要一致。
4. **实际服务目录**：本仓库 systemd 模板写的是 `/opt/xinyi/backend` 和 `/opt/xinyi/frontend`。用 `systemctl cat xinyi-api`、`systemctl cat xinyi-web` 检查机器实际配置；更新另一个克隆目录不会改变正在运行的服务。
5. **私有配置**：Git 不包含 `backend/.env`、数据库、模型资源或 `runtime/`。整套后端部署到树莓派时，需要在该机器配置语音凭据；使用本仓库 systemd 模板时，环境文件是 `/etc/xinyi/backend.env`。进程环境优先于 `backend/.env`，改好后需重启 API 和 worker，不能只刷新网页。

Windows 现场端口由启动器保存；Linux 模板的前端3000、后端8000只是模板值，不应套用另一台电脑的61500／61499。远程浏览器语音还需要 HTTPS／WSS，见[语音说明](../features/voice.md)。

SEGA 的本机模型资源和配置也不会随 Git 拉取。本项目当前作者权重推理脚本要求 CUDA，不能因树莓派已经启动网页和 API 就认为 SEGA 已能在树莓派本机运行；该部分需要另行安排 GPU 服务及验证。

### 原终端部署范围记录

树莓派只放 2.1/2.7 音频输入播放、最终文本事件、robot_client 队列和可选 care_core 规则预览；云端运行 FastAPI、worker、Next 及可选模型。Pi 的 ARM/Python/音频、开机管理、真实语音/策略生效由后续实际设备验证。本轮电脑进程模拟不证明 Pi 兼容。2.5 接入经确认量表记录级版本、完成时间、分数范围和审核引用后再启用可靠 live 展示；当前缺这些证据时显示 unverified。
