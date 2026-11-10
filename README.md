# 心理疏导机器人系统

面向心理疏导与辅助陪伴机器人的软件项目。本仓库用于项目开发、版本管理和本地复现；当前增量开发覆盖对话文字记录与上传、异步规则分析、网页查询和打印报告。

当前本地演示使用虚构数据。真实语音、正式模型、有效量表、公司环境和树莓派仍需后续接入与验证。

## 当前功能

- **记录与上传**：保存对话文字，支持会话结束后上传、失败补传和幂等去重。
- **异步分析**：独立 worker 处理持久化记录，生成规则情绪分类和支持提示。
- **历史与更正**：查看历史记录，更正转录时保留原文及输入版本。
- **量表与趋势**：只读展示量表记录，按来源、版本及测试属性分组，保留缺失和未核验状态。
- **报告与打印**：生成带来源引用和数据性质说明的陪伴记录摘要，支持预览及 PDF 打印。
- **安装与复核**：按锁文件安装项目独立环境，提供本地演示、回归和进程停启检查入口。

本轮开发集中于 2.3／2.4／2.6；2.1 的真实音频与策略链路、2.5 的确认量表记录仍需整项目联调。

## 文档入口

| 文档 | 内容 |
|---|---|
| [项目开发交接（2026-11-10）](docs/项目开发交接_20261110.md) | 当前版本、启动与预置、代码地图、接口、验证证据和后续任务 |
| [安装与交付复现](README_RELEASEPREP.md) | 前置工具、锁文件安装、演示启动、完整复核和已知问题 |
| [2.3／2.6 与 2.4 增补](README_MODULE236.md) | 增量模块的接口、运行机制和来源语义 |
| [2.4 记录模块](README_MODULE24.md) | 记录上传模块说明 |
| [功能与整项目部署简述](功能与整项目部署简述.md) | 当前功能、服务器与树莓派接入关系 |
| [部署与迁移](docs/部署与迁移.md) | 服务部署、迁移、备份与恢复说明 |
| [配置与协议](docs/配置与协议.md) | 配置项和模块对接协议 |

安装时优先阅读 [安装与交付复现](README_RELEASEPREP.md)；其他模块文档保留了前轮开发记录。

## 本地运行

Windows 安装依赖后，可直接双击根目录中的脚本：

- [Start-Project.cmd](Start-Project.cmd)：恢复固定汇报对话，启动接口、分析 worker 和网页。
- [Start-Presentation.cmd](Start-Presentation.cmd)：同上，每次恢复 3 段、共 12 条虚构对话：日常积极、孤独担忧、明确危险表达，并恢复最初的 3 条虚构量表结果（5、7、4 分；demo-v1、demo-v1、demo-v2；原始 2026 年 10 月完成时间）。报告未保存范围时，默认起始月会覆盖这些演示量表，仍可自行调整范围。
- [Resume-Project.cmd](Resume-Project.cmd)：继续最近一次运行的数据，不清空。
- [Start-API.cmd](Start-API.cmd)：仅启动接口和分析 worker，打开接口文档。
- [Stop-Project.cmd](Stop-Project.cmd)：停止上述脚本启动的服务。

启动窗口显示实际访问地址和本机虚构演示账号；构建过程中请等待完成。脚本使用项目自己的 `.venv`。每次汇报启动使用独立的 `runtime/presentation_时间戳` 目录，恢复固定对话，不导入旧更正稿或现场操作残留；旧数据库完整保留。继续同一次汇报的数据请使用 Resume-Project.cmd。对话记录页的“新增演示对话”支持现场输入用户文字及可选的手动助手文字，保存后进入真实记录、后台规则分析和报告链路，所有内容标记为模拟数据，不调用真实模型。新增入口只在专用本地开发演示环境开放，生产环境禁用。未安装依赖时，先按以下步骤运行 Setup-Project.ps1。

报告顶部单列明确危险表达提示，并列出当前有效用户对话中的触发表达、来源和修订版本；否认、引用、他人转述及普通消极情绪不按明确危险表达计入，量表分数不触发该提示。提示不依赖模型或分析任务完成，需要人工核实，不作临床风险等级判断。

已在 Windows 验证的工具组合为 Node.js 22.14.0、npm 10.9.2、uv 0.13.6、Python 3.13.18 和已安装的 Microsoft Edge。

在 PowerShell 中克隆并安装：

```powershell
git clone https://github.com/oGasshow/psychological-care-robot.git
Set-Location psychological-care-robot
./Setup-Project.ps1 -UvExecutable '<uv可执行文件路径>' -PythonExecutable '<Python可执行文件路径或3.13.18>'
```

安装脚本创建本项目 `.venv`，按 `backend/uv.lock` 安装后端开发依赖，通过 `npm ci` 安装前端，并检查工具版本、依赖一致性和锁文件哈希。工具在 PATH 中时也可使用脚本默认参数；完整参数见安装文档。

准备并启动专用虚构演示：

```powershell
./.venv/Scripts/python.exe backend/tools/demo_care.py prepare --runtime runtime/my_demo_001
./.venv/Scripts/python.exe backend/tools/demo_care.py start --runtime runtime/my_demo_001
```

打开 `start` 输出的 `/robot-care` 地址。虚构账号和随机密码保存在本机 `runtime/my_demo_001/access.json`，不提交到 GitHub。`prepare` 需要新的运行目录；首次 `start` 会构建前端并启动 API、分析 worker 和 Next.js。

停止本次演示：

```powershell
./.venv/Scripts/python.exe backend/tools/demo_care.py stop --runtime runtime/my_demo_001
```

重复启动保留同一演示库的数据。安装环境和运行数据由本机生成，不随仓库分发。

## 验证状态

已独立验收的本地 L1 基线为 `9355597`。2026-11-04 的依赖治理代码 `ab7cc35` 在同一 Windows 的新解包目录中完成了开发自测：

- 原 180 个主测试和 31 个子项通过。
- 固定 40 条记录／20 轮真实本机 HTTP 专项，以及故障补传恢复通过。
- 28 个真实网页检查通过。
- 7 类 PDF 共 25 页已逐页检查。
- Windows 三服务停止、重复停止、重启及同库数据保留检查通过。

该轮开发自测仍待独立验收，不代表公司或整机生产上线完成。原始日志、审计结果与自测回执保存在本地对应开发交付目录中。

当日最终 npm 全量审计的 high／critical 均为 0，生产依赖告警为 0；全量保留 16 个已说明的 moderate lint 依赖条目。全仓 lint 仍有 12 个旧错误和 20 个警告，基线对照无新增诊断。审计是当日快照，后续应重新检查，详见安装文档。

真实模型、正式内容审核、真实语音与策略、有效量表、树莓派、公司环境和安全动作继续保留为未验证项；Linux 生命周期仅做 mock。报告用于辅助陪伴记录展示，不作诊断依据。

## 项目来源

本项目在 [上游项目](https://github.com/Ethanwhh/xinyi) 的基础上增量开发。上游的原始介绍单独保存在 [上游原始 README](docs/upstream/README_XINYI.md)，其中的相对链接仍按原项目结构保留。

仓库保留原 [MIT 协议及版权署名](LICENSE)。当前项目的功能、运行入口和验证状态以上述说明及对应模块文档为准。
