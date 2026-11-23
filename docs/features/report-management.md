# 用户报告管理端

[文档导航](../README.md)

入口 `/care-admin`，使用单独授权的管理账号登录。管理员登录后直接进入报告管理；访问个人空间、语音或量表页面也会回到报告管理。普通用户继续使用自己的个人空间。

## 页面功能

管理端只提供“查找用户 → 选择历史报告 → 查看／打印”的流程：

2026-11-23 补充：按用户最新要求，现另有“待联系提醒”。检测已保存记录中的明确安全线索后，管理员核实并人工联系；可点击“确认已人工跟进”写入审计。系统不自动发短信或拨号。详情见[报告后台检查](report-backend-audit-2026-11-23.md#第8部分-建议与人工联系)。这一确认接口是报告管理只读规则的特定例外，不开放其他用户业务写操作。

- 按账号搜索用户、分页查看全部普通用户。
- 显示每个用户可查看的报告数量和最近报告时间。
- 选择用户后查看其多次对话的完整报告，包括报告原有的分数、覆盖率、总结与建议。
- 读取最新内容后打印或保存为 PDF。

不提供语音聊天、量表填写、个人空间、关怀跟进编辑或独立的关怀状态面板。业务报告默认显示，测试报告单独切换。只列出已结束且记录收齐的会话；尚未收齐、正在进行或已删除的会话不计入可查看报告数量。

列表每分钟刷新一次，也可手动刷新。管理接口只读，不允许修改备注、重新生成文字或删除报告。此前保存的跟进数据没有删除，但已不向管理页面提供。

## 报告一致性与权限

用户端已成功生成的模型文字保存在 `robot_record_care_report_wordings`，管理端直接读取同一来源版本的报告，不在查看时调用模型重新生成。没有当前有效模型文字时使用现有规则总结。用户端显式重新生成后，管理端刷新可读取最新文字。转录更正或对话删除会使旧文字失效，管理端不能继续读取被删除的报告。

注册接口不授予管理权限。后端每次从 `robot_care_report_managers` 核验授权；账号停用或授权撤销后，原 token 不能继续读取管理接口。普通账号仍只可访问自己的记录。访问动作记录在 `robot_care_management_audit`，不重复保存报告原文。

部署负责人通过本地命令创建、授权或撤销专用管理账号，密码交互输入：

```powershell
& ./.venv/Scripts/python.exe ./backend/tools/manage_reports.py create --username care_manager --runtime <runtime>
& ./.venv/Scripts/python.exe ./backend/tools/manage_reports.py grant --username care_manager --runtime <runtime>
& ./.venv/Scripts/python.exe ./backend/tools/manage_reports.py revoke --username care_manager --runtime <runtime>
```

`<runtime>` 为活动 `access.json` 所在的私有运行目录。本机管理账号信息保存在忽略 Git 的 `runtime/report-management-access.json`；不向仓库提交账号密码、token 或数据库。当前一个部署对应一个机构，管理账号可读取该部署的全部普通用户，尚未实现多机构租户分区。

## 小程序／App 读取接口

当前交付为电脑和手机浏览器可用的网页及 API，尚未制作原生 App 或微信小程序。后续客户端通过 `POST /api/auth/login` 登录，在请求中携带 `Authorization: Bearer <token>`。`GET /api/auth/me` 的 `can_manage_reports` 可用于入口展示，权限仍由服务端核验。

| 接口 | 用途 |
|---|---|
| `GET /api/care-management/users` | 搜索、分页查询用户及报告数量 |
| `GET /api/care-management/users/{uid}` | 指定用户的账号及报告概况 |
| `GET /api/care-management/users/{uid}/sessions` | 已完成且可查看的历史报告列表 |
| `GET /api/care-management/reports/{sid}` | 读取指定报告，返回 `user_id` 和 `report` |

用户列表参数为 `q`、`is_test`、`limit`、`cursor`。历史报告列表参数为 `is_test`、`limit`、`cursor`。`is_test` 默认 `false`；分页返回 `{items,next_cursor}`，默认 20 条，上限 100。游标绑定当前管理账号、用户及筛选范围。

用户概况包括 `user_id`、`username`、`is_active`、`is_test`、`report_count`、`latest_session_id`、`latest_at`。没有报告时数量为 0，最近报告字段为 null。管理接口不提供跟进状态、备注或个人操作接口。所有管理响应设置 `Cache-Control: no-store`。

详细契约可查看后端 `/docs`。甲方从其他设备远程访问需要服务器与 HTTPS 域名；本机 `127.0.0.1` 地址不对外提供访问。微信登录、订阅消息和 App 推送尚未配置，目前通过管理端登录查询与刷新获取报告。
