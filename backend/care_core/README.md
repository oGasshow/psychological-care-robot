# 独立文本分析核心

`care_core` 仅依赖 Python 标准库，不导入数据库、音频或大型模型框架。它处理单条当前用户已完成文字，属于有限中文文本规则演示，不能代替专业评估，不提供医疗风险等级、概率或准确率承诺。

## Python 入口

```python
from care_core import analyze, configuration, CoreSettings, CoreAnalysisError
from care_core import safety, input_eligibility, local_preview

config = configuration("rules", CoreSettings.from_env())
result = analyze("今天见到朋友，我很开心。")
preview = local_preview("最近我有些孤独。")
```

`analyze(text, engine_kind='rules', *, settings=None)` 返回纯 JSON 字典：

- `classification_status=classified/unable_to_determine`；后者 `emotion_label=null`，原因写入无原文 `reason_code`。成功分类仅 positive/neutral/negative。
- `engine_kind/engine_version/config_version/config_sha256/config_summary`；`matched_rule_ids` 保存有限规则依据，不保存输入片段。
- `safety_signal=none_detected/explicit_danger_expression/undetermined`；`none_detected` 仅表示未匹配当前规则，不能显示成“无风险”。
- `support` 含 `template_id/template_version/policy_kind/text/review_state/applicability_scope/valid_timing`。上层负责补齐用户、业务会话、来源任务/结果、目标记录与策略 ID。

`input_eligibility(role, text_status, text)` 显式排除非 user、非 completed、空白及超长输入。`analyze` 拒绝无效正文，不能以中性替代排除或失败。

`local_preview` 始终 `source_kind=local_preview/is_persisted=false/is_test=true`，无任务/结果 ID，不得混入正式报告。正式存储须由鉴权任务、原记录、更正版本和事务统一管理。

## 规则和事先预期

规则在 `rules.v1.json`，支持与安全提示在 `templates.v1.json`。版本名称加实际生效内容摘要共同组成配置版本；模型配置、提示/schema、模板或规则变更均会改变 `config_version`。当前不输出细情绪标签，`emotion_tags=[]`。

| 虚构输入 | 事先预期 | 理由 |
|---|---|---|
| 今天见到朋友，我很开心。 | positive | 本人当前明确积极词 |
| 我今天去公园散步了。 | neutral | 有限明确事实句式 |
| 我有些孤独。 | negative，倾听模板 | 明确孤独词 |
| 我很担心明天，压力很大。 | negative，自愿放松/追问模板 | 明确担忧词 |
| 我今天不开心。 | negative | 否定积极词独立负向规则 |
| 我并没有感到孤独。 | unable_to_determine | 否定消极词，不倒推积极/中性 |
| 我不是不开心。 | unable_to_determine | 双重否定保守不判 |
| 朋友说他很难过。 | unable_to_determine | 他人转述不归给当前用户 |
| “我很开心” | unable_to_determine | 引号内不当作本人当前表达 |
| 我希望开心。 | unable_to_determine | 期望不等于实际心情 |
| 我很开心，也有些难过。 | unable_to_determine | 混合，不做加权猜测 |
| 嗯，那个事情就这样吧。 | unable_to_determine | 不足以分类 |
| 我不想活了。 | 独立 explicit_danger_expression + 安全提示 | 不依赖情绪分类结果 |

处理顺序为引用/转述排除、复杂否定、期望/假设、消极词否定、积极词否定、混合冲突、有限事实句式，其余未知。规则能力有限，讽刺、隐喻、隐含指代、复杂句、方言等不在本轮能力证明范围。

安全规则独立扫描未引用的本人明确危险表达。危险词只出现在转述/引用/否认或无法确认语境时为 `undetermined`。它是文本信号，不是临床判断；普通消极不会自动成为危险等级。安全/支持模板均为 `draft_pending_professional_review`，正式内容审核 X02 仍待指定人员，未附热线号码、药物指导或诊断。

## 独立 CLI

在 backend 目录把单个 UTF-8 JSON 事件送入 stdin：

```json
{"text":"今天见到朋友，我很开心。","role":"user","text_status":"completed"}
```

运行 `python -m care_core`，默认 rules。参数 `--engine ollama` 只选择服务端配置好的适配器，不接受地址/模型名。输入/模型错误只输出稳定码与独立安全提示，退出码 2；输入排除输出 `classification_status=excluded`。不从命令行参数读取正文，避免正文进入进程参数。

## Ollama 协议与默认值

实现配置档 `ollama-api-chat-structured-2026-10-28`，引擎版本 `ollama-chat-v1`。2026-10-28 查阅的官方依据：[POST /api/chat](https://docs.ollama.com/api/chat) 和 [Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)。按 `/api/chat` 发送 model/messages，显式 `stream=false`、JSON schema `format` 与 `temperature=0`；接收完整 assistant/content JSON，核对模型名、完成标志、schema 与枚举。正文不放 URL。

| 服务端配置 | 默认/限制 |
|---|---|
| ROBOT_CARE_MODEL_BASE_URL | 无默认；ollama 时必需；http/https origin，不含认证、路径、query、fragment |
| ROBOT_CARE_MODEL_NAME | 无默认；ollama 时必需；精确模型名与响应一致 |
| ROBOT_CARE_MODEL_TIMEOUT_SECONDS | 10 秒；0.01—120 秒 |
| ROBOT_CARE_MODEL_MAX_RESPONSE_BYTES | 65536；1024—1048576 字节 |

只连接配置地址，禁用环境 HTTP 代理及重定向；不自动下载模型、不访问默认外部地址。配置摘要只保存 endpoint 的 SHA256，不保存原 URL。适配器拒绝非法/重复字段 JSON、未知/不一致标签、未知字段、错误模型、未完成响应及超长响应。模型生成自由建议不进入结果，支持内容全部来自版本化模板。

模型错误抛 `CoreAnalysisError`，`code/retryable/safety_result` 可保存；`str/repr` 仅有错误码/重试标记，无输入、原响应或 URL。无静默规则回退。错误码包括 `model_configuration_missing/invalid`、`model_http_error`、`model_timeout`、`model_unavailable`、`model_transport_error`、`model_response_too_large`、`model_protocol_invalid`、`unsupported_analysis_engine`、`invalid_analysis_input`。安全分支先执行，即使模型失败/超时，异常 `safety_result.support` 仍保留预设安全提示；上层应将任务标为 failed，而非伪造分类成功。

这里只验证真实 localhost 假 HTTP 协议与故障，未证明任何实际模型能力、精确权重/服务版本或内容安全效果，X01 未执行。

## 自测

`python -m unittest discover -s tests -p test_care_core.py -v` 可独立运行，不导入应用数据库。

测试覆盖事先期望、否定/引用/转述/混合、至少 3 支持场景、安全信号与普通消极区分、异常安全分支、真实本地 HTTP 请求/schema、非法 JSON/标签/字段、超时/错误/重定向、响应上限、配置变更摘要及短标记/长输入异常脱敏。策略模拟接收、任务持久化和 UI/报告由应用层集成测试验证。
