# 文档导航

[返回项目首页](../README.md)

新读者先看[快速开始](getting-started.md)，接手开发先看[当前状态与已知问题](status.md)和[开发指南](development/guide.md)。历史交接记录当时的实现与验证，不作为当前能力承诺。

## 使用与功能

| 文档 | 内容 |
|---|---|
| [快速开始](getting-started.md) | 安装、首次启动、保留数据继续运行、页面入口 |
| [语音与终端接口](features/voice.md) | Windows 语音、豆包配置、终端适配与连接恢复 |
| [逐句情绪与危险表达](features/sentiment.md) | 用户分类、独立提示、版本与重试 |
| [对话辅助量表采集](features/screening.md) | 触发、持久任务、候选、确认与跨会话依据 |
| [近期陪伴报告](features/reports.md) | 报告模板、来源统计、模型文字与打印 |
| [SEGA 实模型实验接入](features/sega.md) | 作者权重、实际验证、特征契约与未完成部分 |

## 架构、配置与部署

| 文档 | 内容 |
|---|---|
| [记录与上传模块](architecture/recording.md) | 记录 API、持久队列、幂等、终态与原始基线 |
| [分析与报告模块](architecture/insights.md) | 分析任务、输入修订、支持策略与来源边界 |
| [配置与接口索引](reference/configuration.md) | 服务端配置、核心接口与专项配置入口 |
| [安装与交付验证](operations/installation.md) | 工具、依赖锁、隔离演示与交付复核命令 |
| [部署与数据库迁移](operations/deployment.md) | 备份恢复、服务模板、公司与 Pi 对接 |
| [当前状态与已知问题](status.md) | 已实现能力、未完成环节及验证口径 |

## 开发与局部说明

| 文档 | 内容 |
|---|---|
| [开发指南](development/guide.md) | 代码地图、检查入口与文档维护约定 |
| [前端开发与浏览器验证](development/frontend.md) | 同源接口、构建、浏览器与 PDF 检查 |
| [care_core 模块说明](../backend/care_core/README.md) | 独立规则内核与本地预览协议 |
| [固定二十轮回放](../backend/examples/twenty_usage.md) | 独立记录上传回放工具 |
| [合成触发音频来源](../backend/app/voice/assets/README.md) | 后台结构化模型调用使用的音频素材 |
| [报告组件许可](../frontend/src/components/report-ui/LICENSE.shadcn.md) | 复用组件来源及许可 |

## 历史归档与来源

这些文档保留原日期、基线和结论；文件链接已按新结构更新。遇到历史“尚未接通”或“已完成”表述，先核对[当前状态](status.md)。

| 文档 | 归档内容 |
|---|---|
| [2026-11-12 开发交接](archive/handoffs/2026-11-12.md) | 情绪、风险提示、持久任务与 SEGA 开发记录 |
| [2026-11-11 开发交接](archive/handoffs/2026-11-11.md) | 语音、报告模型及当时采集范围 |
| [2026-11-10 开发交接](archive/handoffs/2026-11-10.md) | 预置演示、代码地图与早期验证 |
| [2026-11-04 旧功能部署简述](archive/2026-11-04-overview.md) | 依赖治理时的功能与部署口径 |
| [D01—D04 修复记录](archive/fixes/d01-d04.md) | 配置回退、来源分流、provider 与进程生命周期 |
| [进程停止归属说明](archive/fixes/process-ownership.md) | Windows 身份核验与 Linux mock 边界 |
| [上游原始介绍](upstream/xinyi-original.md) | 上游介绍快照，文件及图片链接指向原仓库 |
| [复制基线与来源清单](upstream/baseline.json) | 原提交、原始文件哈希与稀疏快照记录 |
