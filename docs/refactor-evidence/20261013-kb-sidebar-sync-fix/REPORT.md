# 知识库最近侧栏同步修复报告

状态：修复及源码级验证完成；真实 Orca 创建/改名/删除复验由 Root 独占执行，本报告不把单位 GREEN 或 build 当作 GUI 验收。

## 问题和变更

Root 真实操作证据 059、119–127 表明，同路由保存后侧栏保留旧名，删除后保留失效入口。原实现仅在 Platform 挂载和 route.path 改变时刷新；异步读取缺少时序保护。

只修改 `frontend/src/api/index.ts`、`frontend/src/views/Platform.vue`，新增 `frontend/src/views/Platform.recent-sync.test.mjs`。API 的 createKb/updateKb/copyKb/pinKb/deleteKb 成功后发出无载荷通知；失败保持原拒绝、不通知，成功原样返回响应。Platform 挂载订阅、卸载解绑，收到通知后沿用原查询和排序。请求序号防止旧成功/失败及 finally 覆盖新列表或加载状态；聊天、新对话、评测分支忽略知识库 mutation 通知。评测及卸载使旧查询失效。

设计、取舍、授权和实施记录见 [DESIGN.md](DESIGN.md)、[PLAN.md](PLAN.md)。普通修复已获用户授权且 Root 认可此设计；遵循禁止 Git 写入，不执行 commit/stage/push，不创建额外 module 层。

## 实际验证结果

| 检查 | 实际 exit | 计数 / 说明 |
| --- | ---: | --- |
| 原生产代码 RED：`node --test frontend/src/views/Platform.recent-sync.test.mjs` | 1 | 19 tests，5 pass、14 fail，0 skipped/cancelled/todo |
| 最小修复 GREEN：同一命令、同一测试 SHA | 0 | 19 tests，19 pass、0 fail，0 skipped/cancelled/todo |
| `frontend` 中 `npm run test:unit` | 0 | 389 tests，389 pass、0 fail，0 skipped/cancelled/todo；71.952 秒 |
| `frontend` 中 `npm run build` | 0 | 构建完成，17.405 秒；保留现有 >500 kB chunk 提示 |
| `git diff --check -- frontend/src/views/Platform.vue frontend/src/api/index.ts` | 0 | 无空白差异错误 |

原始命令、工作目录、实际 exit 和耗时分别保存在 [red.json](red.json)、[green.json](green.json)、[unit.json](unit.json)、[build.json](build.json)、[diff-check.json](diff-check.json)。完整 stdout/stderr 在对应 `*.stdout.txt`、`*.stderr.txt`，计数抽取记录在 [test-counts.json](test-counts.json)。所有执行输出先捕获到 `.log`，结束后逐字节改名为 `.txt` 避免仓库 `*.log` 忽略规则；保留 RED 失败证据。

RED 的 create/edit/copy/pin/unpin/delete 断言均实际得到 1 次读取，期待成功后的第 2 次读取；详情保存仍为旧名称；旧读取会重新引入已删除项、清空新结果、终止最新加载、覆盖聊天/评测及卸载后状态。没有缺失导入、编译异常或静态字符串伪回归。GREEN 覆盖上述行为及失败不通知、响应身份、服务端顺序、page_size=5、既有 knowledge_bases 字段与兜底名称。

测试执行现有已安装 Vue compiler-sfc/esbuild 编译后的真实 API 和 Platform 脚本；保留真实 Vue ref/watch，在 VM 中替换 HTTP client、路由和生命周期宿主，deferred 请求受控决定返回顺序。新测试完全不启动浏览器、不访问服务器/QA 数据。指定 `npm run test:unit` 运行仓库已有检查，包含已有隔离的 headless Playwright 用例；未操作真实 Orca、GUI、QA 服务或真实业务数据，未安装依赖。

## 差异与源身份

完整生产代码及新增测试差异：[code-complete.diff](code-complete.diff)。它使用修改前精确源快照计算，包含新增测试全文；变更前快照 `before-Platform.vue.txt`、`before-index.ts.txt`，哈希分别见 [before-sha.json](before-sha.json)、[after-sha.json](after-sha.json)。测试 SHA 在 RED 与 GREEN 之间未变化。

| 文件 | 修复后 SHA-256 |
| --- | --- |
| Platform.vue | `46827813528834e5bdacd80c467c777e51b82c4d94e6612dfbd0d3371985901a` |
| api/index.ts | `22a48b23bdf24718bcd90d68bba2cf6b7ccb522bda57eb4b3fa954987ef8dd51` |
| Platform.recent-sync.test.mjs | `1429b448bb1fa452dd399ba2d7e658802101dfe9c7a6614a167a7da0e42aeede` |

验证临时 runner 已精确归档 [validation-runner.source.py.txt](validation-runner.source.py.txt) 和 [validation-runner-sha.json](validation-runner-sha.json)，核对原文件/归档 SHA 相同后删除，删除记录 [validation-runner-removal.json](validation-runner-removal.json)。最终文件和链接核查见 `final-audit.json`；文件清单哈希见 `evidence-sha.json`。

## 关注项和验收边界

无已知源码验证阻塞。现有大 chunk 构建提示不在本修复范围。成功 mutation 后侧栏重新读取真实服务端列表，读取失败沿用原行为清空，不推断/伪造创建结果；HTTP、数据库、权限和网络时序的真实 GUI 结果仍待 Root 复验。

KB-DETAIL-LOAD-002（直接访问已删除 ID 后正文空白、仅短暂 toast，Root 127 证实 GET 404）已记录为独立后续问题，本次不修改 KnowledgeDetail.vue。未修改 Core/Desktop/锁文件/依赖/其他页面、主验收文档或既有 Windows 包 manifest/receipt。Vite HMR 对本次前端源码迭代为预期，下一 Windows 包必须使用新源码 hash；旧包证据保留。

工作区其他已有改动保留。生成的 frontend/dist 仍由既有 .gitignore 忽略；本 worker 没有执行 Git 写入。
