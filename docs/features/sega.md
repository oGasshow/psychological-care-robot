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
