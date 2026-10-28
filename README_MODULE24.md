# 2.4 本地开发包

本模块接收已整理的双方终态文本，先写本地 SQLite outbox，再写入心翼同一数据库中的独立记录表。新接口不生成回复，不调用模型。默认以本文件作为开发入口，原 README 是上游说明。

范围为 M0—M3 和 L1 开发自测。L2 真实语音事件与 L3 公司测试环境尚缺条件；独立验收由原计划对话执行。原生聊天页面不会自动显示这些记录；`/api/chat/clear` 只清原生聊天。2.3/2.6 应经本模块查询接口消费数据。

## 1. 代码与基线

- 上游核查提交：`01add7abd7c1d4da72adf7463006a3baec5e6aed`。
- 本地复制基线：`5abae05`。原快照是部分/稀疏克隆：已落地的 52 个文件全部复制，Git blob 与原提交一致；后端完整。原快照未落地的 13 个前端图片/图标没有补下载，不影响本模块。
- 新仓库不宣称与上游具有同一 Git 提交祖先。交付包含复制基线、差异、Git bundle 和源代码 ZIP；可查 `baseline.json`。
- 原审计快照和计划文档仅作对照。测试不使用其中的 data，也不访问公司、豆包或真实机器人。

## 2. 环境准备

要求 Python ≥3.13；实际版本和依赖以交付环境记录及 `backend/uv.lock` 为准。推荐用 uv 创建本项目独立 `.venv`。不要向科研 venv 安装。

在仓库根目录运行（已有 uv）：

```powershell
.\Setup-Module24.ps1
```

可传 `-UvExecutable 'uv.exe的绝对路径' -PythonExecutable 'Python3.13解释器绝对路径'`，避免自动寻找其他环境。脚本把 Python 下载目录、缓存及虚拟环境都指向当前项目。若已有合适 Python，直接传完整路径。本轮使用项目内 uv，引导安装命令记录于交付的 `environment.json`。

后续命令均在 `backend` 目录执行：

```powershell
$env:PYTHONUTF8='1'
# 生成到当前进程环境；不要输出或提交此值。重启服务须恢复原密钥。
$env:SECRET_KEY = & '..\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_urlsafe(48))'
$env:DATABASE_URL='sqlite:///./runtime/local.db'
& '..\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动时会幂等创建新增表，SECRET_KEY 缺失或小于32字符会拒绝启动。所有配置先由 `app/config.py` 从进程环境或 `backend/.env` 读取，再初始化数据库与JWT；进程环境优先。修改配置后重启进程。

## 3. 完整自测与 CLI 回放

```powershell
& '..\.venv\Scripts\python.exe' -m pytest tests -q --disable-warnings --junitxml=./test-results/junit.xml
& '..\.venv\Scripts\python.exe' tools/local_replay.py --output ./test-results/replay
```

回放工具自动启动仅绑定回环地址的独立后端，注册虚构用户，实际调用 CLI 的 bind/replay/work/status，核对3条记录及原生表行数，导出 OpenAPI 和脱敏轨迹，最后停止服务并删除临时库。不需要手工保存密码、token 或数据库。

单项自测可用 `-k A22` 等选择，A07/A24含多个参数化子项。测试默认创建系统临时目录内的真实文件数据库；`MODULE24_EVIDENCE` 可指定脱敏 JSON 证据输出目录。真实子进程测试使用随机回环端口。测试模型接口已替换为报错哨兵；仅 A27 的旧聊天回归使用可控替身。测试不调用付费服务，不下载模型。

## 4. 接口与状态

全部接口使用原 `POST /api/auth/register`、`POST /api/auth/login` 和 `GET /api/auth/me` 的用户/JWT。请求体不接受用户ID。接口前缀 `/api/robot-records`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /sessions | 新建201，完全一致重复200；已删410 |
| GET | /sessions | 当前用户非删除会话，内部ID倒序快照分页 |
| GET | /sessions/{recording_session_id} | 详情、接收计数、最大序号和完整状态 |
| POST | /sessions/{recording_session_id}/messages | 不可变终态文本，首次201、重复200、内容/序号冲突409 |
| GET | /sessions/{recording_session_id}/messages | 按sequence升序，签名游标绑定用户、会话、快照和排序 |
| POST | /sessions/{recording_session_id}/close | 固定最终序号上界；关闭后允许上界内补传 |
| DELETE | /sessions/{recording_session_id} | 删除消息和非必要会话元数据，仅保留防重建标记 |

OpenAPI 中路径变量名为 `sid`，对应上述 `recording_session_id`；URL与业务语义相同。请求、响应详情见 `app/robot_records.py`、共享的 `robot_client/schemas.py` 和交付的 OpenAPI。请求时间统一UTC、微秒精度、Z结尾；原文不做strip。

会话唯一键为 `(user_id,source,external_session_id)`；消息唯一键为 `(recording_session_id,external_message_id)` 和 `(recording_session_id,sequence_no)`。写事务先 `BEGIN IMMEDIATE`，再检查状态；唯一约束和冲突回读兜底，提交后才ACK。读取统计使用真实聚合，不维护可漂移缓存。新表外键实际启用，ID使用 SQLite AUTOINCREMENT 以支撑快照。

关闭不代表传齐，closed且计数等于最终上界才完整。文本 `completed` 不代表播放完成，`canceled` 不是完整发言；`unknown` 不会自动升级。没有 PATCH。下游应按状态处理，不能把助手生成文字等同于老人听到的全部文字。

错误结构为 `error.code/message/retryable`。常规验证只返回字段位置/类型，不回显心理正文。数据库锁忙或事务提交失败均使用契约内的 `503 storage_busy`，未提交成功不会返回成功ACK；客户端可用同一编号重试。

## 5. 文本客户端接入

先在非音频路径完成登录及 bind，身份由 `/api/auth/me` 核实。运行期 token 仅在 Transport/进程环境，不能存入 outbox。换用户、换目标时使用对应分区，旧分区需用原身份恢复。

```powershell
$env:ROBOT_BASE_URL='http://127.0.0.1:8000'
$env:ROBOT_OUTBOX_PATH='./runtime/outbox.db'
# ROBOT_TOKEN 通过原登录响应在进程环境中提供，不使用命令行参数。
& '..\.venv\Scripts\python.exe' -m robot_client bind
# 将 bind 返回的 owner_user_id 用于以下 --owner；示例的1须以实际返回为准。
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 replay examples/final_events.json
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 work
```

Ctrl+C 停止worker；`work --once`只执行一条符合依赖和调度时间的任务。默认5秒HTTP超时；暂时失败指数退避，普通上限60秒及抖动，合法Retry-After优先；连续8次暂时失败进入 `paused_retry`。参数见配置表。没有在音频路径等待HTTP或退避。

Python库中 `Outbox.create_session(body)`、`enqueue(external,event)`、`close_session(external,ended_at)` 先本地提交再返回。enqueue的event不含sequence_no，客户端在同一事务中分配序号和入队；稳定的 external_message_id 重试不变。映射、高水位、封存/删除状态存于独立sessions表，清除ACK正文或重启不会重置序号。关闭入队后禁止新增消息，原pending仍能补传。

音频回调只应调度文本任务。文本任务可 `await box.enqueue_async(external,event)`，其持久化在独立线程执行，入口不发HTTP、不等待退避。初始化/bind、同步方法和worker均不得直接放入音频回调。真实音频侧调度及最终播放回执由2.1负责人在L2确认。

| 状态 | 含义及操作 |
|---|---|
| pending / sending | 已持久化待处理 / 已领取未确认；取得OS worker锁后可恢复sending |
| retry_wait | 网络、429或5xx；持久化最早重试时间 |
| blocked_auth | 身份、凭证或目标不匹配；换回正确凭证后显式resume |
| dead_letter | 永久HTTP错误或成功响应校验失败；查回原记录并修复后显式重放 |
| paused_retry | 连续暂时失败达到阈值；修复后显式resume |
| acked | 编号和关键元数据核验成功；正文已清除，保留最小回执 |

```powershell
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 status
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 resume
# 409应先查回原记录核对，不自动换ID或序号绕过去重。
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 resume --include-dead
& '..\.venv\Scripts\python.exe' -m robot_client --owner 1 purge fictional_demo_001
```

队列容量默认10000条未ACK任务（整个文件统计，包含暂停/失败任务），`--capacity`可调整；满时 `queue_full`，写失败 `local_storage_error`，不会把失败入队当作成功。ACK元数据不会随队列空而丢失。操作系统文件锁限制同一outbox文件同时执行一个网络任务；不支持并行worker来提升吞吐。

410只有在确认错误码 `session_deleted` 时才清理该服务/用户/会话分区的正文。离线设备无法立即获知远端删除；下次连接或显式purge才清理。本地purge阻止后续重建，不能撤销已经发出的HTTP请求；远端DELETE提供最终防重建屏障。SQLite逻辑删除与secure_delete不能替代系统磁盘、旧备份/WAL或文件系统的物理擦除策略，保留政策待L3确认。

## 6. 升级、备份、恢复

先在公司旧库的授权复制件验证；此交付不操作公司库。新增两张表，无旧表增删列；`create_all`仅用于不存在表的创建，无结构降级脚本。停止服务再切换恢复库，恢复默认只允许新目标路径，不覆盖或删除当前记录。

```powershell
& '..\.venv\Scripts\python.exe' manage_records.py backup --db ./runtime/local.db --output ./runtime/before_upgrade.db
& '..\.venv\Scripts\python.exe' manage_records.py upgrade --db ./runtime/local.db
& '..\.venv\Scripts\python.exe' manage_records.py upgrade --db ./runtime/local.db
& '..\.venv\Scripts\python.exe' manage_records.py restore --source ./runtime/before_upgrade.db --db ./runtime/restored.db
& '..\.venv\Scripts\python.exe' manage_records.py check --db ./runtime/restored.db
& '..\.venv\Scripts\python.exe' manage_records.py openapi --db ./runtime/openapi_scratch.db --output ./test-results/openapi.json
```

备份使用SQLite online backup API，支持提交内容位于WAL时的一致备份，并做完整性/外键检查。也可同样备份outbox文件。恢复到旧备份会失去该时刻以后的记录，应保留当前库并由负责人决定切换；不能将旧备份直接覆盖当前库。

## 7. 配置对应位置

| 配置 | 默认/约束 | 实际读取位置 |
|---|---|---|
| DATABASE_URL | sqlite:///./data/xinyi.db；测试总是显式临时库 | app/config.py → app/database.py，导入时 |
| SECRET_KEY | 必填≥32字符；JWT及签名游标共用 | app/config.py → auth.py / robot_records.py |
| SQLITE_BUSY_MS | 1000ms | app/config.py → database.py 每连接 |
| ROBOT_BASE_URL / ROBOT_OUTBOX_PATH | CLI必填或参数提供 | robot_client/__main__.py |
| ROBOT_TOKEN | bind/work必填，仅进程配置 | robot_client/__main__.py → Transport |
| ROBOT_HTTP_TIMEOUT | 5秒 | robot_client/__main__.py |
| ROBOT_RETRY_BASE / ROBOT_RETRY_CAP | 1秒 / 60秒 | robot_client/__main__.py → Worker |
| ROBOT_MAX_TRANSIENT | 8次 | robot_client/__main__.py → Worker |
| MODULE24_EVIDENCE | 系统临时目录 | tests/conftest.py |

Python库支持构造参数设置上述客户端选项，CLI的容量由 `--capacity` 提供。base_url规范化协议/主机大小写、默认端口和尾斜线，禁止URL内凭证、查询与fragment。明确使用同一配置服务路径；不能通过换base_url发送旧分区任务。

## 8. 证据与待联调

交付目录包含运行环境、Git差异、OpenAPI、实际CLI回放、测试XML及逐用例JSON、独立目录复现结果、自测回执和开发交接说明。回执 `review` 全部保留未复核。

仍需：2.1的真实脱敏事件、原生ID关联依据和可靠播放回执；公司实际部署提交、测试地址/账号、用户绑定、HTTPS及部署备份负责人。缺这些条件不影响本地实现，不能据L1自测宣称真实豆包、R1或公司链路已通过。上游原生Schema仍有Pydantic弃用警告，本模块未扩展为上游全项目重构。

实现核查参考：[uv独立Python](https://docs.astral.sh/uv/guides/install-python/)、[SQLAlchemy SQLite事务及外键](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)。
