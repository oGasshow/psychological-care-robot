# 20轮专项回放

本清单是预先固定的虚构数据：每批20轮，每轮一条用户终态和一条助手终态，共40条。normal与fault的会话、轮次和消息ID分别固定，不能为改善统计结果临时替换ID。正文和UTC时间见同目录`twenty_turns.json`。

在backend目录、已安装锁定依赖的Python环境中执行：

```powershell
python tools/replay_twenty.py --output-dir <新的绝对证据目录>
```

不传`--base-url`时，脚本创建临时隔离数据库、虚构账号和仅监听127.0.0.1的后端，设置APP_ENV=test、规则引擎、量表disabled、策略模拟false。进程记录和脱敏日志写入证据目录，运行库及令牌在临时目录中清理，不复制进交付。

也可显式传`--base-url`，令牌只从`ROBOT_TOKEN`环境变量读取；该方式仅应指向已授权的专用测试账号和测试后端，账号下不得已存在这两批固定ID。重复验收请用新的隔离测试库/账号和新证据目录，保留旧证据，不能删改已存在的业务数据凑通过。

normal批次先入队40条，关闭前worker无任何HTTP调用，状态为“等待会话结束”；封存上界40后异步上传，凭当前账号GET查回全字段、归属、唯一性并同时统计记录成功率和完整轮率。

fault是另一独立批次。脚本真实启动和终止上传进程，依次核对未关闭保留、401身份暂停、暂停重启无HTTP；真实loopback代理首次建会话返回503，下一次恢复；第7条后台提交后、客户端ACK持久化前强制终止worker，再用新PID重启。恢复前后分别保存统计，始终以40条和20轮为分母；重复第7条只返回原记录，不增加分子或分母。额外open会话保留且不阻塞sealed批次，序号分配重启后从2继续。

核心证据：`fixed_manifest.json`、`normal_open_status.json`、`normal_final.json`、`fault_before_recovery.json`、`fault_after_recovery.json`、`attempts_*.jsonl`、`process_lifecycle.json`及`twenty_summary.json`。尝试日志只保存HTTP路径、序号、状态和耗时；固定清单及查回正文均为本次声明的虚构文本。此回放不调用模型、真实语音、公司网络或硬件。

接入时显式设置`ROBOT_UPLOAD_POLICY=after_close`。CLI读取该配置；库构造使用`Outbox(..., upload_policy='after_close')`。旧默认仍为streaming。两种策略共用持久会话状态、序号高水位、身份暂停和重试数据；after_close的close任务还会等同会话消息全部ACK后领取。录音回调只调度文本任务，既有`enqueue_async`把磁盘事务移到工作线程；实际语音回调仍需后续集成验证。
