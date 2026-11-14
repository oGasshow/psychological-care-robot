# 近期陪伴报告

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

文中的命令与代码路径从仓库根目录理解，另有工作目录说明时按该节执行。

2026-11-10：将 `/robot-care/report` 改为“近期陪伴回顾”。复用 [shadcn/ui dashboard-01](https://ui.shadcn.com/blocks/dashboard) 的概况分层和实际 Card 组件，保留 [MIT 许可](../../frontend/src/components/report-ui/LICENSE.shadcn.md)。未安装新的 npm/Python 依赖。

页面先显示文字回顾，再显示记录覆盖、按日表达、同口径前后周期、话题原话、交流建议及可展开的来源。默认近 7 天含今天，方便查看最新记录；“近 7 个完整日”用于周期比较。量表不再出现在新报告主线，历史数据和旧接口保留。

最新增量：只有后台触发相关对话采集并形成已确认条目时，报告才显示独立的辅助结果。普通用户、未触发会话和旧全空结果都不出现量表卡片，不要求补做问卷。详见 [按需采集](screening.md)。

统计由后端计算，文字通过独立生成链路组织。没有模型时，规则摘要仍可直接使用，并清楚标记；模型未配置、调用失败、输出不合法和混合来源都有可用的回退。明确危险表达始终由原来的独立规则提示，不能被模型输出覆盖。

## 启动与查看

已有运行数据使用 `Resume-Project.cmd` 继续，登录后打开“报告摘要”。`Start-Presentation.cmd` 会恢复新的演示底稿，不适合保留现场操作。只配置模型时也需要重新启动 API 进程，使 `.env` 生效。

## 模型配置

参考 [backend/.env.report.example](../../backend/.env.report.example)，将所需字段写入本机 `backend/.env` 或启动 API 的进程环境。该示例文件不会自动加载。密钥只存本机，不写进代码、截图、Git 或交接附件。

| provider | base URL | 模型字段与行为 |
|---|---|---|
| `disabled` | 不需要 | 默认规则摘要，无模型外部调用 |
| `doubao_realtime` | 固定的已开通全双工语音地址 | 复用 `DOUBAO_VOICE_API_KEY`；固定合成语音触发函数调用输出，模型 `1.2.6.1` |
| `ollama` | 例如 `http://127.0.0.1:11434` | 填本机已安装模型名称；请求 `/api/chat`，传 JSON Schema |
| `qwen` | 百炼控制台提供的 `compatible-mode/v1` 地址 | 填已开通模型名；Chat Completions JSON 模式，关闭 thinking |
| `doubao` | 例如 `https://ark.cn-beijing.volces.com/api/v3` | 填已开通的模型名/接入点；Chat Completions JSON 模式，关闭 thinking |
| `chat_completions` | 提供方的兼容 API base URL | 通用 JSON 模式，不添加供应商 thinking 参数 |

共用字段为 `ROBOT_CARE_REPORT_PROVIDER`、`ROBOT_CARE_REPORT_MODEL_BASE_URL`、`ROBOT_CARE_REPORT_MODEL_NAME`、`ROBOT_CARE_REPORT_API_KEY`、`ROBOT_CARE_REPORT_TIMEOUT_SECONDS`。base URL 不含 `/chat/completions`。如果没有报告专用配置，已有 `ROBOT_CARE_MODEL_BASE_URL/NAME` 可作为 Ollama 配置继承；不自动调用旧的云端路由或凭证。

2026-11-11 本机已配置并真实验证 `doubao_realtime`。该权限是语音服务，并非方舟文本 API：服务端建立单独报告会话，将事实包放入系统指令，发送仓库内固定的合成开始语音，再接收 `write_companionship_report` 的结构化参数。没有打开麦克风或扬声器，不把这段触发语音写入用户历史；输出仍须通过原有结构、引用和来源快照校验。超时建议 45 秒。语音服务的调用计费与并发限制按实际开通权益执行。后续获得方舟/百炼文本权限后，只需切换 provider 和相应配置。

百炼地址按当前控制台的地域/业务空间填写，不把示例里的占位符当真实地址；豆包也须选择支持所用 JSON/非思考参数的实际模型。资料：[百炼 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[百炼思考模式](https://help.aliyun.com/zh/model-studio/deep-thinking)、[火山方舟结构化输出](https://console.volcengine.com/ark/region:cn-beijing/docs/structured-output-beta)、[Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)。

配置完成后，在仓库根目录执行一次纯虚构输入检查：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe backend/tools/check_report_model.py --show-text
```

返回 `mode=model` 且退出码 0 表示该次模型生成通过结构/引用等程序检查；`mode=rules`、退出码 2 表示当前是规则回退，`reason_code` 提供原因。这个命令不访问业务数据库，输出不含 API Key；语义忠实性仍需人工检查。

## 来源一致性和统计边界

`reports/preview` 新增 `report_facts`、`source_snapshot_hash` 和即时规则摘要；`reports/narrative` 只接受本人 `scope` 和预期 hash，前后重新读取来源，网络调用期间不持有 SQLite 事务。更正/删除、前周期来源变化及分析配置变化会使旧摘要失效。未新增正文持久缓存。

刚保存语音时，后台分析可能在总结生成期间完成。页面会丢弃失效输出，读取全新快照并自动重新生成一次；如果来源仍在变化，可使用“刷新本次回顾”。不会将旧 hash 的文字贴到新统计上。

积极/中性/消极只表示已记录文字类别。未分类不补中性，无记录日不补零分；按引擎/版本/配置/测试属性分流。完整自然日、每周期至少 5 条分类且覆盖 3 日时才显示描述性比较，这只是工程展示门槛。不同口径不拼趋势，也不输出临床总分、诊断或疗效结论。

话题采用原话关键词提及归组，显示原文依据；它不是新增的细粒度情绪模型，不能当作生活质量测量。输入模型的原话按时间分散抽样，最多 20 条、每条最多 400 字；长原话标节选，不能穷尽所有话题。首次模型接入与后续质量审核应单独记录。

## 验证身份

原有测试使用虚构数据库和本机受控 HTTP 服务验证四种文本协议、来源 hash、失败与不合法输出。2026-11-11 另用真实豆包凭证验证了语音函数调用生成摘要，并验证真实语音转录保存后的报告 API 返回 `mode=model`。Ollama、千问和方舟文本 API 仍仅完成适配及本地协议测试。语义质量仍需人工复核；本轮是开发自测，不追认历史独立验收。


## 量表依据与 API 解读

量表页和报告共用量表结果卡，显示名称、测量方向、近两周回顾范围、完成度、合计/满分、参考分段、逐条频率及原话会话链接。未采齐或来源待核实不生成总分；项目自定义指标单独标识，不换算成标准量表，不设置临床分界。

| 量表 | 条目与满分 | 分段参考 | 原始研究 |
|---|---|---|---|
| PHQ-9 | 9项，0—27分 | 0—4、5—9、10—14、15—19、20—27 | [Kroenke等，2001](https://pmc.ncbi.nlm.nih.gov/articles/PMC1495268/) |
| GAD-7 | 7项，0—21分 | 0—4、5—9、10—14、15—21 | [Spitzer等，2006](https://pubmed.ncbi.nlm.nih.gov/16717171/) |

上述分段是原量表的症状频率参考，本系统当前采用对话辅助采集，不能把原研究的效度直接宣称为聊天施测的效度。PHQ-9第9项非零回答单独提示关怀与核实，不以低总分排除关注。原始研究链接、DOI与用途说明可在卡片展开查看。

报告的量表事实在生成文字之前纳入同一快照，包括核验后的条目、完整度、分数和来源。API只解释已有事实，不补缺项、不合并不同量表分数。只选择单次会话而遗漏跨会话评分所需来源时，分数会隐藏；选择包含全部来源的日期范围或会话集合后才能展示完整结果。

本机首版使用已配置的 `doubao_realtime` API：分别生成总览、具体建议及逐指标解读，减少语音接口返回复杂结构不完整的问题。每段均需提供有效事实或原话引用；分数、分段和量表名称经过校验。现有 OpenAI兼容格式适配仍可连接豆包文本API或千问，但需对应服务地址、模型名及本机密钥配置。语音密钥不被当作文本API密钥使用。接口失败会明确标记规则摘要，不冒充模型输出。

## 普通版采集修复迁移

普通版已共用明确回答直接入账、乱序条目识别、缺信息澄清、跨会话已完成项提示、持久的保存后自动核对、完成态保持和会话占用释放流程。普通版仍使用完整PHQ-9/GAD-7及项目指标；标准量表四档和自定义指标五档独立匹配，不把回答跨量表套分。演示低门槛和三项短流程保持隔离。明确拒绝、暂停或安全关注优先，不通过自动核对绕过。
