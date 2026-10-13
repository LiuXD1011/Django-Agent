# KB-DETAIL-LOAD-002 设计与实施计划

授权：Root 已明确授权 Goal 2.3/2.4 普通设计及修复自主推进；本次禁止提交、暂存、真实 QA 数据写入、GUI 和服务操作。2026-10-13 Root 认可下述单文件设计。

## 根因与设计

实际 `KnowledgeDetail.vue` 为 1335 行，已完整阅读。`load()` 失败仅产生短暂 toast，正文 `main v-if="kb"` 在 null 时完全不渲染，真实证据 125/126/127 的已删 ID GET 404 与 mainText=null 因此一致。已有 kb/docs/citation 请求代次及卸载保护，必须保持并贯穿加载状态。

选择在现有详情组件增加页面级 loading/error 主区域，保留正常工作台所有功能。相比仅延长 toast（仍缺返回与重试）或另建错误路由（扩大路由模块和历史行为），单文件分支能保持当前 URL 并提供可访问的持久提示。

401/403/404/410 统一提示“知识库不存在、已删除或无权访问”，只提供返回知识库列表；其他服务/网络读取失败显示静态安全文案，并有重新调用实际 load 的重试按钮。页面不显示服务返回文本、路径、账户或标识。loading 有 role=status；error 有 role=alert；返回始终可用，不能虚构成功。正常文档、Wiki、图谱、任务、分块和快速设置保留。

load 使用同一 current 判定（未卸载、最新代次、当前 kbId 与 route 参数一致），在每个 await 后、catch、finally 检查。路由复用重置加载错误并清空旧统计/标签，避免旧请求关闭 B 的加载、旧错误覆盖 B 成功，以及卸载后改状态。

## 实施步骤

1. 新建 `frontend/src/views/KnowledgeDetail.load-state.test.mjs`：实际 Vue SFC 脚本与模板编译，Vue 自定义 renderer 挂载生产组件。仅替换 API IO、TDesign/子组件边界和 window；用 deferred 控制读取顺序。检查真实渲染树文本与事件处理器，不能源码 regex。
2. RED：初次 pending 必须有主区域加载状态；404/403 等必须持久错误+返回；网络/500 错误必须有调用 load 的重试；A→B、同 ID 新 load 和卸载晚完成不能发布过时状态。归档 stdout 与实际退出码。
3. 在上述单文件实现最小状态分支及请求保护，不改全局 CSS、API、认证、Core、Desktop、依赖或锁文件。
4. GREEN：运行新行为回归；运行 frontend `npm run test:unit` 与 `npm run build`，保存终态、stdout 和实际退出码。审阅限定差异，记录前后 SHA 与 code-complete.diff。
5. 报告只声明生产组件受控回归结果。真实 Orca 由 Root 独占重跑，整组 B/Goal 不在本任务宣称完成。自身临时脚本 SHA 归档后精准删除。

## 自检

范围仅详情加载状态、关联回归测试和本证据目录。授权覆盖技能默认重复审批/提交环节。无新增兼容层、外部副作用或依赖。未把侧栏修复当作无效直链的修复证据。

## Root 真实 Orca 布局反馈后的追加计划

Root 在正常浏览器 1289×921 实测发现：返回按钮存在于 DOM/AX，但错误 main 复用 `.kb-detail-page` 的 112px 首行，`.workspace-panel` 的 overflow:hidden 裁剪按钮。原 VM renderer 的 19 项仅覆盖功能状态，未覆盖真实 CSS，因此第一轮代码不能代表整个问题已解决。Root 明确授权单文件 scoped 布局修正。

1. 保存原 19/408/build 输出、pre-layout sourceSHA 与 code-complete.diff；只读核对 Root 004 截图、005 请求和 006 权威几何。完整读当前 app.css 的 shell/workspace/content/detail/panel 及相关媒体布局，读 mobile.css 的 app-frame 祖先布局。
2. 新建 `KnowledgeDetail.load-layout.test.mjs`：使用实际 app.css/mobile.css、完整生产 SFC 脚本/模板/编译 scoped CSS、真实 installed TDesign Button、真实 Vue/router，运行无真实服务的隔离 headless Chromium。1289×921 与 1024×768，各测 pending/404/500。
3. RED 断言实际按钮完全位于所有裁剪祖先与 viewport 内，中心 elementFromPoint 命中按钮或其子元素；不能只用 isVisible 或 CSS regex。正常 pointer click 返回真实 memory router 列表，500 点击重试实际重新读 KB。
4. 最小改动仅错误 main 使用 `kb-load-page`，scoped block/height100% 取代文档页固定 grid；错误 panel scoped block/auto/visible 按内容展开。正常文档布局与全局 CSS不改。
5. 运行 layout+behavior GREEN、frontend unit/build，独立保存 LAYOUT 前缀 stdout 与 actualexit，更新最终 SHA/完整限定 diff。真实 Orca 再验仍由 Root 执行。
