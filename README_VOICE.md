# 豆包语音与 Windows / 树莓派接口

2026-11-12：修复旧回复取消确认缺失时可能持续丢弃新回复的路径，保留已取消旧消息的隔离。Windows 页面增加停顿后的补发、25秒无回复提示及“重新连接并保留记录”；重连先结束保存当前会话，再恢复用户级采集任务。浏览器收音数据意外中断超过6秒时，服务端先发送静音控制，恢复音频帧时再解除，避免无上行数据导致云端超时。后台仅记录事件类型、帧数及阶段等诊断元数据，不记录音频或原始事件载荷。此前那一次卡住没有事件日志，不能据此断言与本次可复现路径完全同因。

最新需求变更见 [按需对话采集](README_GUIDED_SCREENING.md)：用途由购买须知说明，后台上下文检测决定是否安排 PHQ-9 / GAD-7 辅助采集，会话没有勾选或口头同意门槛；普通用户只自然交流。

2026-11-11：新增 `/robot-care/voice`。网页实际收音，经服务端连接已开通的豆包全双工模型，显示最终转录和动态回复并播放返回音频。最终文字通过既有持久 Outbox，在结束后上传到本人的对话历史、规则分析和报告；网页和树莓派均不需要持有豆包密钥。不保存原始录音。

## Windows 使用

按锁文件更新依赖（新增 `websockets==15.0.1`），将 [语音配置示例](backend/.env.voice.example) 的所需字段写入本机 `backend/.env`，然后运行 `Resume-Project.cmd`。本机已配置的密钥不在仓库里；新电脑需自行配置。

登录后打开“语音陪伴”，点击“开始语音对话”，允许麦克风。可暂停收音、继续、打断回复；结束时点击“结束并保存”，等页面显示保存结果，再查看本次记录或生成回顾。建议佩戴耳机，减少扬声器回声。麦克风仅在点击开始后打开，结束或离开页面即停止。网页需要本机 localhost/127.0.0.1 或 HTTPS 安全上下文。

最终文字会实时写入本机持久队列，按既有 `after_close` 策略在结束后上传；待保存时可点击“重试待保存记录”。断网或进程中止后，重新登录、重试或开启下一次会话会补传已落盘文字。未被服务端识别/接收的声音无法补传。每位用户同时只允许一个语音会话，默认最长 15 分钟；服务端当前按单 Uvicorn worker 部署。

“最终文字”表示文本生成完成。播放完成回调仅表示客户端软件播放进度，不能证明真人听到了。已入库的助手文本播放状态保守保留 `unknown`，若持久化前已确认打断则为 `interrupted`；不篡改原模块的不可变消息。页面出现“保存状态需要处理”时不能视为已保存。

## 本次实际协议

用户提供的 Python 代码及可用凭证对应 Seeduplex3 JSON 协议：

- 固定地址 `wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`，服务端 `X-Api-Key` 鉴权。
- `session.create`，模型 `1.2.6.1`；输入 PCM16 小端单声道 16 kHz，每帧 20 ms/640 字节，输出 PCM16 小端单声道 24 kHz。
- `input_audio_buffer.append/commit`，`input_audio_mute.commit` / `input_audio_unmute.commit`；开场 TTS 使用 `speech_text_buffer.commit`。
- ASR、文字回复、音频与取消按事件流处理。每条回复独立追踪 ID；旧回复的取消回执及迟到音频不会丢弃新回复。

附件 Android SDK 是另一版本接口资料，没有把 Android SDK 安装到 Windows。旧二进制地址也没有直接替换新协议；本次该凭证访问旧地址返回 403，因此不假定具有旧版文本查询权限。原代码中的量表提问、问卷计分和独立纯文本报告写盘未导入，按当前范围沿用既有陪伴记录与新报告。

官方资料：[全双工服务接口](https://docs.volcengine.com/docs/doubao-voice/end-to-end-real-time-voice-full-duplex-version?lang=zh)、[接入必读](https://docs.volcengine.com/docs/doubao-voice/access-must-read?lang=zh)。附件含第三方版权声明，仓库仅包含项目适配实现与必要链接，不复制完整 SDK PDF、原始含密钥代码或厂商文档。

## 稳定终端协议 voice-bridge-v1

`GET /api/robot-voice/config` 使用现有用户 JWT，返回 enabled、采样率、帧大小、时限、测试属性及协议版本，不返回云端密钥。连接同源 `/api/robot-voice/live` WebSocket 后，首条 JSON 为：

```json
{"type":"authenticate","token":"通过现有登录获得的用户JWT","device_id":"raspberry_pi"}
```

JWT 仅通过首帧发送，不能放 URL 查询中。`session.ready` 后发送 `{"type":"unmute"}`，随后逐帧实时发送 640 字节二进制 PCM。控制 JSON 支持 `mute`、`unmute`、`interrupt`、`commit`、`finish`；`playback` 的 `state` 为 playing/completed/interrupted，可附 message_id。客户端不允许直接透传厂商事件、地址、工具或提示词。

| 服务端事件 | 客户端行为 |
|---|---|
| `session.ready` | 服务就绪，含实际会话 ID、采样率与测试属性 |
| `transcript.delta/final` | 按 message_id 更新同一条字幕；含 role、turn_id、text、occurred_at |
| `audio.delta` | base64 解码，按 24 kHz 播放，按 message_id 归属回复 |
| `audio.done` | 云端该条音频结束，客户端队列可能仍未播完 |
| `playback.clear` | 立即清空本机播放队列，屏蔽已打断回复迟到音频 |
| `records.saved` | 已获既有记录 API 确认，含 recording_session_id |
| `records.pending` | 已落盘队列仍待上传，不应展示“已保存” |
| `records.error` | 未确认完整保存，保留页面文字排查 |
| `status/error` | 展示可读信息/安全错误码；不包含密钥或上游原始载荷 |

原始队列在数据库同目录 `voice_outbox/user_<id>`，属于敏感本机运行数据，不提交 Git。JWT 失效时重新登录再补传，队列不保存 JWT。补传仅扫描该用户目录。生产部署须给页面和 WebSocket 同时配置 HTTPS/WSS 反向代理，并填写精确允许的浏览器 Origin。

## 树莓派保留入口

[device/voice_client.py](device/voice_client.py) 是与网页使用相同协议的独立 Python 终端，不依赖完整后端。`AudioDevice.read/write/close` 封装音频设备，后续可替换成 ALSA、I2S 或机器人自己的音频驱动；麦克风和扬声器无需与服务端同机。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r device/requirements.txt
# 真实收音/播放额外安装：Pi 上先 sudo apt install portaudio19-dev python3-dev
pip install PyAudio==0.2.14
python device/voice_client.py --server https://你的系统地址 --username 你的系统用户名 --device-id raspberry_pi
```

密码交互输入，不写命令行。也可通过进程环境 `ROBOT_CARE_ACCESS_TOKEN` 提供现有登录 JWT。终端输入 `q` 结束保存、`i` 打断、`m/u` 暂停/继续。远程连接强制 HTTPS/WSS；开发时可用 SSH 将远程系统转发到本机 localhost。纯协议验证可用 `--wav 虚构语音.wav --no-playback`，不打开真实麦克风/扬声器；WAV 必须 16 kHz、单声道、16bit PCM。

本轮开发平台为 Windows，树莓派仅保留协议与终端适配代码；ALSA/I2S、声卡、回声消除、ARM 安装及真机稳定性尚未实测。

## 验证与边界

已用真实授权服务验证鉴权、开场 TTS、虚构中文语音识别、动态回复音频、最终文字入既有 HTTP 记录 API，以及同一记录通过报告 API 返回 `mode=model`。一条完整合成输入的语音链路约 10 秒，收到了 384420 字节返回 PCM；这是一次开发测量，不是延迟承诺或真人验收。

报告 provider `doubao_realtime` 使用单独语音会话、固定合成触发与函数调用生成摘要，说明见 [报告配置](README_REPORTS.md)。普通 Ollama/千问/方舟文本 API 适配继续保留。规则情绪分类仍是规则引擎，不能把动态语音/报告接通说成专业情绪模型已通过验证。

本地回归还覆盖旧回复取消回执、重复完成事件、错误帧、浏览器 Origin、登录、单用户并发保护与模型格式回退。真实浏览器使用虚构 WAV 作为假麦克风进行专项检查，不采集现场环境或真人声音。真人听感、长期连续对话、正式内容审核、公司部署、Pi/机器人硬件、动作反馈及独立验收仍需后续完成。

同一真实云会话另完成三轮不同虚构输入（散步开心、独处孤独、计划看花），三条用户转录与含开场的四条助手文字全部保存，共七条，无重复；本次约 25.38 秒、1189820 字节返回 PCM。独立 `device/voice_client.py --wav --no-playback` 也在 Windows 跑通并收到 `records.saved`，证明终端协议可用，不代表 Pi 硬件验收。

后端全量回归：219 个测试、31 个子项通过；随后新增/完善的语音专项共 13 项通过（与全量用例有重叠，不相加）。前端生产构建与 TypeScript 通过，lint 基线无新增诊断。Edge 使用虚构 WAV 验证真实同源 WebSocket、收音帧、音频调度/结束回调、打断、暂停、停止麦克风、保存及手机宽度布局；这些软件证据不能替代真人实际听感。
