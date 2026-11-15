# SEGA 实模型实验接入

[文档导航](../README.md) · [当前状态与已知问题](../status.md)

文中的命令与代码路径从仓库根目录理解，另有工作目录说明时按该节执行。

2026-11-12 已实际运行作者中文 EATD SEGA 权重，并接入平台实验分析 API。它与豆包的上下文判断、逐句情绪分类、自然回答抽取是不同的执行器，不能把后者的提示词称为 SEGA。

来源：[论文](https://aclanthology.org/2024.naacl-long.452/)、[作者仓库](https://github.com/zhchen18/SEGA)，本机核验提交 `0514201653d71728015cf4aea2816c9151b94f71`。实际使用 `EATD/3-model/models/graph_fusion.py` 与 `sega_best.pt`，权重 SHA-256：`f9b427f3928a56fde91e25265eea5aac8677e5fd4c369f2cb2ebac438cfbc8bd`。第三方代码、权重与数据保持在忽略的 runtime/sega_reference，不再分发进本仓库。

## 实际做到了什么

- 用作者评估脚本运行完整三折权重评估：Macro-F1 分别 82.90、79.41、80.88，平均 81.06，与作者检查点报告一致。这是作者既有特征上的评估，没有重新训练，也不是本平台用户准确率。
- 新增隔离进程执行器 backend/tools/sega_infer.py，实际加载权重并 strict=True 装载状态，检查权重摘要与输入形状，运行图模型。当前作者实现内部使用 CUDA；本机实测为 RTX 3060 Laptop、PyTorch 2.5.1+cu121。
- 后台量表页的“SEGA 图模型 · 实验分析”可以运行作者特征样例。它不关联当前用户原话，不写入个人量表或采集标识。
- 本人会话可上传完整特征包执行真实模型。实验输出 class=1 可建立 PHQ-9 待进一步了解任务；这只保留后续温和了解的需求，不直接启动问卷、不生成量表分数、不判断临床风险。当前交流是否适宜继续，仍由后台对话流程核查。class=0 不会清除已有任务。

## 当前不能当作什么

原语音记录只持久化最终转写，没有保留严格题答对齐的音频特征。旧会话 6/7/8 因而不能追补一次可信的完整 SEGA 推理；接口会显示缺失，不能用零向量或猜测性别等方式伪造输入。

作者 EATD 权重需要对应的文本、问题、88维音频、7类情绪概率及性别编码。作者预处理还依赖其特征抽取工具配置，文件名与脚本包含不同编码器实验痕迹。当前未验证一个从本平台实时音频到完全同口径输入的自动抽取器，也未验证日常陪伴对话相对训练访谈的分布差异。手动上传特征始终标为 manual_aligned_features_unverified，不宣称临床有效性。

论文的 GPT 用于训练数据增强；其结构图分类器不是 GPT。若后续改用豆包生成增强样本，还需要训练与对照评估，不能声称仅换 API 就复现 SEGA++。

## 运行与接口

模型进程独立于服务端 .venv。默认读取项目根 runtime/sega_env/Scripts/python.exe 与 runtime/sega_reference，可在服务端配置 ROBOT_CARE_SEGA_PYTHON、ROBOT_CARE_SEGA_REFERENCE。当前独立环境只读复用本机已有 torch 依赖，未修改常用 venv；其他机器需准备匹配的 torch、numpy、scikit-learn 与 CUDA。Pi 通过平台接口调用服务器模型，不在 Pi 上运行 CUDA，也不持有豆包密钥。

作者资源获取可使用 git sparse checkout 与 git lfs pull；权重与特征需完整下载，LFS 指针文件不能作为模型。部署核验代码与上述提交、摘要是否一致。

本机使用的下载范围如下（如目录已存在，先核查其来源和提交，不覆盖）：

```powershell
$env:GIT_LFS_SKIP_SMUDGE='1'
git clone --depth 1 --filter=blob:none --sparse https://github.com/zhchen18/SEGA.git runtime/sega_reference
git -C runtime/sega_reference sparse-checkout set EATD/3-model EATD/1-preprocess
git -C runtime/sega_reference lfs pull --include="EATD/3-model/checkpoints/sega_best.pt,EATD/3-model/data/EATD-Features/*"
```

这些命令下载当时 main 的内容；部署者还需核查提交是否仍为本文记录值，不能把后续上游改动自动当作本次已测版本。准备好独立GPU Python后，可运行 backend/tools/sega_infer.py 的 `--reference runtime/sega_reference --fixture` 检查实际推理。

所有接口沿用本人系统 JWT，返回 no-store：

- `GET /api/robot-voice/sega/status`：安装状态与输入缺项。
- `POST /api/robot-voice/sega/probe`：仅测试环境，运行作者特征样例，不写个人记录。
- `GET /api/robot-voice/sega/sessions/{sid}`：本人会话实验结果或缺失状态。
- `POST /api/robot-voice/sega/sessions/{sid}`：请求体为 NPZ 字节，最多16MiB、展开最多64MiB；不接受客户端本机路径或 pickle。结果保存来源修订，后续更正使旧模型输出待重新核实。

NPZ 契约：text 与 question 为 `[1,3,L,768]`，audio 为 `[1,3,L,88]`；各 L 为1–2048。emotion 为 `[1,3,7]` 概率，gender 为 `[1]` 或 `[1,1]` 且必须有实际依据；record_ids 与 question_record_ids 各为3个当前本人会话的已完成用户／助手记录ID。来源存在和角色检查不能证明外部特征抽取口径正确，因此结果仍是实验状态。没有来源或任何特征缺失均拒绝，不补值。

后续真正部署到实时语音，还需采集与问答对齐音频、核对完整编码器与音频提取配置、验证新对话输入分布，再决定是否让模型更深入参与触发。现有用户级任务标识与豆包采集链路已经可独立运行。

## 提取时机评估与当前选择（2026-11-14）

| 方案 | 对本项目的适用性 | 仍需解决的输入问题 |
|---|---|---|
| 通话过程中持续提取 | 需要处理未完成的转写、被打断回答、重复窗口和并发推理，会增加语音链路负担 | 完整原音频、固定编码器与辅助特征、问答对应关系仍缺一不可 |
| 通话后异步提取并跨会话汇总 | 可以在文字保存和问答边界固定后处理，便于重试、版本核查与追溯，优先采用 | 同样需要真实音频和经核对的特征提取配置；改变处理时机不能补回缺失模态 |

本机检查：独立 SEGA 环境已有 torch 与 transformers，尚未安装 opensmile 与 MSA_FET。下载的作者脚本引用定制 FeatureExtractionTool，文本文件名包含 BERT/RoBERTa 实验痕迹；七类情绪使用中文转英文后再送入英文情绪分类器。训练输入按 negative/positive/neutral 三组组织。正式复用该权重前必须核对这些配置，不能只生成相同维数就称为同口径，也不能把平台三类文本情绪填成七类情绪概率。

原有的[通话后文本复核与跨会话任务](screening.md)由豆包整理有原话依据的关注线索。SEGA 保留作者样例与手动特征实验入口。自动支路的接口和启用条件见下节。

## 通话自动分析与账号标记

语音服务持续接收正常麦克风帧时，默认连续 60 秒静默自动结束并保存。可用 `ROBOT_CARE_VOICE_SILENCE_SECONDS` 在 15–300 秒之间调整。手动暂停、音频断流和助手播放期间分别处理。

新增自动实验链路。语音页只在作者权重与本地提取配置可用时提供本次参与选项，需要明确同意暂存本次回答音频并自行提供模型支持的性别输入。服务端使用已完成的回答和上一轮已播放的助手文字配对，至少需要三组。保存完成后进入持久任务，在 SEGA 独立环境内提取特征和推理。任务用完或到期后清除暂存音频。没有播放回执、音频断流、转录更正或特征缺失时，相关输入不会生成账号标记。

后端 `GET /api/robot-voice/sega/followup` 使用本人 JWT，返回 `marked` 和 `source_session_id`。自动分析成功的 `class=1` 形成标记，`class=0` 与失败均不新增标记。测试数据与非测试数据分开。删除来源会话或更正用作依据的转录后，该来源不再参与标记。会话实验接口的 `automatic_status` 可查询后台处理状态。这个分支只写实验标记，与原豆包采集任务及手动 SEGA 实验接口分开。

安装提取依赖到 `runtime/sega_env`，包括 `opensmile`、`transformers`、`sentencepiece`。本地 NumPy 1.26 环境使用 `pyarrow==23.0.1`。将 `ROBOT_CARE_SEGA_EXTRACTOR_CONFIG` 配为一个本地 JSON 文件的路径。文本编码器需能输出 768 维 token 向量，情绪模型的标签需覆盖作者顺序的七类。配置中的模型目录使用绝对路径，包含 tokenizer、模型配置和 safetensors 权重。配好后重启 API 和 worker。

```json
{
  "answer_encoder": "D:/path/to/verified/answer-encoder",
  "question_encoder": "D:/path/to/verified/question-encoder",
  "zh_en_translation": "D:/path/to/verified/zh-en-translation",
  "emotion_classifier": "D:/path/to/verified/emotion-classifier",
  "audio_window_ms": 1000,
  "audio_hop_ms": 500,
  "test_only": true
}
```

示例的音频窗口与步长用于说明配置格式。提取器使用 eGeMAPSv02 Functionals 生成 88 维帧序列，作者权重对应的窗口、步长与预处理仍需要对照作者参考数据核验。真实会话联调也要求配置有效的语音服务。自动分析输出保持实验属性。

## 两个服务对接接口

前缀为 `/api/robot-voice/sega/integration`，建议同机调用 `http://127.0.0.1:51077`，其他环境以 API 实际监听地址为准。两个调用方分别使用自己的 `Authorization: Bearer <凭证>`，由 `backend/.env` 中的 `ROBOT_CARE_SEGA_INPUT_TOKEN` 和 `ROBOT_CARE_SEGA_FOLLOWUP_TOKEN` 配置。服务凭证留在服务端，前端用户 JWT 继续使用原有接口。

### 豆包侧提交语音问答

`POST /sessions/{sid}`。先完成原有会话保存，再提交三组按时间排序的问答。`sid` 是服务端 `recording_session_id`，消息使用同一会话内已保存的 `external_message_id`，PCM 格式为 **16 kHz、16-bit 小端、单声道**。每条回答音频为 Base64 编码，包含至少 0.3 秒可检测语音且最长 60 秒。`gender` 来自用户自报，`consent` 表示当前会话已经获得录音分析授权。

请求中的字段为 `user_id`、`consent: true`、`gender: "female" | "male"`、`sample_rate: 16000`、`pairs`。`pairs` 恰有三项，每项提供 `question_message_id`、`answer_message_id` 和 `pcm_base64`。文本从已保存记录读取。

返回 `202` 及 `session_id`、`status`、`duplicate`。相同会话重复提交会返回已有状态。会话未完整保存或提取配置限测试数据时返回 `409`，问答或音频无效返回 `422`，模型配置缺失返回 `503`。后台任务完成前的 `pending` 或 `running` 只代表处理状态。

### 量表服务读取待跟进标记

`GET /followups/{uid}?is_test=true`。正式来源使用 `is_test=false`。响应格式如下。

```json
{"user_id": 123, "is_test": true, "marked": true, "source_session_id": 456}
```

上游 `class=1` 成功且来源仍有效时返回 `marked: true`。`source_session_id` 可用于下游去重。没有有效标记时返回 `marked: false` 与 `source_session_id: null`。该状态接口仅供下游读取，量表发送流程另行接入。

`test_only` 省略时默认 `true`。使用本地 BERT、翻译模型或自配音频切窗的实验配置保留 `test_only: true`，待用作者原始特征完成对照后再评估扩展范围。

本地实验配置在 `runtime/sega_extractor.json`。它用 `google-bert/bert-base-chinese` 分别编码问题与回答，用 `Helsinki-NLP/opus-mt-zh-en` 翻译，再用 `j-hartmann/emotion-english-distilroberta-base` 输出七类概率。音频使用 1000 ms 窗口和 500 ms 步长的 eGeMAPSv02。配置文件记录了下载的模型提交。完整对接验证使用虚构转录和合成 PCM，经两个服务接口完成队列、作者权重推理和标记查询。
