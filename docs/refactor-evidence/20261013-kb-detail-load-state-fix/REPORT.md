# KB-DETAIL-LOAD-002 详情加载状态修复

2026-10-13，本次代码与受控生产组件回归已完成。真实 Orca 复验由 Root 独占执行；本报告不宣称真实浏览器复验、整组 B 或整个 Goal 完成。

## 问题与改动

真实已删 ID 的 [125 操作结果](../20261013-root-browser-business/125-stale-recent-result.json)、[126 截图](../20261013-root-browser-business/126-stale-recent-screen.png)、[127 资源时序](../20261013-root-browser-business/127-stale-resource-confirm.json)显示 GET 404，短暂失败 toast 后 mainText=null。根因是 `load()` catch 仅发送 toast，且正文 `main` 仅在 `kb` 有值时渲染。侧栏同步修复不能覆盖直接打开无效或无权限链接。

仅修改 [KnowledgeDetail.vue](../../../frontend/src/views/KnowledgeDetail.vue)，新增 [行为回归](../../../frontend/src/views/KnowledgeDetail.load-state.test.mjs) 和 [真实布局回归](../../../frontend/src/views/KnowledgeDetail.load-layout.test.mjs)：

- 首次加载有 main 与 role=status 的“正在加载知识库…”；正文数据仍读取时保留加载提示。知识库、标签、文档读取失败均有持久错误正文。
- 401/403/404/410 使用同一文案“知识库不存在、已删除或无权访问”，提供返回知识库列表按钮，不显示资源属于特定账户或任何服务错误详情。
- 网络与其他服务失败提示“知识库加载失败，请检查网络或稍后重试”，重试按钮调用原生产 `load()`，等待真实读取结果；pending 时不显示重试按钮或成功结果。
- `load()` 每个阶段、catch 与 finally 使用相同的未卸载/最新代次/当前路由判定，新 load 立即废弃旧文档请求。路由 A→B 重置旧标签和计数，旧错误或旧成功不能覆盖 B 或关闭 B 的加载提示。
- 加载/错误期间暂停状态轮询，成功恢复后处理中任务继续轮询。引用读取独立显示其状态；文档、Wiki、图谱、解析记录、分块与快速设置保留。
- 错误与首次加载 main 使用独立 scoped `kb-load-page`，面板 block/auto/visible 按内容展开，避免复用正常文档页固定 112px grid 首行；正常工作台与全局 CSS 未改变。

[设计与计划](PLAN.md) 已由 Root 认可。没有改 Platform/API/auth/Core/Desktop、全局 CSS、依赖或锁文件；没有提交、暂存、Git 写操作、GUI/服务操作或真实 QA/管理员/Key/设备/资料修改。

## 验证

新测试实际编译生产 SFC 的完整脚本与模板，在真实 Vue 自定义 renderer 中挂载，使用真实生命周期、watch 调度和渲染按钮事件处理器。仅控制 API IO、window、定时器与外部 UI/子组件边界，没有源码 regex 断言，不使用真实网络或认证。该测试验证功能状态与导航目标，不替代 TDesign 的真实布局、网络认证或 Orca UI 验收。

| 验证 | 实际结果 | stdout / 退出码 |
| --- | --- | --- |
| 原实现 RED：`node --test src/views/KnowledgeDetail.load-state.test.mjs` | 17 项，4 pass / 13 fail；失败来自主区域缺失、错误和重试未渲染 | [RED](RED.stdout) / [1](RED.actualexit) |
| 补充边界 RED：同 ID 新加载旧文档结果、错误后重试轮询恢复 | 19 项，17 pass / 2 fail；明确旧 docs 可早发布与恢复后无轮询 | [EDGE-RED](EDGE-RED.stdout) / [1](EDGE-RED.actualexit) |
| 最终 GREEN：同一生产路径回归 | 19/19 pass，0 fail | [GREEN](GREEN.stdout) / [0](GREEN.actualexit) |
| 首轮 `frontend/npm run test:unit` | 408/408 pass，0 fail，0 skip；该阶段未覆盖真实 CSS 布局 | [保留的完整输出](test-unit.stdout) / [0](test-unit.actualexit) |
| 首轮 `frontend/npm run build` | 成功，16.09s；Vite 提示部分 minified chunk 大于 500KB | [保留的完整输出](build.stdout) / [0](build.actualexit) |
| 布局 RED：实际全局 CSS / scoped SFC CSS / TDesign Button | 6 项，1289×921 三项 fail，1024×768 三项 pass；真实复现按钮被 112px panel 裁剪、中心命中 MAIN | [LAYOUT-RED](LAYOUT-RED.stdout) / [1](LAYOUT-RED.actualexit) |
| 布局修复后：layout + 原 behavior GREEN | 25/25 pass；两尺寸各有 pending/404/500，几何、中心命中、正常 pointer 点击返回，以及实际重试读取通过 | [LAYOUT-GREEN](LAYOUT-GREEN.stdout) / [0](LAYOUT-GREEN.actualexit) |
| 最终 `frontend/npm run test:unit` | 414/414 pass，0 fail，0 skip，48.94s | [最终完整输出](LAYOUT-test-unit.stdout) / [0](LAYOUT-test-unit.actualexit) |
| 最终 `frontend/npm run build` | 成功，13.96s；仍只有 minified chunk 大于 500KB 提示，无新依赖/配置更改 | [最终完整输出](LAYOUT-build.stdout) / [0](LAYOUT-build.actualexit) |
| `git diff --check -- frontend/src/views/KnowledgeDetail.vue` | 退出码 0，无空白错误 | [验证记录](validation.json) |

测试 runner 的退出码独立保存为 actualexit，不将日志采集 shell 的退出码当成测试结果。RED 最初开发自定义 renderer 缺少原生输入事件宿主方法时出现的 harness 错误已修正，归档的最终 RED 无运行时错误或未处理拒绝，只有行为断言失败。

## Root 真实 Orca 发现的 CSS 问题与修正

首轮 sourceSHA `84ee651d…` 的 19 项生产 VM 回归与 408 项前端测试只能证明状态逻辑。Root 真实 [004 截图](../20261013-kb-detail-load-state-orca/004-deleted-screen.png)、[005 GET404/正文](../20261013-kb-detail-load-state-orca/005-deleted-proof-box.json)、[006 权威几何](../20261013-kb-detail-load-state-orca/006-button-visibility-audit.json)明确显示：返回按钮虽在 DOM/AX，y153.84–185.84，却落在 top10/bottom122 的 overflow:hidden 面板下方，中心 elementFromPoint 命中 MAIN。因此首轮不能代表 002 已完全修复。

已只读核对当前 app.css 的 shell/workspace/content/detail/panel 和所有相关媒体分支、mobile.css 的 app-frame 祖先布局；新增真实 headless Chromium 布局回归使用完整生产 SFC、实际 app.css/mobile.css/编译 scoped CSS、真实 installed TDesign Button 与真实 memory router。只替换 API IO 和无关子组件，无真实服务/认证/资料访问。

1289×921 上 RED 重现 112px 裁剪，修复后按钮 y136.84–168.84 位于全部裁剪祖先及 viewport 内；1024×768 同样通过。中心命中真实按钮的 SPAN 子元素，使用正常 Playwright pointer click 返回列表；500 的真实重试按钮也完成二次读取后显示成功。没有 force/DOM.click、滚动绕过或修改全局 CSS。

## 产物与边界

- [code-complete.diff](code-complete.diff) 含本次全部生产与新增测试差异。
- [before.sha256](before.sha256) 与 [after.sha256](after.sha256) 标识实际读取的基线与最终代码；详情基线 `cff6e566…`，最终 `017504cd…`，行为回归 `c456d809…`，布局回归 `9a682525…`。[pre-layout.sha256](pre-layout.sha256) 与 [首轮限定 diff](pre-layout-code-complete.diff)保留首轮 `84ee651d…`，原 RED/GREEN/408/build 未覆盖。
- [临时归档脚本源码](archive.source.py.txt) 与 [精准清理记录](temporary-cleanup.json)记录原文件副本及 helper SHA，核对后只删除这两个自有临时文件和空的自有临时目录。
- [布局阶段归档源码](layout-archive.source.py.txt) 与 [布局阶段清理记录](layout-temporary-cleanup.json)记录本阶段 helper SHA，核对后精准删除自有 helper。
- Root 后续用同一正常 QA 浏览器 page 复验已删/无效直链、长期错误提示、返回动作及正常资料页面；可恢复失败的真实重试行为已经由受控生产组件证明，真实服务故障模拟不在本次 QA 环境执行。
