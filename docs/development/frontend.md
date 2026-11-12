# 前端开发与浏览器验证

[文档导航](../README.md) · [开发指南](guide.md) · [当前状态](../status.md)

下面的 npm 和 node 命令从 frontend/ 执行；浏览器脚本按各自场景计数，不能代替当前完整回归或真实语音验收。

新增历史、会话与更正、摘要、量表只读、按版本分组的类别/量表时间变化、统一 ReportDTO 预览及打印页面。复用原 JWT 登录，不显示账号姓名。所有新内容由 React 文本节点呈现，不使用 HTML 插入。报告正文只保存在组件内存；sessionStorage 仅保存查询范围。退出登录清除范围。

## 本地运行

使用 Node 22.14.0、npm 10.9.2。先在后端准备专用虚构演示库，再在 frontend/ 目录运行：

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

打印页打开时重新请求 ReportDTO，点击打印按钮再重新核验来源；请求失败会清除旧预览，禁止将旧报告伪装成当前结果。命名 @page 的 bottom-center 页脚按 `data-data-nature` 为 test_only、non_test_only、mixed、empty 分别显示模拟、非测试标志、混合来源分流或无纳入来源，每页重复并带页码；非测试标志不代表真实来源、评估有效性或内容审核已确认。缺少新元信息时展示“数据性质待确认”，不根据旧 is_test 推断全部模拟。此打印能力需以当前交付中的实际 Edge/PDF 证据为准，其他浏览器需另测。无真实接收、真实安全动作、正式量表审核或医疗诊断入口。

## D02 数据性质与混合范围回归

报告显示 `data_nature_summary.dialogue/assessments` 的测试及非测试来源数量；情绪分类使用 `emotion_counts_by_nature.test/non_test` 分别显示。来源引用、量表、趋势分组与数据点各自保留测试属性。情绪与量表时间线都在各自分流内核对独立来源数，测试与非测试各 1 点不形成 2 点趋势；缺少属性时不画趋势。会话范围不自动关联量表，时间范围仍按原发生/已确认完成时间筛选。

保留原 `npm run browser:evidence` 的 13 项检查，另外运行：

```powershell
# 同样设置 CARE_BASE_URL、DEMO_USER、DEMO_PASSWORD、EVIDENCE_DIR；使用新的隔离证据目录。
node tools/browser-data-nature.mjs
```

新脚本通过原登录访问真实同源 API，在专用演示库中创建虚构文本，故意分别设置测试/非测试标志，覆盖单会话、混合会话、各自时间范围、范围外排除、空范围、仅 fixture 量表和非测试对话加 fixture 量表。脚本不修改 provider 配置或 fixture 文件，保留原有来源、归属及审核状态。全部正文始终虚构；`is_test=false` 仅用于验证元数据语义，不能把它称为真实用户实测。页面数量和类别计数须与实际 DTO 一致，混合各 1 点时不得画时间线。

脚本将输出 9 项场景的截图/元数据和 6 份浏览器 PDF（纯测试、非测试标志、混合、空范围、仅量表、非测试加 fixture），并保存每份预览和最终打印的确切 DTO JSON；打印时核对页面与该响应的 generated_at 一致。原 13 项脚本也保存其 PDF 对应的确切 DTO。这些是脚本预期输出；是否实际通过，以新证据 JSON、退出码及逐页渲染检查为准。测试会保留新增虚构记录，因此应始终使用专用演示运行目录，不对生产账户运行。
