# 心理疏导机器人系统

面向辅助陪伴机器人的软件项目，包含 Windows 语音交流、对话记录、逐句用户情绪分析、对话辅助量表采集和近期报告。沿用 FastAPI、Next.js、SQLite 与既有账号体系，保留树莓派终端接口。

## 从这里开始

| 你想做什么 | 阅读或运行 |
|---|---|
| 第一次安装、启动项目 | [快速开始](docs/getting-started.md) |
| 继续本机已有对话数据 | 根目录 [Resume-Project.cmd](Resume-Project.cmd) |
| 新建固定演示数据 | [Start-Presentation.cmd](Start-Presentation.cmd)；会切到新的演示库 |
| 查看能力与待修问题 | [当前状态与已知问题](docs/status.md) |
| 找功能、配置、部署或历史交接 | [文档导航](docs/README.md) |
| 继续开发、运行检查 | [开发指南](docs/development/guide.md) |

## 当前能力

- **语音与记录**：豆包全双工语音、字幕、播放与打断；双方最终文字经持久队列在结束后上传，支持失败补传。
- **分析与回顾**：只对用户发言做情绪分类；明确危险表达独立提示；支持转录更正、历史查询、近期报告及打印。
- **对话采集**：支持 PHQ-9 / GAD-7 辅助信息整理，按账号保留未完成任务，缺项不补分。
- **SEGA 实验分析**：已运行作者权重并接入实验接口；实时语音的同口径自动特征提取尚未接通。

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
