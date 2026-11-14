# 开发指南

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

以下命令从仓库根目录执行；前端命令明确使用 `npm --prefix frontend`。安装方法见[安装与交付验证](../operations/installation.md)。

## 代码地图

| 路径 | 职责 |
|---|---|
| [backend/app](../../backend/app) | 既有账号、原生聊天与 FastAPI 主应用 |
| [backend/robot_client](../../backend/robot_client) | 客户端持久 Outbox、上传与重试 |
| [backend/app/robot_records.py](../../backend/app/robot_records.py) | 双方最终文字的记录接口、归属与删除 |
| [backend/app/care](../../backend/app/care) | 异步分类、修订、策略、报告与来源查询 |
| [backend/care_core](../../backend/care_core) | 可独立调用的规则、安全信号与预览内核 |
| [backend/app/voice](../../backend/app/voice) | 豆包桥接、阶段、持久任务、自然回答与 SEGA 适配 |
| [frontend/src/app/robot-care](../../frontend/src/app/robot-care) | 历史、语音、采集、报告等页面 |
| [frontend/src/components](../../frontend/src/components) | 语音控制、结果与报告组件 |
| [device](../../device) | 终端语音适配器及可选音频依赖 |
| [deploy](../../deploy) | 服务与反向代理模板 |

## 常用检查

```powershell
# 文档本地链接、旧文档路径残留和导航可达性
./.venv/Scripts/python.exe -X utf8 tools/check-docs.py

# 后端工程回归；默认使用隔离测试库，不调用真实云模型
./.venv/Scripts/python.exe -X utf8 -m pytest backend/tests -q

# 前端完整 lint、类型与构建，随后核对剩余警告是否有新增
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run lint:changes
```

前端构建需配合当前运行环境的 BACKEND_URL，改变该值后要重新构建。2026-11-14 已修复全部 12 项既有 ESLint 错误，当前完整检查为 0 错误、19 条既有警告；不能称为零警告。lint:changes 的基线只保留尚存警告，已修复诊断不再获准重新出现。

### 2026-11-14 静态检查修复明细

| 位置 | 原问题 | 数量 |
|---|---|---|
| 聊天页 | 未重赋值的变量使用 let；异常参数使用 any | 2 |
| 首页 | 异常参数使用 any | 1 |
| 日记详情 | 引导回答、反馈字段及推荐项使用 any | 3 |
| 日记编写 | 反馈状态及推荐项使用 any | 2 |
| 日记列表 | JSX 中两处双引号未转义 | 2 |
| 登录页 | 异常参数使用 any | 1 |
| 陪伴工作台公共接口 | 返回字典使用 Record<string, any> | 1 |

日记结构由 [diary-types.ts](../../frontend/src/lib/diary-types.ts) 共享；工作台响应与语音事件由 [care-types.ts](../../frontend/src/lib/care-types.ts) 声明。公共接口对未指定结构的字段使用 unknown，由调用处选择具体响应类型；这属于编译期契约，不代替运行时数据校验。没有关闭 ESLint 规则或通过新增忽略项绕过错误。

真实云调用、浏览器和生命周期验证分别见[语音](../features/voice.md)、[自然采集](../features/screening.md)、[SEGA](../features/sega.md)、[前端验证](frontend.md)及[完整复核入口](../operations/installation.md)。这些检查可能调用云服务或向专用演示库写入虚构记录，按对应说明使用隔离环境。

通话后复核随现有 `python -m app.care.worker` 启动，单独线程执行模型调用；只运行 API 不会消费该队列。`ROBOT_CARE_CONCERN_REVIEW_MODE=post_session` 为默认流程，`live` 保留原逐回合模式供回归。新增回归见 [test_after_call.py](../../backend/tests/test_after_call.py)；[check-after-call-ui.mjs](../../frontend/tools/check-after-call-ui.mjs) 使用虚构 API 响应核对浏览器中的状态、重试和跨会话部分条目，不读取生产数据。

## 文档维护约定

- 根目录 README 只保留项目概况和入口；功能说明写入 docs/features，不再新增根目录 README_*.md。
- 通用配置、部署和安装分别维护在 docs/reference 与 docs/operations；模块内部说明、素材来源及许可保留在相应代码目录。
- 当前未解决的问题统一维护在 docs/status.md；新增测试通过不自动关闭问题。
- 历史交接与修复说明进入 docs/archive，保留日期、基线和验证口径，不冒充最新操作手册。
- 移动文档时同时修正文档相对链接、文字中的路径和文档导航，运行 check-docs.py。文档中的 shell 命令需明确执行目录。
- 凭证、数据库、模型资源和本机回执保存在忽略的运行目录；引用本机证据位置时不把私人原话写进仓库。

根目录启动脚本属于固定用户入口；维护文档时不搬动这些入口，不操作正在运行的数据库。上游原始介绍和[复制基线清单](../upstream/baseline.json)用于来源追溯，其历史结论按[当前状态](../status.md)理解。

文档旧名称与新位置的完整对应关系见[迁移对照表](../reference/document-paths.json)。
