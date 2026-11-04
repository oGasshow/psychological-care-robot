# 从源码包重新安装

基线9355597；Next/eslint-config-next16.4.5，React/react-dom19.3.1。后端锁保持。既有登录、记录、规则分析、更正删除、来源分流和打印继续使用；本轮没有新建语音或量表计分系统。

## 前置工具与安装

Windows实测Node22.14.0/npm10.9.2、uv0.13.6、Python3.13.18及已有Edge；不是“最新工具”推荐。Next要求Node>=20.9，后端要求Python>=3.13；建议复现实测组合。可用PATH工具或传显式可执行文件路径，不修改全局安装或科研环境。

在新解包目录（支持中文和空格）运行：

```powershell
Set-Location '<新源码目录>'
./Setup-Project.ps1 -UvExecutable '<uv路径>' -PythonExecutable '<已有Python路径或3.13.18>'
```

工具在PATH时可直接运行脚本。可选参数`-NodeExecutable`、`-NpmExecutable`、`-UvCacheDirectory`。脚本以`uv sync --locked --group dev`创建根目录.venv，以`npm ci --include=dev`安装前端；检查锁哈希不变、项目sys.executable、uv pip check和npm ls。缺前置工具明确失败；只临时设置本进程环境并恢复。uv默认缓存放本项目.uv-cache，避免跨盘临时文件问题；下载解释器时仅放本项目.python；venv不假定有pip。无凭据回执在runtime/setup_receipt.json。

`-CheckOnly`只检查已有环境。可复用工具与下载缓存，不能复制旧node_modules、.next或venv冒充干净安装。证明同一Windows的新项目环境，不是全新电脑、Linux或Pi实测。

## 本地虚构演示

```powershell
./.venv/Scripts/python.exe backend/tools/demo_care.py prepare --runtime runtime/my_demo_001
./.venv/Scripts/python.exe backend/tools/demo_care.py start --runtime runtime/my_demo_001
./.venv/Scripts/python.exe backend/tools/demo_care.py stop --runtime runtime/my_demo_001
```

打开start输出的/robot-care地址并登录；随机账号密码只在本次专用runtime/my_demo_001/access.json，不提交或外传。首次start按实际后端地址构建Next同源反代；更改前端源码或BACKEND_URL后须重新build。prepare拒绝覆盖非空目录，restart保留同库数据与匿名编号，stop只核验本次实例。production禁止fixture/策略模拟；占位配置不带真实密钥，不用演示库替换现有库。

## 完整复核

使用新的证据目录，逐phase运行，失败试次另存，不覆盖旧验收：

```powershell
./.venv/Scripts/python.exe tools/verify-release.py backend --evidence runtime/check_001
./.venv/Scripts/python.exe tools/verify-release.py start --evidence runtime/check_001
./.venv/Scripts/python.exe tools/verify-release.py browser --evidence runtime/check_001
./.venv/Scripts/python.exe tools/verify-release.py lifecycle --evidence runtime/check_001
```

backend跑原180主测试/31子项、复制后的三个原探针和固定20轮；原探针code_commit旧常量不作本次提交判据。browser运行原13+来源9+provider6检查及7类PDF，可传`--browser`和`--node`；D03仅临时将专用fixture写为[]，finally恢复bytes/SHA，http_status数值与步骤status分开。PDF生成后必须Poppler逐页检查中文/分页/来源及非诊断页脚。lifecycle检查Windows三服务停止、重复停止、同库重启后计数一致及最终PID/端口关闭。Linux仍仅mock。工具从当前项目定位，不会指回旧source/venv；全部正文虚构，false标志只用于来源边界。

## 审计与静态检查

frontend中运行：

```powershell
npm audit --json --include=dev --package-lock-only --registry=https://registry.npmjs.org
npm audit --json --omit=dev --package-lock-only --registry=https://registry.npmjs.org
npm run lint
npm run lint:changes
```

当日全量high/critical均0，生产审计0；全量尚有16个moderate包级条目，沿lint链指向同一minimatch公告。修复11.0.1跨旧插件要求的3.x/10.x API，未强制覆盖/倒退/删除dev依赖或抬审计门槛。范围、路径和剩余原因逐项在交付材料中保留；不能据审计清零宣称绝对安全或公司生产验收完成。

React新版规则发现旧初始化时序问题，本轮只调整声明位置、可取消的挂载读取、日数时间快照及内部路由导航，不改业务接口、量表或分数。正常全仓lint仍有旧12错误/20警告（原13/20）；日志保留，不能称全仓lint通过。lint:changes保留所有ESLint规则，对比9355597实测诊断，新诊断即失败；新浏览器/检查脚本另行lint。

## 整项目接入

服务器合并代码和锁，先备份并在隔离副本验证原迁移，再运行FastAPI/SQLite/独立worker/Next，经公司HTTPS入口访问。Pi以后运行2.1音频/outbox及可选规则；2.5提供确认的量表记录，沿用live只读接口。X01—X07、正式内容审核及公司/Linux/Pi仍未实测。回退选择已验收9355597及原锁/备份，不覆盖或删除历史数据。
