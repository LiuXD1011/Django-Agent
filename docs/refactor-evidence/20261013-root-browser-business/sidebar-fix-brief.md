# 知识库侧栏同步回归修复

用户已批准Goal普通修复与功能保留；本任务修复真实Orca操作发现的既有行为缺陷，不改变最近列表排序/权限/页面能力。

现象：`Platform.vue`只在挂载和route.path变化时调用loadRecentItems；知识库列表页create/copy/pin/delete以及详情页保存不触发侧栏更新。Root正常登录QA，通过真实mouse move/down/up建库、编辑、复制和删除；删除后仍有同名入口，点击进入已删除ID，正文空白且“知识库加载失败，请稍后重试”。

证据：119-owned-none.json/120-final-timings.json中列表为空但sidebar还有删除对象；121-stale-recent-box.json +122/123/124真实鼠标+125-stale-recent-result.json/126-stale-recent-screen.png证明坏入口。059-edited-detail.json中标题已改而sidebar旧名，069-list-edit-persistence.json路由改变才更新。两个验收UUID分别03591ced-c5b0-4c1d-841a-35701aa724be/990690de-aec0-433b-9959-399345982377，仅在ownedQA资料中。

范围：复用现有api mutation和Platform生命周期，让成功创建、编辑、复制、置顶/取消及删除后，相关侧栏及时以真实结果更新；失败不假成功，不添加兼容层/额外轮询，不扩大到云同步或改变排序语义。不要删除正常功能/断言；不得改auth传输/存储、Core、Desktop、锁文件、依赖。处理晚到的旧load结果不能覆盖新结果或重新引入已删除项；卸载后解绑，保持聊天/评测分支正常，不额外泄露权限或Key。

文件归属：frontend/src/views/Platform.vue、frontend/src/api/index.ts，以及为此必要的新独立service/controller .mjs/.d.ts及关联.test.mjs；若能在更小现有同类模块完成，先向Root说明具体路径。不要改KnowledgeBases.vue/KnowledgeDetail.vue，api级通知应足够覆盖这两者。完整读受影响文件、实际API类型及现有测试；本机源码无并发写者，Windows上一包已完成但这次前端修复将产生新源码迭代，不能改旧包manifest/receipt。

先记录最小设计与现有机制取舍；用原生产路径和deferred异步结果做有意义RED回归，然后单一根因修复、GREEN，验证node直接测试及frontend npm run test:unit；执行必要npm run build验证不新装依赖。禁止静态字符串断言伪装行为回归，允许单位级受控请求替身并明确标注，真实Orca重跑由Root独占完成，不操作GUI/浏览器/真实数据/服务/外部模型。

产物：docs/refactor-evidence/20261013-kb-sidebar-sync-fix/ 下设计、完整diff、before/after源SHA、原RED/GREEN/stdout/stderr实际exit、REPORT.md；不得修改主验收四docs。禁止任何Git写入、commit/stage/push。自身临时脚本精确归档SHA后删除，保留failed evidence，不把单位GREEN或build当GUI验收。报告Root状态、测试计数和concerns。
