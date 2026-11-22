# 公开开发资料包

公开交接资料使用虚构数据库、示例凭据和配置模板。它不包含真实服务器口令、SSH 私钥、API 密钥、业务数据库或可连接生产服务器的私有安装包。

## 内容

- 当前完整源码和统一交接手册。
- `backend/tools/create_development_database.py`：从空数据库生成虚构账号与一份虚构 PHQ-9 对话报告，不读取或复制业务库。
- 发布附件中的 `xinyi-development-demo.db`：由上述脚本生成的示例库，仅用于本地开发。
- `deploy/edge/*.example`、`deploy/central.env.example`、`deploy/reports-windows/connection.json.example`：部署配置模板。
- `docs/reference/model-artifacts.json`：原始模型地址、固定提交和实际安装文件 SHA-256；权重从原作者获取，不把作者数据集当作交接附件。

权重来源：[SEGA 作者仓库](https://github.com/zhchen18/SEGA)、[中文 BERT](https://huggingface.co/google-bert/bert-base-chinese)、[中英翻译模型](https://huggingface.co/Helsinki-NLP/opus-mt-zh-en)、[七类情绪模型](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base)。这些辅助模型是当前项目的实验提取配置，不代表作者定制提取口径已经复现。133 字节 LFS 指针不能作为模型使用。

## 生成或使用示例数据库

在已安装项目依赖的新开发副本中执行：

```powershell
& ./.venv/Scripts/python.exe ./backend/tools/create_development_database.py --output ./runtime/public-demo/xinyi-development-demo.db
```

目标文件存在时脚本拒绝覆盖。脚本仅生成 `development_admin`、`development_user` 两个虚构账号，密码均为公开示例 `DEMO-ONLY-CHANGE-ME`。这不是现有平台的管理员账号或口令。

如使用发布附件，先将示例数据库放到新开发副本的 `runtime/public-demo`。设置该开发进程：

```powershell
$env:APP_ENV='development'
$env:ROBOT_CARE_DEPLOYMENT_ROLE='standalone'
$demoPath=(Resolve-Path './runtime/public-demo/xinyi-development-demo.db').Path.Replace([char]92,[char]47)
$env:DATABASE_URL='sqlite:///'+$demoPath
$env:SECRET_KEY='development-only-public-example-key-never-use-in-production'
$env:ROBOT_CARE_VOICE_ENABLED='false'
$env:ROBOT_CARE_GUIDED_SCREENING_ENABLED='false'
$env:ROBOT_CARE_REPORT_PROVIDER='disabled'
& ./.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir ./backend --host 127.0.0.1 --port 8000
```

另一个终端在 `frontend` 中设置 `BACKEND_URL=http://127.0.0.1:8000` 后运行前端。管理员登录后切换到“测试记录”查看虚构报告。语音需要开发者自行配置获授权的豆包密钥；公开资料包不提供可用云密钥。

这些账号和签名值故意公开，只可用于隔离的本地开发，不得用于生产。已有本机 edge 环境与正式服务器不要指向该示例库。

## 真实运行资料

真实数据库、管理员凭据、SSH 密钥和 API 配置仍在负责人控制的私有运行目录与服务器上。交接时使用受控的私有渠道，不通过公开仓库明文发布。后续加密不能收回此前已经公开的 Git 历史、下载和 fork 副本。
