# 快速开始

[文档导航](README.md) · [当前状态与已知问题](status.md)

本文命令均从仓库根目录执行。Windows 安装和启动脚本保留在根目录；网页地址与账号以本次启动窗口输出为准，端口可能变化。

## 1. 安装项目依赖

准备 Node.js、npm、uv、Python 和用于开发验证的本机 Edge。已验证的版本与完整参数见[安装与交付验证](operations/installation.md)，Python 与前端依赖分别按 backend/uv.lock 和 frontend/package-lock.json 安装。

```powershell
git clone https://github.com/oGasshow/psychological-care-robot.git
Set-Location psychological-care-robot
./Setup-Project.ps1
```

工具不在 PATH 时，传入本机已有可执行文件位置：

```powershell
./Setup-Project.ps1 -UvExecutable '<uv路径>' -PythonExecutable '<Python路径或3.13.18>'
```

脚本创建本项目 .venv 并安装锁定依赖。不要复制其他项目的 venv 或 node_modules 代替安装。

## 2. 配置需要的模型功能

纯本地演示可以使用规则引擎。语音、豆包语义分类和模型报告需在忽略的 backend/.env 或服务进程环境配置有效接口；复制字段时使用[语音样例](../backend/.env.voice.example)和[报告样例](../backend/.env.report.example)，不要把示例占位值当成凭证。

| 功能 | 配置说明 |
|---|---|
| 豆包语音与 Windows/Pi 终端 | [语音说明](features/voice.md) |
| 逐句用户情绪分类 | [情绪分析](features/sentiment.md) |
| 报告文字生成 | [报告配置](features/reports.md) |
| 对话辅助采集与持久任务 | [采集说明](features/screening.md) |
| SEGA 隔离模型环境与权重 | [实验接入](features/sega.md) |

## 3. 选择启动方式

| 脚本 | 用途与数据行为 |
|---|---|
| [Open-NormalMode.cmd](../Open-NormalMode.cmd) | 正常模式入口；健康的服务直接打开，保留完整采集与当前数据 |
| [Open-CollectionDemo.cmd](../Open-CollectionDemo.cmd) | 快速采集演示入口；独立数据库与网页，3项确认后可显示实际合计；见[短演示步骤](operations/collection-demo.md) |
| [Stop-CollectionDemo.cmd](../Stop-CollectionDemo.cmd) | 仅停止快速演示，正常模式继续运行 |
| [Resume-Project.cmd](../Resume-Project.cmd) | 继续当前 active_runtime 的数据；日常调试优先使用 |
| [Start-Presentation.cmd](../Start-Presentation.cmd) | 新建独立演示目录，恢复固定虚构对话和模拟量表，并切换 active_runtime |
| [Start-Project.cmd](../Start-Project.cmd) | 与固定演示入口相同，会切换到新演示库 |
| [Start-API.cmd](../Start-API.cmd) | 仅启动 API 与分析 worker |
| [Stop-Project.cmd](../Stop-Project.cmd) | 按受控进程台账停止当前服务 |

切到新演示库不会删除旧目录，但页面会看到另一套数据。希望继续已有对话时使用 Resume-Project.cmd。启动器的具体行为在 [Run-Project.ps1](../Run-Project.ps1)。

启动窗口显示网页地址和本机演示账号。首次启动可能需要构建前端；运行数据、私有账号和日志保存在 runtime/，不提交 Git。

## 4. 进入对应页面

登录启动窗口给出的地址后：

- `/robot-care`：历史会话、用户情绪与报告入口。
- `/robot-care/voice`：开始语音、实时字幕、结束并保存；调试时可看本人当前后台阶段。
- `/robot-care/assessments`：未完成采集任务、各会话进度、已确认条目，以及折叠的模拟量表。
- `/robot-care/report`：近期回顾、独立危险表达提示与打印。

结束语音并等待保存确认后，再刷新历史和采集结果。候选信息、未完成项和已确认条目是不同状态；未齐不出总分。连续语音采集还有[尚待修复的问题](status.md#尚待修复与验证)。

独立演示目录、备份恢复、部署和完整验证分别见[安装与验证](operations/installation.md)、[部署与迁移](operations/deployment.md)及[开发指南](development/guide.md)。
