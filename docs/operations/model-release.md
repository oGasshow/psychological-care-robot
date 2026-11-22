# 模型权重交接附件

项目当前已安装的非敏感模型权重通过 [GitHub 模型交接版](https://github.com/oGasshow/psychological-care-robot/releases/tag/models-handoff-2026-11-22) 提供，不放入 Git 源码历史。

| 附件 | 内容 |
|---|---|
| sega-eatd-checkpoint.zip | 作者中文 EATD 的 sega_best.pt |
| feature-encoder.zip | 当前实验提取器使用的中文 BERT 及 tokenizer/config |
| feature-translation.zip | 当前实验提取器使用的中英翻译模型及 tokenizer/config |
| feature-emotion.zip | 当前实验提取器使用的七类情绪模型及 tokenizer/config |
| model-packages.json | 各附件大小和 SHA-256 |

压缩包按项目根目录组织 runtime 相对路径，包含原始模型来源与固定版本信息；解压前先核对校验值，已有文件应先备份。safetensors 和现有 PyTorch bin 两种文件均按原文件提供，没有重新训练或改写权重。

提取器路径配置模板位于 `deploy/edge/sega-extractor.example.json`，默认仅限测试。它记录了当前实验配置的固定模型版本；1000/500 ms 音频窗口及步长仍需与作者口径核对。SEGA 原模型代码需要另按交接手册取得，附件中的检查点不能代替完整代码和运行环境。

作者的其他部分检查点在本机只有 133 字节 LFS 指针，未当作有效权重分发。附件不包含作者数据集、用户对话、业务数据库、密码、API 密钥、SSH 私钥、虚拟环境或可连接现有服务器的设备私有配置。

权重及模型代码的原始来源和使用条件继续适用；各组件原始地址、固定提交与文件校验值见 [模型清单](../reference/model-artifacts.json)。这些特征模型是当前项目的实验组合，不代表作者定制提取口径已被完全复现。

资源上传不等于 ARM 部署完成：当前 SEGA 执行器仍要求 CUDA，普通树莓派需要 CPU/ARM 适配及输入、速度和内存验证。Windows 虚拟环境不能直接复制到树莓派。
