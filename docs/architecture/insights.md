# 2.3 / 2.6 与 2.4 增补

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

本文保留早期模块设计和契约，旧环境路径及当时验收结论按快照理解。首次运行看[快速开始](../getting-started.md)，当前语音、模型和采集范围以[当前状态](../status.md)及功能文档为准。

2026-11-04新依赖与干净安装入口见 `docs/operations/installation.md` / `Setup-Project.ps1`；下述环境复用说明属于前一轮历史。

2026-10-29 D01—D04修复：配置A→B→A恢复当前结果；测试/非测试来源分流与准确打印；fixture文档错误受控降级；演示停止验证实例归属。详见 `docs/archive/fixes/d01-d04.md`。新增交付保留原独立验收结论，等待重新复核。

在已验收 `aac2115b4c4b8835f3241d0ea1994f5cbec48981` 上增量实现，同一个 FastAPI/Next 项目。新增功能只在虚构本地数据下验证；开发自测不代替独立验收。入口 `/login` → `/robot-care`，历史、会话与转录更正、只读量表、趋势、报告/打印均在此入口。项目性质为辅助陪伴设备，非专业心理咨询师或医疗服务设备。

## 本机准备与演示

本轮实际复用项目环境 `F:\横向课题\心理疏导机器人系统\开发工作区\module24\.venv\Scripts\python.exe`，Python 3.13.18 / SQLite 3.53.1；没有改科研环境。Node 22.14.0 / npm 10.9.2。后端依赖保留 `backend/uv.lock`，前端 `package-lock.json` 固定 playwright-core 1.56.1；浏览器使用已装 Edge，不下载浏览器或模型。

全新机器可安装 Python 3.13 和 uv，在 backend 执行 `uv sync --frozen --group dev`；此轮没有验证全新机器安装。以下命令在项目根目录运行，`$py236` 可替换成新环境解释器：

```powershell
$py236='F:\横向课题\心理疏导机器人系统\开发工作区\module24\.venv\Scripts\python.exe'
Set-Location frontend
npm ci
Set-Location ..
& $py236 backend/tools/demo_care.py prepare --runtime "$PWD/runtime/my_demo_001"
& $py236 backend/tools/demo_care.py start --runtime "$PWD/runtime/my_demo_001"
```

首次启动自动准备两名虚构用户、跨日期情绪记录、只读虚构量表，启动 API、独立 worker、Next，输出实际端口。打开输出的 `/robot-care` 地址，按登录提示到 `/login`。密码只在本机专用 `runtime/my_demo_001/access.json`，不提交、复制或发送此文件。脚本检查 Next 已构建的后端地址，必要时重新 build（先完成 npm ci）；构建日志在 runtime。前端启动后首次 HTTP 可稍等几秒。所有文本均虚构、`is_test=true`。

```powershell
& $py236 backend/tools/demo_care.py stop --runtime "$PWD/runtime/my_demo_001"
& $py236 backend/tools/demo_care.py start --runtime "$PWD/runtime/my_demo_001"
```

prepare 拒绝非空目录；再次 start 保留数据库和匿名编号，不重复 seed。Windows 后台隐藏窗口，stop 核对本次记录的 PID/命令，只停止这些进程及其子进程。不提供删除原库的 reset。`--no-frontend` 用于仅启动后端/worker。

独立固定 20 轮专项会创建另一专用测试后端，分母始终 40 条和 20 轮：

```powershell
Set-Location backend
& $py236 tools/replay_twenty.py --output-dir "$PWD/../runtime/twenty_new_evidence"
$env:MODULE24_EVIDENCE="$PWD/../runtime/pytest_evidence"
& $py236 -m pytest tests -q --junitxml="$PWD/../runtime/pytest.xml"
```

证据默认不含真实数据/凭证。专项有正常、故障前、恢复后独立统计，真实本地 HTTP、503、响应已保存但 ACK 前终止、身份暂停和新 PID 恢复。详见 `backend/examples/twenty_usage.md`。浏览器命令及实际 PDF 生成方法在 `docs/development/frontend.md`；需要专用虚构登录，脚本会增加隔离 UI 分页测试会话并提交/恢复更正版本。

## 运行机制和对接

`Outbox(..., upload_policy='after_close')` / CLI `ROBOT_UPLOAD_POLICY=after_close` 封存后才开始 HTTP；旧默认 streaming 保留。callback 用 enqueue_async，最终文本/身份/稳定 ID/文本终态/播放依据由 2.1 提供。云端记录 API 不推理。独立 `python -m app.care.worker` 扫描持久消息，以 owner/record/revision/engine/version/config 唯一任务，支持租约、有限重试和过期尝试 fencing。结果与策略同事务提交。

`care_core` 仅 Python 标准库，可供未来树莓派调用 `local_preview`（不持久、不入报告），详细协议、事先规则预期、支持/安全模板和 Ollama 适配见 `backend/care_core/README.md`。正式模型必须显式配置；错误不静默替换规则成功。支持策略只证明本地模拟接收，永久 `simulated_*`，不能表示语音已改变或硬件已执行。关闭后云端分析不能追溯改变已播放内容。

原始转录不修改；更正有 request_id 幂等和 base_revision 冲突，A→B→A 仍是新输入版本。删除调用原 DELETE，同事务清除更正、输入快照、结果、策略、回执；旧 worker 不可复活。仅留下原 2.4 最小 tombstone，以及 owner 绑定 HMAC 的已删除资源引用（无原 ID/正文，归属该 tombstone），以本人 410/他人 404 保持错误语义。更换密钥会令旧 JWT/游标失效，旧匿名删除引用退为不可定位 404；部署密钥需持久保管。

`/api/robot-insights` 只接受现有 User JWT，不接受 body/query owner。带签名的游标绑定 owner/scope/snapshot，敏感响应 no-store。量表 fixture 独立文件和专用库开关，production 禁止。live 仅查看既有量表记录，缺记录级版本/确认完成时间/审核依据则 unverified，不用当前模板回填或重算。将来由 2.5 提供经确认的记录级信息后扩展映射。

报告由临时 ReportDTO 同时供预览/打印，不在数据库保存报告正文。时间范围左闭右开，消息用 occurred_at、量表用确认 completed_at；指定会话不猜量表关联。按同来源/同版本分组，至少两个独立有效来源才展示变化，不给临床总分或自动好转/恶化结论。

## 生产和边界

公司合并/数据库升级/备份恢复/服务模板详见 `docs/operations/deployment.md`；配置清单见 `docs/reference/configuration.md`。Linux/systemd/Nginx 是待实机核对模板，未部署公司或树莓派。真实模型、内容审核、真实语音、有效量表、Pi、公司环境、实际动作均需 X01—X07 后续独立验证。原前端基线缺 13 个静态媒体文件，新增入口不依赖这些文件，原首页媒体未补齐；前端依赖 audit 记录和上线前修复边界见交付交接说明。
