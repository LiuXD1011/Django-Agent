# Windows包与业务续验主文档addendum

本轮只修改4份主文档及本目录；全文读取现存文档（与13b冻结逐项相同），核读6份本次报告和关键收据，检查新增链接、局部差异、38组/69UI编号与b36c逻辑暂存集合。不重复前次155绑定/1022链接/74native大审计，不重跑suite、GUI、Source、Windows或模型，不修改产品/测试/依赖/其他worker资料，不执行Git写入。

- [Windows owned-runtime报告](../20261013-owned-runtime-windows-build/REPORT.md)：prepare/package实际0，原HANDLE/Job终态0；新安装器401906433B/SHA869a0401…、ASAR12项/25305 runtime文件、新native b3875cb7…；未安装/产品GUI，468/dd5来源早于本次sidebarfix，不能当当前完整源码包。
- [Core报告](../20261013-current-core-full-validation/REPORT.md)：typecheck0、full698=696PASS/2SKIP，315源/依赖该轮相同；后续fresh build0/plain Node无tsx compiled Owner2/2另记，原SKIP保持，不继承到在途Core迁移。
- [sidebar修复](../20261013-kb-sidebar-sync-fix/REPORT.md)及[独立审查](../20261013-kb-sidebar-sync-review/REPORT.md)：19例RED5PASS/14FAIL→19/19，389/389/build0，spec/quality无finding；真实Orca结果按Root独立证据。
- [Root业务报告](../20261013-root-browser-business/REPORT.md)：同页正常login、mouse空库CRUD/筛选/刷新，原stale404保留；145创建/161改名/182删除即时侧栏同步，原12表/25文件相同、5模型/174usage/active0，3owned正常soft-delete。B仍partial；KB-DETAIL-LOAD-002正文错误态修复中。单次HTTP数据不作整条UI延迟或P95。
- [Langfuse autostart缺口](../20261013-legacy-retirement-prepare/AUTOSTART-GAP.md)：UI开发opt-in能力缺TS落点，Core代理迁移中，10旧入口/301候选保留，desktop不autostart，不引Django或隐藏能力。

[Source身份现态](../20261013-root-browser-business/live-services-checkpoint.json)记录Core3622114/start26564594、Vite3622392/start26564747及独立原QA目录；Root此前ss确认8000/5173，本轮文档未重复查询。后端早于在途autostart迭代，前端已载sidebarfix，无需用户再配Key。Root两browser helpers已[精确消费](../20261013-root-browser-business/consumed-helpers.json)，私有QA口令/profile66b/page d330仍供未完Goal，非全局清理完成。

旧13b/b99/fd3冻结和所有历史失败保持，严格53956整体1/原25268历史原因未知不改。38组/69UI稳定，仅M-01/M-02整组PASS；Goal active/incomplete，无产品重跑、无新付费或Git写操作。下一步完成正文错误态/autostart及余页，用后续准确源码绑定验最终安装与普通业务生命周期。

主文档原快照和前置哈希见[before](before.json)，本次有限来源、新链接、局部差异和逻辑index见[validation](validation.json)，自有助手见[cleanup](consumed-helper-cleanup.json)，最终文档与本次绑定见[freeze](freeze.json)。
