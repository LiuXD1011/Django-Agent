# 知识库侧栏同步修复独立审查

审查日期：2026-10-13。范围仅为本次侧栏同步修复：`frontend/src/api/index.ts`、`frontend/src/views/Platform.vue`、`frontend/src/views/Platform.recent-sync.test.mjs` 及修复证据。已读项目 `AGENTS.md`、准确需求 [sidebar-fix-brief.md](../20261013-root-browser-business/sidebar-fix-brief.md)、修复 [REPORT.md](../20261013-kb-sidebar-sync-fix/REPORT.md) 和完整 [code-complete.diff](../20261013-kb-sidebar-sync-fix/code-complete.diff)，完整阅读三个受审文件；核对现有 HTTP client、已安装 Axios/Vue 类型及调用者。没有审查整个分支，也没有修改生产代码、测试、依赖、主验收文档、GUI、服务或 QA 数据；没有执行 Git 写入、提交或发布。

## 两个结论

**Spec compliance：通过本次源码与受控异步行为审查。** 六类操作（create、edit、copy、pin、unpin、delete）在 mutation 成功后刷新同路由侧栏；失败不通知且保持原拒绝对象；旧读取不能覆盖最新成功结果、清空最新结果或提前结束加载；聊天、新对话、评测及卸载行为符合需求。该结论不替代 Root 的真实 Orca 验收。

**Code quality：通过；未发现需修复的阻塞或非阻塞 finding。** 变更复用原 API、原列表映射与 Vue 生命周期，没有轮询、额外兼容层、排序变更或依赖。当前唯一生产订阅者在 Platform 内，调用受自身 try/catch 保护的异步读取；成功 mutation 不等待列表读取完成，列表读取失败保持原清空语义，不会把服务端 mutation 成功变为列表失败。

## 具体核查和行为证据

| 需求 / 风险 | 源码位置 | 审查证据与结果 |
| --- | --- | --- |
| 只在成功后通知且保持原响应 | `api/index.ts:227`、`:247`、`:249`–`:252` | await 原 client Promise 后发出无参数通知并原样 return response。新测试六类 mutation 分别使用 deferred Promise，确认 pending 时没有额外 GET、成功后只有第二次读取、请求 URL/body 不变、响应对象身份相等。 |
| 失败不假成功 | `api/index.ts:228`；`api/client.ts:29`、`:55` | 原 client 成功拦截器返回原响应 data，失败拦截器拒绝原业务错误对象；通知位于 await 之后。测试六类 rejection 保持同一失败对象，侧栏读取数仍为 1、旧项仍在。现有 Core `application.ts:103`、`:104` 定义成功与错误 HTTP 语义，未引入新的业务成功判断。 |
| 详情保存及时改名 | `Platform.vue:141`；现有 `KnowledgeDetail.vue:797` | 现有详情保存沿用 updateKb；新测试在详情路由保存后直接得到服务端新名称且 route 不变。无需改详情页。 |
| 旧读取不覆盖最新结果 | `Platform.vue:93`、`:105`、`:113`、`:121`、`:123` | 每次读取分配递增序号，成功、catch、finally 均校验当前请求。deferred 测试实际检验已删除条目不能回流、旧失败不能清空新成功、旧完成不能停止当前 loading。 |
| 卸载解绑与请求失效 | `Platform.vue:147`–`:150`；`api/index.ts:222`–`:224` | 卸载标记 disposed、增加序号并取消订阅；测试先留 pending 读取再卸载，之后 mutation 不再读取，晚到结果不再修改 items/loading。Vue 生命周期类型声明确认所用 API 可用。 |
| 聊天 / 新对话 / 评测分支 | `Platform.vue:96`、`:103`、`:139`、`:142` | 三条分支通知不引发 KB 读取；路由切换到聊天时会话结果不被旧 KB 结果覆盖；切到评测立即清空并使旧请求失效。沿用原页大小、会话字段和名称兜底。 |
| 原顺序及真实列表 | `Platform.vue:112`–`:118` | 仍请求 page=1/page_size=5，沿用 items/knowledge_bases 字段、服务端顺序、slice(0,5) 与原名称兜底；测试返回 6 项和 legacy 字段，确认前 5 项顺序不变。未构造本地成功结果。 |
| 权限 / Key / 新命令 | 完整生产 diff | 通知没有 ID、名称、response、Key 或权限载荷；读取仍调用原 client/searchKbs，无新增 shell、进程、网络地址、存储写入、auth 传输修改或权限判断。仅新增原请求成功后的既有 GET。此项是 diff 范围审查，未宣称重新完成系统级权限测试。 |

测试执行真实 API 文件和真实 SFC script 的 Vue compiler-sfc/esbuild 编译产物，保留 Vue ref/watch，仅替换 HTTP client、路由和生命周期宿主。受控异步请求替身不涉及真实后端，不使用静态字符串断言代替行为。

## 源码身份及执行结果

[source-sha.json](source-sha.json) 实际计算当前三个文件 SHA，与修复报告及 after-sha.json 全部一致。用修改前精确快照和当前文件重建完整 unified diff，与修复 code-complete.diff 逐字节一致，见 [diff-identity.json](diff-identity.json)。

| 文件 | 当前 SHA-256 |
| --- | --- |
| Platform.vue | `46827813528834e5bdacd80c467c777e51b82c4d94e6612dfbd0d3371985901a` |
| api/index.ts | `22a48b23bdf24718bcd90d68bba2cf6b7ccb522bda57eb4b3fa954987ef8dd51` |
| Platform.recent-sync.test.mjs | `1429b448bb1fa452dd399ba2d7e658802101dfe9c7a6614a167a7da0e42aeede` |

独立运行命令 `node --test frontend/src/views/Platform.recent-sync.test.mjs`，cwd 为项目根目录，实际 **exit 0，19 tests / 19 pass / 0 fail，0 skipped/cancelled/todo**。原始 stdout/stderr 及执行记录为 [focused.stdout.txt](focused.stdout.txt)、[focused.stderr.txt](focused.stderr.txt)、[focused.json](focused.json)。本审查没有重复完整 unit suite 或 build。

逐项核对既有原始 stdout/stderr 和实际 exit 记录，生成 [prior-evidence-audit.json](prior-evidence-audit.json)：

| 原执行证据 | 保存的实际 exit | stdout 实际计数 / 结果 |
| --- | ---: | --- |
| 原生产代码 RED | 1 | 19 tests，5 pass / 14 fail；13 个 ERR_ASSERTION，1 个因旧失败清空最新列表导致读取 undefined.id 的 ERR_TEST_FAILURE；没有导入/编译错误。 |
| 修复 GREEN | 0 | 19 tests，19 pass / 0 fail。 |
| frontend npm run test:unit | 0 | 389 tests，389 pass / 0 fail。 |
| frontend npm run build | 0 | stdout 为 `✓ built in 15.65s`；外层 runner 耗时 17.405 秒，二者口径不同且一致；stderr 保留既有 >500 kB chunk 警告。 |

这些是修复 worker 已保存的运行证据核查，不冒称本审查重新执行了 RED、完整 unit 或 build。最新独立行为验证仅为上述 19 个相关测试。

## Finding 与未能验证项

**Finding：无。** 本次范围内没有确认到需要修复的代码或需求违背。没有用推测扩展本次修复范围。

真实 Orca 操作由 Root 独占，本 reviewer 未操作或观察 GUI。收到任务时，Root 已报告 create 操作立即新增侧栏，rename/delete 正在重跑；这里只记录来源与当时状态，不将未完成操作写为 final PASS。真实 HTTP/数据库/权限与浏览器网络时序的端到端结论以 Root 最终证据为准。未重新验证 Windows 包；也未修改旧包 manifest/receipt。直接访问已删除知识库 ID 的详情错误展示（KB-DETAIL-LOAD-002）是已记录的独立问题，不在本次侧栏同步修复范围。

## 自有临时文件和审查产物

唯一行为验证临时 runner 为本目录 `review-runner.py`；执行结束前逐字节归档到 [review-runner.source.py.txt](review-runner.source.py.txt)，核对相同 SHA 后精确删除原路径，见 [temp-cleanup.json](temp-cleanup.json)。没有删除或清理他人的临时文件。

报告链接、源码复核、审查目录 SHA 及最终审计工具自身的精确清理记录见 [final-audit.json](final-audit.json)、[evidence-sha.json](evidence-sha.json)、[final-audit-cleanup.json](final-audit-cleanup.json)。
