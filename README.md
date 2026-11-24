# 心理疏导机器人系统

面向树莓派终端的心理陪伴平台，提供账号登录、豆包实时语音、对话记录、PHQ-9／GAD-7对话辅助采集、情绪趋势和用户评估报告。管理员可远程查看报告，并对需要关注的用户进行人工联系。

**[使用手册](docs/USER_MANUAL.md) · [开发交接](docs/PROJECT_HANDOFF_2026-11-22.md) · [后台检查与待办](docs/features/report-backend-audit-2026-11-23.md) · [全部文档](docs/README.md)**

本页更新于2026年11月24日。当前架构为“终端运行用户服务，服务器统一存储数据并提供管理员服务”。辅助评分、情绪分类和模型提示不构成医学诊断。

## 当前功能

| 功能 | 当前实现 |
|---|---|
| 账号与个人资料 | 用户账号隔离；姓名、性别、年龄可选填；紧急联系人姓名、电话及同意确认必填，老账号可补填 |
| 实时语音 | 豆包语音、字幕、打断、四种音色和语速调节；结束后确认保存 |
| 对话与续答 | 同账号可有多段对话；未完成的采集任务保留，后续会话在合适时继续 |
| 量表采集 | 按线索采集PHQ-9／GAD-7；依据已确认答案统计，独立任务和回顾窗口不混合 |
| 九区评估报告 | 本次对话、近72小时、近168小时；共享网页预览和PDF打印样式 |
| 情绪变化趋势 | 多日报告每段会话一个点，本次按用户发言顺序；缺失留空，单点不连线 |
| 管理员端 | 按用户查看报告、导出PDF、查看待联系提醒、确认已人工跟进 |
| SEGA实验接口 | 作者权重推理与输入提取链路；目标设备适配和实际筛查效果仍需验证 |

### 报告与评分

报告包括流程、基础信息、量表评分、按需量表、情绪曲线、风险线索、三类摘要、关怀建议和扫码续答占位区。

- 综合分采用PHQ-9九项与GAD-7七项的16项口径，满分48分；部分作答按项目规则估算，0题不计分。
- 页面中的“置信度”表示有效作答占16题的完成率，不是医学准确率或患病概率。
- 情绪参考分由积极／中性／消极分类映射为100／50／0，多日报告在每段会话内取平均；与量表分和SEGA二分类分开。
- 风险与摘要目前主要基于上下文规则、主题词和原话摘录；复杂隐含表达可能漏判，信息不足时不补造结论。

详细口径见[报告模板说明](docs/features/user-report-template.md)和[后台检查](docs/features/report-backend-audit-2026-11-23.md)。

### 人工联系提醒

已保存记录出现明确安全关注线索时，管理员页面每30秒检查并显示待联系提醒、登记联系人及相关会话。管理员核实并人工联系后，可确认“已人工跟进”；来源变化后会重新核验。

**系统没有自动短信、自动拨号或页面关闭后的独立推送。**没有提醒不能证明没有风险，人工确认也不等于已经确认用户安全。

## 部署分工

| 位置 | 组件与职责 |
|---|---|
| 树莓派或开发电脑 | Next.js用户网页、FastAPI用户服务、语音连接、分析worker、量表任务与报告取数 |
| 服务器 | PostgreSQL统一保存账号、资料、对话、答案、进度、结果和审计；管理员网页与报告API |
| 外部服务 | 豆包实时语音及配置启用的模型服务 |

用户在终端本机HTTP页面操作，终端通过受限SSH连接服务器数据库。管理员使用独立的服务器访问入口，中央服务不运行模型推理。原SQLite单机模式保留兼容，正式终端数据不回退到本地空库。

部署、权限与私有配置见[树莓派本地运行和服务器保存](docs/operations/edge-central.md)。

## 启动与使用

### 已配置的Windows开发电脑

1. 双击 [Open-NormalMode.cmd](Open-NormalMode.cmd)，保留当前数据启动普通模式。
2. 在Chrome打开启动器给出的登录地址。当前开发电脑为 `http://127.0.0.1:51078/login`，其他机器以实际输出为准。
3. 注册或登录；旧账号先在“个人资料”补齐紧急联系人，再开始新的语音对话。
4. 结束对话后等待保存确认，进入报告页选择范围，点击“更新并打印 / 保存 PDF”。
5. 管理员运行 [Open-ServerReports.cmd](Open-ServerReports.cmd)，使用授权账号查看服务器报告与待联系提醒。

| 操作 | 入口 |
|---|---|
| 安装与配置 | [快速开始](docs/getting-started.md)、[Setup-Project.ps1](Setup-Project.ps1) |
| 普通模式 | [Open-NormalMode.cmd](Open-NormalMode.cmd) |
| 独立快速演示 | [Open-CollectionDemo.cmd](Open-CollectionDemo.cmd)；[演示说明](docs/operations/collection-demo.md) |
| 停止本项目 | [Stop-Project.cmd](Stop-Project.cmd) |
| 完整操作步骤 | [使用手册](docs/USER_MANUAL.md) |

### 页面入口

| 页面 | 路径 |
|---|---|
| 注册与登录 | `/login` |
| 个人对话空间 | `/robot-care` |
| 个人资料与联系人 | `/robot-care/profile` |
| 语音陪伴 | `/robot-care/voice` |
| 量表进度 | `/robot-care/assessments` |
| 评估报告 | `/robot-care/report` |
| 服务器管理员端 | `/care-admin` |

不同账号的对话隔离，同一账号的量表任务可跨会话延续。结束时未确认保存的数据不能视为已入库；正式终端需要服务器网络连接。

## 从GitHub接手开发

```bash
git clone https://github.com/oGasshow/psychological-care-robot.git
cd psychological-care-robot
```

使用Python 3.13及以上、Node.js 22，按锁文件安装依赖并重新构建前端。先读[使用手册中的接手与安装步骤](docs/USER_MANUAL.md#9-新开发者从github接手)，再看[开发指南](docs/development/guide.md)。

源码不包含真实API密钥、SSH私钥、业务数据库、`runtime/`、虚拟环境或构建缓存。模型文件通过[模型权重交接附件](docs/operations/model-release.md)取得；已获服务器运维权限的接手人可按[私有运行资料取得说明](docs/operations/private-runtime-handoff.md)下载授权资料。私有归档是旧快照，应用源码以最新main为准。

服务器升级须准备资料表和受限账号权限，方法见[注册资料与数据库升级](docs/features/registration-profile.md)。树莓派安装使用最新源码重新生成的私有终端包，不能把Windows虚拟环境或`node_modules`直接复制到ARM。

## 验证范围与后续任务

已完成Windows本地与服务器管理员服务的联调；保留113项针对性回归、41项PostgreSQL隔离检查及7项页面检查结果，测试范围重叠，不相加为全项目测试总数。PDF已验证常规单页和长内容分页。

后续重点：

- 在真实树莓派验证安装、麦克风、扬声器、性能、断网及断电恢复。
- 核验SEGA输入口径、CPU／ARM运行及真人误报漏报，不能把作者权重已加载等同于效果达标。
- 增强风险语义复核与三类摘要抽取，并使用独立标注数据评估。
- 验证管理员值守、紧急联系人可用性和人工联系流程。
- 手机扫码续答、微信小程序、原生App、短信及自动外呼尚未交付。

详细状态见[后台检查与剩余任务](docs/features/report-backend-audit-2026-11-23.md)，历史记录见[项目交接](docs/PROJECT_HANDOFF_2026-11-22.md)。

## 仓库结构

```text
backend/       FastAPI、分析worker、模型适配、后台工具与测试
frontend/      Next.js用户端、管理员端与PDF报告组件
device/        终端适配器
deploy/        部署脚本、服务文件和配置示例
tools/         打包、交接与仓库检查工具
docs/          使用手册、功能说明、部署与历史归档
runtime/       本机运行资料，不提交Git
```

## 项目来源

基于 [Ethanwhh/xinyi](https://github.com/Ethanwhh/xinyi) 增量开发，保留 [MIT协议与版权署名](LICENSE)。[上游介绍归档](docs/upstream/xinyi-original.md)与[来源清单](docs/upstream/baseline.json)用于追溯原始项目，当前功能以本页和最新使用手册为准。
