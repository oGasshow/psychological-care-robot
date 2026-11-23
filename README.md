# 心理疏导机器人系统

**使用先读：[最新使用手册](docs/USER_MANUAL.md)。开发接手再读：[项目交接与后续任务](docs/PROJECT_HANDOFF_2026-11-22.md)。**

2026-11-23：用户与管理员报告接入九区 PDF 模板，近三天／近七天按72／168小时的会话段展示情绪；新增必填紧急联系人、老账号补填和管理员待联系提醒。见[报告计分说明](docs/features/user-report-template.md)与[后台审查](docs/features/report-backend-audit-2026-11-23.md)。

面向辅助陪伴机器人的软件项目。网页提供豆包实时语音、对话记录、逐句情绪分析、PHQ-9／GAD-7 对话辅助采集和报告。服务端使用 FastAPI、分析 worker、Next.js 和 SQLite。

当前设备部署采用[树莓派本地运行、服务器统一保存](docs/operations/edge-central.md)：新增 edge/central 角色和服务器 PostgreSQL，用户在本地 HTTP 页面操作；服务器只保存业务数据并提供管理员报告。原 SQLite 单机模式保留兼容。

## 2026-11-19 历史验收记录

当时验收应用为 [`4a6d4f2`](https://github.com/oGasshow/psychological-care-robot/commit/4a6d4f254930f83e3e8195c1a68ab9f95c4df07e)，用于保留历史对照。当前接手应使用最新main及[使用手册](docs/USER_MANUAL.md)，终端／中央分工以新版说明为准。

本版已在 Windows 普通模式使用独立测试账号和合成用户语音走完真实豆包链路。单次对话自动保存 PHQ-9 9/9 项、GAD-7 7/7 项，量表页、单次报告与打印视图分别核对为 10/27 分和 7/21 分。该结果属于软件联调，树莓派整机和现场音频仍需在目标设备验收。

## 从这里开始

**先到 `/login` 注册或登录。** 普通用户进入 `/robot-care`，每次对话独立保存；授权管理账号进入 `/care-admin`，查看各用户报告。首页 `/` 自动进入个人空间，未登录时进入登录页。语音入口为 `/robot-care/voice`，量表入口为 `/robot-care/assessments`，个人单次报告入口为 `/robot-care/report`。管理账号配置与小程序/App接口见[关怀报告管理端](docs/features/report-management.md)。

下表中的 `.cmd` 和 `.ps1` 启动器适用于 Windows。树莓派通过 systemd 运行 API、worker 和网页服务。

| 你想做什么 | 阅读或运行 |
|---|---|
| 用户、管理员与新开发者的完整操作 | [最新使用手册](docs/USER_MANUAL.md) |
| 正常模式：启动当前本地版本并保留已有对话 | [Open-NormalMode.cmd](Open-NormalMode.cmd) |
| 快速演示：短对话采集到实际计分 | [Open-CollectionDemo.cmd](Open-CollectionDemo.cmd)；[演示步骤与两个入口](docs/operations/collection-demo.md) |
| 第一次安装、启动项目 | [快速开始](docs/getting-started.md) |
| 继续本机已有对话数据 | 根目录 [Resume-Project.cmd](Resume-Project.cmd) |
| 新建固定演示数据 | [Start-Presentation.cmd](Start-Presentation.cmd)；会切到新的演示库 |
| 查看能力与待修问题 | [当前状态与已知问题](docs/status.md) |
| 找功能、配置、部署或历史交接 | [文档导航](docs/README.md) |
| 继续开发、运行检查 | [开发指南](docs/development/guide.md) |

## 当前能力

- **语音与记录**：豆包全双工语音、字幕、播放与打断；可以说“结束吧”或点击“结束并保存”。双方最终文字经持久队列在通话中同步，结束时完整归档，支持失败补传。
- **账号展示**：陪伴工作台显示登录用户名，新注册账号也通过同一个账号接口读取用户名。
- **九区评估报告**：在 `/robot-care/report` 选择本次、近72小时或近168小时，查看登记资料、综合分、按需量表、会话情绪趋势、摘要与建议，打印或保存PDF；管理员读取同一口径。部分作答的综合分为项目估算，“置信度”按完成率表示，非医学准确率。
- **人工联系提醒**：已保存记录出现明确安全线索时，管理员页面展示待联系提醒及登记联系人。由管理员人工联系并确认跟进，不自动发短信或拨打电话。
- **对话采集**：普通模式从首条有效发言开始判断。已有采集线索且适合继续时，最迟在第 4 轮回复问清一项近两周频率，用户在第 5 轮明确回答后可直接保存。出现两类线索时可穿插采集 PHQ-9 和 GAD-7。用户明确邀请继续提问时，可补问后续未确认项。详见[普通版短对话验收](docs/features/screening.md#普通版短对话验收)。
- **删除对话**：对话历史和详情均可删除已结束的会话。确认后，该对话的转录及关联结果将移除。
- **语音量表结果**：通话中自然追问频率，单次报告和量表页从本次完整语音转录核对已确认的回答，再显示小计。参见[语音回答与旧记录核对](docs/features/screening.md#语音回答与旧记录核对)。
- **快速采集演示**：独立数据、网页与构建目录；一句近况可触发3项自定义指标，依据实际确认回答计分，结果标记演示。
- **SEGA 实验分析**：保留作者权重推理、问答音频特征提取及上下游接口；需在目标机器单独配置模型环境和资源，输入口径、CPU／ARM及真人效果仍需验证。不能把class=0/1当作临床诊断。详见[SEGA接入](docs/features/sega.md)。

源码更新不等于运行环境迁移：`backend/.env`、数据库、模型权重、`runtime/` 和前端构建均不随 Git 分发。新机器需要配置自身环境、重新构建前端并重启实际运行的服务。不要用本机演示数据或私有配置文件覆盖另一台机器的现有数据。

现场请核验麦克风、扬声器、网络及语音中断后的保存。部分会话只有已答小计。辅助合计与报告供陪伴参考，诊断由专业人员完成。[当前状态与已知问题](docs/status.md#尚待修复与验证)

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
