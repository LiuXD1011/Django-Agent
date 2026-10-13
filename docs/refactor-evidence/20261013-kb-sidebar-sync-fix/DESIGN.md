# 知识库最近侧栏同步设计

授权：Root 已确认用户 Goal2.3/2.4 批准普通设计及修复后自主实施；本设计获 Root 明确认可。禁止 Git 写入优先于 skill 提交惯例，文档保存在指定证据目录。

根因：Platform 仅挂载及 route.path 变化时读取最近项。KnowledgeBases 的 create/copy/pin/delete 和 KnowledgeDetail 保存均调用现有 api，但成功后未触发侧栏读取。旧的异步读取还能覆盖更新或新路由结果。

方案比较：推荐现有 api/index.ts 内成功 mutation 通知，由 Platform 订阅后查询真实数据；页面分别通知容易漏掉详情保存，并超出文件归属；轮询产生额外请求，不符合要求。无需新增 service/controller 层。

架构：api 模块维护无载荷订阅集合，导出 subscribeKnowledgeBaseChanges(listener: () => void): () => void。五个 mutation 方法（pin 包括取消置顶）仅在 authenticated client promise 成功后通知，返回原响应，失败保持拒绝。Platform 挂载订阅，卸载解绑；聊天/新对话/评测路由忽略知识库通知，其余路由延续原知识库分支。每次 loadRecentItems 递增序号；只有最新且未卸载的读取能写 recentItems/recentLoading。评测清空也使旧读取失效。

边界：不改变 page_size=5、服务端排序、items/knowledge_bases 现有读取、鉴权/传输/存储、页面功能或权限。不添加 optimistic items，不向事件附带名称、Key 或内容，不处理独立 KB-DETAIL-LOAD-002。

验证：用已安装 Vue compiler-sfc/esbuild 编译原 Platform.vue 和 api/index.ts，在 VM 中保留真实 Vue ref/watch，仅替换 HTTP client 及生命周期宿主；deferred 请求检验成功后刷新、失败不刷新、晚到旧成功/失败不能覆盖新数据、路由和卸载隔离。先原代码 RED 后最小修复 GREEN。执行直接 node 测试、frontend npm run test:unit、npm run build；不运行真实 GUI/QA 数据。单位及构建结果不能代替 Root Orca 验收。

自审：无待定项；授权、文件范围、同步语义、错误行为及测试边界一致。
