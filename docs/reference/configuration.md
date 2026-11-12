# 配置与接口

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

## 专项配置与后续接口

本页下表保留记录与分析的核心接口。后续语音、报告和采集配置按对应功能维护：

| 范围 | 权威说明 |
|---|---|
| 豆包语音与终端 | [语音配置及协议](../features/voice.md) |
| 逐句豆包语义分类 | [分类引擎及重试](../features/sentiment.md) |
| 报告模型 | [报告配置](../features/reports.md) |
| 持久采集任务 | [对话采集与任务接口](../features/screening.md) |
| SEGA 特征与实验接口 | [SEGA 接入](../features/sega.md) |

后端从 backend/.env 或进程环境读配置，进程环境优先。样例 `backend/.env.demo.example` / `.env.production.example` 的密钥留空，必须生成足够长的随机 SECRET_KEY；不把样例改成实际凭证再提交。生产默认 APP_ENV=production、engine=rules、assessment_provider=disabled、simulator=false。fixture 或 simulator 在 production 启动即拒绝。

| 配置 | 默认和边界 |
|---|---|
| DATABASE_URL | SQLite 路径；生产 API/worker 指向同一个持久文件 |
| SECRET_KEY | 必须至少 32 字符，持久随机密钥，JWT/游标/删除引用使用 |
| SQLITE_BUSY_MS | 1000，SQLite 锁等待 |
| ROBOT_UPLOAD_POLICY | streaming；本轮演示显式 after_close，属客户端进程配置 |
| ROBOT_CARE_ANALYSIS_ENGINE | rules / ollama / doubao_realtime；API 和 worker 必须一致 |
| ROBOT_CARE_ASSESSMENT_PROVIDER | disabled / fixture / live |
| ROBOT_CARE_DEMO_DATABASE | fixture 必须为 true，仅专用演示库 |
| ROBOT_CARE_FIXTURE_FILE | fixture 必需，独立 UTF-8 JSON，不写原量表表 |
| ROBOT_CARE_SIMULATOR_ENABLED | false，只接受 true/false |
| ROBOT_CARE_LEASE_SECONDS | rules/Ollama 默认30，豆包语义分类默认90，范围1—600；模型模式应长于超时加提交余量 |
| ROBOT_CARE_MAX_ATTEMPTS | 3，1—10 |
| ROBOT_CARE_RETRY_SECONDS | 2，0—300，按尝试指数退避 |
| ROBOT_CARE_POLICY_SECONDS | 3600，1—86400；旧输入或配置也会使策略失效 |
| ROBOT_CARE_POLL_SECONDS | 1，1—30 |
| ROBOT_CARE_MODEL_BASE_URL / NAME | ollama 时必需，无默认地址/模型 |
| ROBOT_CARE_MODEL_TIMEOUT_SECONDS | 10，0.01—120 |
| ROBOT_CARE_MODEL_MAX_RESPONSE_BYTES | 65536，1024—1048576 |
| BACKEND_URL | Next 服务端内部 HTTP(S) origin，build 时固定；修改后重新 build |

不会自动下载模型。旧 MODELSCOPE_API_KEY 是原项目其他模块使用的配置，本轮规则分析/回放不需要它，也不调用原聊天推理接口。

新增前缀 `/api/robot-insights`，全部复用原 User JWT，严格 body 字段、int64、UTC 时间，默认错误不含请求正文：

| 方法 / 路径 | 输入和行为 |
|---|---|
| GET /profile | 稳定随机匿名编号 |
| POST /analysis-jobs | `{record_id}`；202 新建 / 200 相同版本已有任务 |
| GET /analysis-jobs/{job_id} | 状态、版本、来源、失败码，不伪造中性 |
| GET /sessions/{sid}/analyses | 带签名游标分析列表 |
| GET /sessions/{sid}/summary | 当前有效稿摘要，排除/未知/失败/待分析分别计数 |
| GET /messages/{record_id}/effective | 原始稿与当前有效稿、input_revision |
| POST /messages/{record_id}/corrections | `{request_id,base_revision,content}`；201 / 幂等 200 / 冲突 409 |
| GET /policies/{policy_id} | 来源、版本、有效期、模拟入口是否可用 |
| POST /strategy-deliveries/simulate | `{policy_id,request_id}`；仅 demo 接收，201 / 200 |
| GET /strategy-deliveries/{delivery_id} | simulated_received 或 simulated_rejected，无 real/applied |
| GET /assessments | 当前 provider 的只读条目及缺口状态 |
| GET /trends | `from/to` 时间范围，按来源和配置版本分组 |
| POST /reports/preview | `{scope:{session_ids:[1..50]}}` 或 `{scope:{time_from,time_to}}`，不能混用 |

报告/策略不接受客户端写入分类、owner、applied、医疗分数等字段。原生消息仍走 `/api/robot-records`，其旧幂等、删除、分页和字段校验保留。OpenAPI 在交付根目录；响应体具体字段以实现及 ReportDTO 集成测试为准（FastAPI 当前响应 schema 部分为通用 JSON）。

和正式契约的增补：新增独立 demo 数据库 opt-in 防误配；额外输出 simulator_enabled 方便 UI 隐藏关闭的模拟入口；删除引用只留加密摘要，不存原 ID。未改变外部负责人既有接口，未来拿到 2.1/2.5 实际字段后做兼容映射。
