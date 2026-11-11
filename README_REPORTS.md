# 近期陪伴报告

2026-11-10：将 `/robot-care/report` 改为“近期陪伴回顾”。复用 [shadcn/ui dashboard-01](https://ui.shadcn.com/blocks/dashboard) 的概况分层和实际 Card 组件，保留 [MIT 许可](frontend/src/components/report-ui/LICENSE.shadcn.md)。未安装新的 npm/Python 依赖。

页面先显示文字回顾，再显示记录覆盖、按日表达、同口径前后周期、话题原话、交流建议及可展开的来源。默认近 7 天含今天，方便查看最新记录；“近 7 个完整日”用于周期比较。量表不再出现在新报告主线，历史数据和旧接口保留。

统计由后端计算，文字通过独立生成链路组织。没有模型时，规则摘要仍可直接使用，并清楚标记；模型未配置、调用失败、输出不合法和混合来源都有可用的回退。明确危险表达始终由原来的独立规则提示，不能被模型输出覆盖。

## 启动与查看

已有运行数据使用 `Resume-Project.cmd` 继续，登录后打开“报告摘要”。`Start-Presentation.cmd` 会恢复新的演示底稿，不适合保留现场操作。只配置模型时也需要重新启动 API 进程，使 `.env` 生效。

## 模型配置

参考 [backend/.env.report.example](backend/.env.report.example)，将所需字段写入本机 `backend/.env` 或启动 API 的进程环境。该示例文件不会自动加载。密钥只存本机，不写进代码、截图、Git 或交接附件。

| provider | base URL | 模型字段与行为 |
|---|---|---|
| `disabled` | 不需要 | 默认规则摘要，无模型外部调用 |
| `ollama` | 例如 `http://127.0.0.1:11434` | 填本机已安装模型名称；请求 `/api/chat`，传 JSON Schema |
| `qwen` | 百炼控制台提供的 `compatible-mode/v1` 地址 | 填已开通模型名；Chat Completions JSON 模式，关闭 thinking |
| `doubao` | 例如 `https://ark.cn-beijing.volces.com/api/v3` | 填已开通的模型名/接入点；Chat Completions JSON 模式，关闭 thinking |
| `chat_completions` | 提供方的兼容 API base URL | 通用 JSON 模式，不添加供应商 thinking 参数 |

共用字段为 `ROBOT_CARE_REPORT_PROVIDER`、`ROBOT_CARE_REPORT_MODEL_BASE_URL`、`ROBOT_CARE_REPORT_MODEL_NAME`、`ROBOT_CARE_REPORT_API_KEY`、`ROBOT_CARE_REPORT_TIMEOUT_SECONDS`。base URL 不含 `/chat/completions`。如果没有报告专用配置，已有 `ROBOT_CARE_MODEL_BASE_URL/NAME` 可作为 Ollama 配置继承；不自动调用旧的云端路由或凭证。

百炼地址按当前控制台的地域/业务空间填写，不把示例里的占位符当真实地址；豆包也须选择支持所用 JSON/非思考参数的实际模型。资料：[百炼 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[百炼思考模式](https://help.aliyun.com/zh/model-studio/deep-thinking)、[火山方舟结构化输出](https://console.volcengine.com/ark/region:cn-beijing/docs/structured-output-beta)、[Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)。

配置完成后，在仓库根目录执行一次纯虚构输入检查：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe backend/tools/check_report_model.py --show-text
```

返回 `mode=model` 且退出码 0 表示该次模型生成通过结构/引用等程序检查；`mode=rules`、退出码 2 表示当前是规则回退，`reason_code` 提供原因。这个命令不访问业务数据库，输出不含 API Key；语义忠实性仍需人工检查。

## 来源一致性和统计边界

`reports/preview` 新增 `report_facts`、`source_snapshot_hash` 和即时规则摘要；`reports/narrative` 只接受本人 `scope` 和预期 hash，前后重新读取来源，网络调用期间不持有 SQLite 事务。更正/删除、前周期来源变化及分析配置变化会使旧摘要失效。未新增正文持久缓存。

积极/中性/消极只表示已记录文字类别。未分类不补中性，无记录日不补零分；按引擎/版本/配置/测试属性分流。完整自然日、每周期至少 5 条分类且覆盖 3 日时才显示描述性比较，这只是工程展示门槛。不同口径不拼趋势，也不输出临床总分、诊断或疗效结论。

话题采用原话关键词提及归组，显示原文依据；它不是新增的细粒度情绪模型，不能当作生活质量测量。输入模型的原话按时间分散抽样，最多 20 条、每条最多 400 字；长原话标节选，不能穷尽所有话题。首次模型接入与后续质量审核应单独记录。

## 验证身份

新增测试使用虚构数据库和本机受控 HTTP 服务验证四种协议、来源 hash、失败与不合法输出。它们不等于真实 Ollama/千问/豆包推理；没有凭证和服务时不能宣称真实模型联调已完成。当前改动是开发自测成果，不追认历史独立验收。
