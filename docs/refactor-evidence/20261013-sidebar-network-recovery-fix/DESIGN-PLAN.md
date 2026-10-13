# KB-SIDEBAR-003 已批准设计与执行计划

授权来源：Root 分配任务中转述用户 Goal 已批准普通设计、修复与测试；不重复请求确认，不提交、不暂存。仅修改 Platform.vue、Platform.recent-sync.test.mjs、必要的同作用域测试及本证据目录。

## 根因与方案

已完整阅读 AGENTS.md 与两份受影响源码，查看 Root 真实证据 049/050/055/056 和 051/057 截图。读取失败被 catch 写成空列表；模板只有 loading 和 empty 状态，因此 500 错误被表示为成功空记录。详情恢复不会自动触发同路径侧栏刷新，侧栏持续为空。

候选方案：保留实例内最近成功列表并增加错误及手动重试（采用）；失败清空列表但显示错误（丢失已有入口）；自动轮询（扩大范围并增加请求）。采用最小方案：recentError 仅最新请求失败时置为固定安全文案；失败保留 recentItems；最新成功或 evaluation 分支清除错误。错误期间显示原生重试按钮，其 disabled 与处理函数均阻止 pending 重复触发；路由/CRUD 更新仍允许按现有请求代次取最新结果。

空状态须同时满足非 pending、无 error、列表为空。section 标记 aria-busy，状态容器提供 aria-live；错误不回显异常、URL 或凭据。新增 scoped CSS 仅修饰错误文案与按钮禁用/键盘焦点，沿用现有侧栏布局。缓存只在 Platform 实例中，卸载依现有 generation/disposed 保护隔离下一次实例。

## TDD 执行

- [x] 保存两个文件完整 before 副本及 SHA、HEAD、只读 index 观察。
- [x] 修正现有错误清列表的回归预期，增加首次失败/成功真实空/旧错误不覆盖新成功/旧成功不清新错误/pending 重试/卸载后失败测试。保留 CRUD、排序、条数与路由全部断言。
- [x] 新增 Platform.recent-recovery.test.mjs：编译真实 SFC 与 scoped CSS，使用安装的 Vue/router/TDesign Dialog 和真实全局/mobile CSS，仅控制 HTTP 客户端和 auth fixture；通过真实 pointer 与 keyboard 重试，检查两条保留列表、错误非空、命中/未裁切、pending 禁用、成功恢复/清错误、首次失败/成功空。
- [x] 运行定向 node --test 获得 RED，记录实际失败与退出状态。
- [x] 最小修改 Platform 生产代码，再运行同命令确认 GREEN。
- [x] 在 frontend 运行 npm run test:unit 与 npm run build，保存完整日志、实际退出状态与源码 SHA。
- [ ] 从 before 到当前生成完整任务 diff，记录新增测试 SHA；自审后交 Root 独立审查及真实 Orca 复验，KB-SIDEBAR-003 未经 Root 复验不关闭。

自审：范围、文案与状态定义无占位符；不操作 Root 服务/浏览器/auth/数据，不触及 API/Core/KnowledgeDetail/全局 CSS/依赖；不创建定时轮询或接口通知。
