# 知识库最近侧栏同步实施计划

目标：知识库成功创建、编辑、复制、置顶/取消、删除立即触发侧栏读取，并拒绝旧异步结果覆盖。

执行方式：在本 worker 内执行；用户已授权，不新增 agent、不操作 Git 或真实浏览器。TypeScript/Vue，使用现有已安装依赖。

- [x] 建立 frontend/src/views/Platform.recent-sync.test.mjs：编译真实 API 与 Platform，request deferred 替身、真实响应结构。运行 node --test frontend/src/views/Platform.recent-sync.test.mjs，保存 stdout/stderr/实际 exit；原生产代码必须出现缺少刷新及旧响应覆盖断言失败。
- [x] api/index.ts 添加 subscribeKnowledgeBaseChanges(listener: () => void): () => void，内部成功通知包装器；只包装 createKb/updateKb/deleteKb/pinKb/copyKb，await client promise 后同步通知并原样返回结果。
- [x] Platform.vue 导入订阅函数及 onUnmounted，挂载注册后读取；卸载取消订阅并使读取失效。loadRecentItems 递增序号，在 await 后、catch、finally 检查序号及卸载状态；评测仍清空，聊天仍 listSessions，不被 KB 通知触发。
- [x] 运行相同 node 回归 GREEN，frontend npm run test:unit、npm run build，完整保存 exit/输出及计数。检查完整 diff、before/after SHA、文件范围及遗留 warning。
- [x] 保存 REPORT.md 和完整 diff。临时执行脚本归档源及 SHA 后删除；向 Root 报告验证状态与真实 Orca 待验收边界。
