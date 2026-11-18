# 心理疏导机器人系统

面向辅助陪伴机器人的软件项目，包含 Windows 语音交流、对话记录、逐句用户情绪分析、对话辅助量表采集和近期报告。沿用 FastAPI、Next.js、SQLite 与既有账号体系，保留树莓派终端接口。

## 从这里开始

**新版机器人工作台入口是 `/robot-care`，语音页是 `/robot-care/voice`。** 仓库保留了原项目首页 `/` 和原有功能路由；看到这些页面不能据此判定代码版本。先登录 `/login`，再进入机器人工作台。

下表中的 `.cmd`、`.ps1` 启动器适用于 **Windows**。Linux／树莓派运行整套后端时，请看[部署说明](docs/operations/deployment.md#linux树莓派运行整套后端时的版本核查)，不要照搬 Windows 本机运行目录和模型路径。

| 你想做什么 | 阅读或运行 |
|---|---|
| 正常模式：完整采集与跨会话跟进 | [Open-NormalMode.cmd](Open-NormalMode.cmd) |
| 快速演示：短对话采集到实际计分 | [Open-CollectionDemo.cmd](Open-CollectionDemo.cmd)；[演示步骤与两个入口](docs/operations/collection-demo.md) |
| 第一次安装、启动项目 | [快速开始](docs/getting-started.md) |
| 继续本机已有对话数据 | 根目录 [Resume-Project.cmd](Resume-Project.cmd) |
| 新建固定演示数据 | [Start-Presentation.cmd](Start-Presentation.cmd)；会切到新的演示库 |
| 查看能力与待修问题 | [当前状态与已知问题](docs/status.md) |
| 找功能、配置、部署或历史交接 | [文档导航](docs/README.md) |
| 继续开发、运行检查 | [开发指南](docs/development/guide.md) |

## 当前能力

- **语音与记录**：豆包全双工语音、字幕、播放与打断；双方最终文字经持久队列在通话中同步，结束时完整归档，支持失败补传。
- **单次对话报告**：结束并保存后，从本次记录进入报告，或在 `/robot-care/report` 选择一场已归档会话。报告使用本次对话生成情绪概况、总结、建议和必要的关怀提示，可打印为 PDF。部分回答按已确认条目计小计，采集覆盖率为已确认条目数除以量表总条目数。详见[对话报告](docs/features/reports.md)。
- **对话采集**：支持 PHQ-9 / GAD-7 辅助信息整理，按账号保留未完成任务，缺项不补分。
- **快速采集演示**：独立数据、网页与构建目录；一句近况可触发3项自定义指标，依据实际确认回答计分，结果标记演示。
- **SEGA 实验分析**：已接入录音参与选项、三组问答音频的异步实验提取、作者权重推理及上下游服务接口；需在部署机器单独配置模型环境和资源。作者特征口径等效性尚未验证，跟进查询标记尚未自动驱动量表推送。详见[SEGA接入](docs/features/sega.md)。

源码更新不等于运行环境迁移：`backend/.env`、数据库、模型权重、`runtime/` 和前端构建均不随 Git 分发。新机器需要配置自身环境、重新构建前端并重启实际运行的服务。不要用本机演示数据或私有配置文件覆盖另一台机器的现有数据。

连续真实语音中的采集流程仍有等待过久、停止误判和确认漏接问题，详见[已知问题](docs/status.md#尚待修复与验证)。本项目用于辅助陪伴，分析、辅助合计与报告不构成诊断。

## 仓库结构

```text
backend/       FastAPI、记录队列、分析 worker、模型适配与测试
frontend/      Next.js 网页、报告组件与浏览器检查
device/        Windows / 树莓派语音终端适配器
deploy/        服务与反向代理部署模板
tools/         仓库检查、交付复核与回归工具
docs/          使用、功能、架构、部署和历史归档
runtime/       本机运行数据与模型资源，不提交 Git
```

根目录的 Windows 安装、启动、继续与停止脚本保持固定位置，方便日常双击使用。依赖、数据库、凭证及本机验证回执由运行环境生成。

## 项目来源

基于 [Ethanwhh/xinyi](https://github.com/Ethanwhh/xinyi) 增量开发，保留 [MIT 协议及版权署名](LICENSE)。上游介绍与复制基线分别保存在[原始介绍归档](docs/upstream/xinyi-original.md)和[来源清单](docs/upstream/baseline.json)；当前功能以本文和[当前状态](docs/status.md)为准。
