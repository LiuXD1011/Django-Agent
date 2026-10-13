# 知识库类型筛选

## 真实问题与设计

Root 在 Orca 的真实知识库列表选择「本空间 → 文档知识库」后，仍看见普通库和启用 Wiki 的库。真实请求 `type=document&creator=mine` 返回 200；两库数据库 `type` 都是 `document`，但一库的 `wiki_enabled` 为 true。[实际请求与页面](../refactor-evidence/20261012-root-kb-mouse-round2/020-document-type-public-state.json)、[实际返回分类](../refactor-evidence/20261012-root-kb-mouse-round2/021-document-filter-actual-items.json)。

`KnowledgeBaseService.values` 用 `indexing_strategy` 保存能力，统一存储 `type=document`。DTO 和页面已按启用 Wiki 分类，列表查询仍按旧存储字段筛选。筛选应采用现有 `indexing` 投影：文档分类返回 Wiki 未启用的库，Wiki 分类返回 Wiki 已启用的库。历史字符串、缺省值和 `type=wiki` 使用同一现有投影，不重写历史数据库。

三种方案中，复用现有投影在分页前过滤可统一只读/业务查询；仅在前端过滤会破坏分页计数；改写历史 type 会影响数据兼容且无必要。本次选择第一种。关键词、创建者、权限、删除/临时库排除和排序继续使用原有查询。旧 `type=faq` 请求继续返回空结果。

本次只修改 `packages/core/src/knowledge/read-queries.ts`，测试归属 `packages/core/test/knowledge-read-queries.test.ts`。不改变模型、知识库配置或文档内容。6e37 来源已经绑定安装产物，作为本修复之前的历史版本保留；其安装检查不能算本修复的安装验证。

## 实施与验收计划

- [x] 在真实 SQLite/只读连接上增加互斥分类测试，包含关键词、创建者、分页计数、其他空间隔离和读取不写数据库。
- [x] 增加历史 Wiki 字符串、缺省策略和旧 type 的分类测试，先运行两项并确认具体断言失败。
- [x] 导入并复用 `indexing`，在原查询分页前为 document/wiki 选择相应能力。
- [x] 运行本文件全部测试及相关知识库/只读路由测试，再运行核心类型检查与编译。
- [x] 确认验收核心无在途任务，精确停止并重新启动自身开发核心，Orca 真正点击两个分类，核对请求、返回库、统计和保护数据。
- [x] 保存实际命令、结果与真实页面证据。
- [ ] 包含本筛选修复的新版安装包真实复测。

Goal 第二节已经允许记录计划后自主修复和隔离验收，本修复继续当前工作区，不提交或改写历史产物。

## 实际结果

真实 SQLite 两项 [RED](../refactor-evidence/20261012-root-kb-type-filter-checks/red.log) 分别因文档分类返回 3 而非 2、历史 Wiki 分类漏两库失败，退出 1；不存在模块或语法错误。最小修改后，[本文件测试](../refactor-evidence/20261012-root-kb-type-filter-checks/green.log) 8/8、[相关测试](../refactor-evidence/20261012-root-kb-type-filter-checks/related.log) 44/44 通过，均零失败/取消/跳过。核心 [typecheck](../refactor-evidence/20261012-root-kb-type-filter-checks/typecheck.json)、[本测试 strict/noEmit](../refactor-evidence/20261012-root-kb-type-filter-checks/test-typecheck.json)、[编译](../refactor-evidence/20261012-root-kb-type-filter-checks/build.json) 均实际退出 0；没有重复运行未变化的完整前端套件。

原验收核心 PID2245508/startTicks17581590 已通过 native pidfd 仅发送 SIGTERM，原服务会话7456实际退出0。新 PID3833788/startTicks22088558、会话72606使用同一数据目录与解析/评测配置，新核心已监听8000。[原退出与新就绪记录](../refactor-evidence/20261012-root-kb-type-filter-checks/source-owned-exec-observations.json)、[重启后的只读保护](../refactor-evidence/20261012-root-kb-type-filter-checks/source-after.json)。12张保护业务表与媒体/凭据材料哈希完全相同，任务在途为0；认证与审计表正常变化不纳入字节不变结论。

Orca page749b7cae 的033/035为真实鼠标选择文档与本空间，039/041选择 Wiki；没有调用 API 代替选择，也没有在 eval 内触发按钮。eval仅收集已返回的公开 DTO、页面统计与 Resource Timing。结果如下：

| 页面选择 | 实际结果 | 实际请求 | 证据 |
| --- | --- | --- | --- |
| 本空间 + 文档知识库 | 仅普通库，1库/14条目/10020摘录 | `type=document&creator=mine`，200，119.7ms | [公开状态](../refactor-evidence/20261012-root-kb-mouse-round2/036-fixed-document-own-public.json)、[Root实际看图](../refactor-evidence/20261012-root-kb-mouse-round2/037-fixed-document-own-frame.png) |
| 本空间 + RAG + Wiki | 仅Wiki库，1库/2条目/7摘录 | `type=wiki&creator=mine`，200，327.6ms | [公开状态](../refactor-evidence/20261012-root-kb-mouse-round2/042-fixed-wiki-own-public.json)、[Root实际看图](../refactor-evidence/20261012-root-kb-mouse-round2/043-fixed-wiki-own-frame.png) |
| 全部范围 + 全部知识库 | 原两库，2库/16条目/10027摘录/0处理中 | 不带分类或创建者，200，158.5ms | [恢复后的实际状态](../refactor-evidence/20261012-root-kb-mouse-round2/050-final-all-list-public.json) |

以上是每次成功请求各n=1的浏览器 Resource Timing，不代表完整界面响应/P95或与旧样本的性能改善。恢复全部类型时，出现一次401后同请求200的正常重试；没有把401隐藏为全程无错误，也没有额外独立确认该次refresh原因。

Root重启助手的两个前置问题保留：[Python未导出pidfd](../refactor-evidence/20261012-root-kb-type-filter-checks/source-stop-default-python-failure.json)、[新命令argv首项差异](../refactor-evidence/20261012-root-kb-type-filter-checks/source-after-argv-preflight-failure.json)。前者发生在任何signal之前；实际Python3.12.2构建没有所需导出，核对本地Linux系统header并沿用已有native syscall实现后正常停止，没有升级强制终止。另028浏览器快照不支持所传flags，后续普通snapshot成功；原工具失败不覆写，不能计产品缺陷或业务步骤通过。

这仅完成筛选专项的源码与真实浏览器复验，B-01其余编辑、相似名称及安装链路仍待验。没有新增知识库、修改真实资料或执行模型请求；此前6e侧栏包的Windows升级结果不能计作本筛选修复的安装验收。Goal active。
