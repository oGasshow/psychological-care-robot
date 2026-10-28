# /robot-care 前端

新增历史、会话与更正、摘要、量表只读、按版本分组的类别/量表时间变化、统一 ReportDTO 预览及打印页面。复用原 JWT 登录，不显示账号姓名。所有新内容由 React 文本节点呈现，不使用 HTML 插入。报告正文只保存在组件内存；sessionStorage 仅保存查询范围。退出登录清除范围。

## 本地运行

使用 Node 22.14.0、npm 10.9.2。先在后端准备专用虚构演示库，再在本目录运行：

```powershell
npm ci
$env:BACKEND_URL='http://localhost:8000' # 实际内部后端地址
$env:NEXT_TELEMETRY_DISABLED='1'
npm run build
npm start -- --hostname 127.0.0.1 --port 3000
```

访问 /login，既有登录成功后进入 /robot-care。浏览器仅请求同源 /api；Next 在服务端按 BACKEND_URL 反代。该值在 build 阶段写入 rewrite，因此改变服务端地址后须重新 build。生产域名由外层 Nginx/公司反代指向 Next，内部后端地址不会变为浏览器请求目标。配置样例仅为占位，不含凭证。

原页面中的固定 127.0.0.1 API 主机也已统一改为同源路径。移除构建时 Google Font 下载，使用系统中文字体；不需从外站下载字体或原始媒体资源。

## 浏览器及 PDF 证据

playwright-core 固定版本，仅调用本机现有 Edge，不下载浏览器。指定隔离演示账号（不得使用生产账号），并使用新的证据目录：

```powershell
$env:CARE_BASE_URL='http://localhost:3000'
$env:DEMO_USER='<专用虚构账号>'
$env:DEMO_PASSWORD='<本地演示密码>'
$env:EVIDENCE_DIR='<独立证据绝对路径>'
node tools/browser-evidence.mjs
```

脚本实际通过登录表单鉴权、读取后端会话、提交一条含 HTML 的虚构更正后再用新 revision 恢复，验证原文不变及文本转义，检查量表/趋势/错误页，通过最新报告 DTO 执行 Chromium 打印生成 PDF。截图和 JSON 不包含 token 或密码。打印按钮的 window.print 仅在测试中替换为调用标记，随后使用同一浏览器真实打印引擎 page.pdf 输出 PDF；并不声称操作了人工打印对话框。PDF 还须经 pdftoppm 渲染核对中文、分页及每页演示标识。

打印页打开时重新请求 ReportDTO，点击打印按钮再重新核验来源；请求失败会清除旧预览，禁止将旧报告伪装成当前结果。模拟标识使用命名 @page 的 bottom-center 页脚，每页重复并带页码；按 data-is-test 区分演示和普通摘要。此打印能力在当前 Edge 实测，其他浏览器需另测。无真实接收、真实安全动作、正式量表审核或医疗诊断入口。
