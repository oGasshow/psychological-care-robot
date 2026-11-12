# D04：演示进程停止归属修复

> 历史归档：日期、基线与结论保留当时口径，文档位置和链接已更新。当前操作与待修问题请看[文档导航](../../README.md)和[当前状态](../../status.md)。

本次修改`backend/tools/demo_care.py`，新增`backend/tests/test_d04_lifecycle.py`；原106项测试及原2.4的58项断言未改。

prepare为独立runtime生成随机runtime_id。start按每个服务另生成process_id，在进程环境传入runtime_id、绝对runtime目录和process_id；台账保存完整argv、工作目录、runtime归属及从操作系统实际读取的创建身份。任何启动身份无法核验时不会补写“已验证”身份。

Linux身份包含boot_id、/proc start_ticks、UID、完整argv、cwd和上述环境标记。停止时先匹配台账/runtime/完整身份，再打开pidfd绑定进程实例，在绑定之后重新核验，最后通过pidfd发送SIGTERM。没有pidfd支持、/proc不可读、PID复用、命令/目录/环境标记不符时不发送信号，保留台账并给出原因。该分支本次仅进行了纯mock核验，没有实际Linux、ARM或树莓派运行证据。

Windows记录完整解析后的argv和创建时间，读取CIM的创建时间并与原生进程句柄校验。停止时打开具体进程句柄，再核对同一实例创建时间与当前完整身份，然后通过该句柄终止并等待退出。venv redirector的实际解释器子进程须另行登记完整身份；系统conhost仅在确认为System32原件路径、完整参数、父子关系及创建时间均符合时登记。停止逐个核对登记身份，不再使用通用“-m”、参数子串或无条件停止整个PID树。未知子进程也会阻止该项宣称完全停止。

stop输出每项stopped、already_gone或not_stopped及短原因。存在未完成项时保留pids.json、追加stop_attempt日志并以退出码2返回，后续start继续拒绝覆盖；仅全部核验完成才归档台账。已经没有当前台账时，重复stop明确输出already_stopped=true和空结果。旧台账缺少创建身份时采用ownership_record_unverified拒绝，不能因为它保存了相同模块名就代为结束进程；旧运行应由持有方独立核对归属并处理，不自动推断身份。

开发自测入口（backend工作目录，复用module24隔离venv）：

```powershell
python -m pytest tests/test_d04_lifecycle.py -q
python -m pytest tests/test_care_deployment.py::test_N44_real_prepare_start_stop_and_restart_preserves_data -q
```

最终18项mock通过（3.47秒），覆盖无关python -m、同模块不同runtime、PID/start_ticks/boot/UID/cwd变化、不可读身份、旧台账、未知/复用子PID、检查后PID复用、缺pidfd、正确pidfd及Windows句柄创建身份。所有mock均没有实际查询或结束无关进程。原验收Linux探针保持内容原样复制后执行，退出0、信号0次、未删旧台账；该探针不具备新身份字段，因此实际观察为安全拒绝旧台账，新格式正确归属和复用边界另由新增测试覆盖。

实际Windows原N44测试通过（70.74秒）：新prepare、拒绝覆盖、真实API/worker start→stop→同runtime restart→stop，数据和匿名编号保留；另真实重复stop退出0、already_stopped=true，后台端口已关闭。本项使用--no-frontend，未启动Next；整包API/worker/Next生命周期由主流程另行执行。证据在`runtime/d04_evidence/pytest_mock_verified`、`pytest_windows_verified`、`windows_stop_ledgers`、`windows_repeated_stop.json`及`original_linux_probe_verified.json`。

首次Windows定向执行因尚未登记系统conhost子进程而受控拒绝停止，失败证据保留在pytest_windows；随后补齐严格系统子进程身份捕获，仅对本次已记录的启动实例重新核验和清理，再使用新隔离runtime复测成功。未按进程名批量结束其他任务。未导出access.json、密码、令牌或运行数据库，独立验收仍由原验收聊天复核。
