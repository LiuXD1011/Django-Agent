# 用户授权的精简收尾清单

2026-10-13。用户明确要求“选择性跳过一些步骤，快速收尾”。这里的fast-closeout指收尾节奏；两平台本地service_tier仍default，不推断请求实际tier。既有38组/69UI编号、失败和条件SKIP保持，按新范围收尾不等于38组全PASS。

## 已完成并复用

| 可复用结果 | 当前依据与限制 |
| --- | --- |
| 主要迁移已有实际业务，未发现只是壳 | TypeScript Core/SQLite/Worker/private IPC已真实运行；文档、检索问答、Wiki、Agent/工具及评测有实际数据与页面证据。该结论限已验主链，不替所有长尾背书。[当前Core324](../20261013-current-core-324-validation/REPORT.md)、[实际页面与Wiki](../../desktop-refactor/GENERAL-PAGE-BROWSER-ACCEPTANCE.md)、[Agent工具](../../desktop-refactor/MCP-REAL-AGENT-BROWSER.md)、[真实搜索问答](../../desktop-refactor/WEB-SEARCH-REAL-AGENT-BROWSER.md) |
| 主Core不依赖Django；导入/backup/restore已做 | 31表/2445文件导入、幂等与44表/2446文件备份恢复、7源文件workflow已有证明；新Core有独立Node/SQLite/Worker链，旧Windows payload无Django。新包仍须本次真实gate，不用旧包替代。[迁移](../../desktop-refactor/MIGRATION.md)、[旧payload真实门禁](../20261013-owned-runtime-windows-build/REPORT.md) |
| 四role真实模型、五题approved Ragas | 对话/Embedding/ReRank/视觉真实厂商结果已做；唯一五题正式Ragas及报告已做，复用原来源和指标，不重跑收费验收。[四角色](../20261010-windows-model-vendor-regression.json)、[五题与报告](../../desktop-refactor/EVALUATION-CHINESE-QUERY-BROWSER.md) |
| 来源对应测试与修复审查 | 当前Core728=724PASS/4条件SKIP/Owner补2、前端422来源与原Runtime31/test184保持；新test46独立2项/R-01关闭另记。packaging独立spec/quality accept、blocking0/finding0；4项独立是原49子集，不累加。[Runtime复审](../20261013-asar-bootstrap-runtime-review/iteration-2/REPORT.md)、[packaging复审](../20261013-asar-bootstrap-packaging-review/REPORT.md) |
| 非空知识库只复制配置子项 | Root实际copy→refresh→open→仅delete副本完成；原库2文档、复制配置一致/副本0文档和索引，原业务/25文件保持、usage174/active0、0paid。不增加整组PASS，不重跑。[实际报告](../20261013-kb-nonempty-config-copy-orca/REPORT.md) |

## 保留的必做项

- [x] 新v2 Windows包prepare/package actual0，实际ASAR→Electron main→bundledNode→真实Core/native Job gate ready/capabilities/stop0，并一次隔离owned升级0；25381文件匹配，DB/WAL/SHM与opaque Key保持。所有旧失败保持。[最终构建](../20261013-asar-bootstrap-windows-build/REPORT.md)、[升级](../20261013-asar-fix-installed-preparation/REPORT.md)
- [x] 新包正常startup到login并实际合法QA登录，2库16文档10027摘录；使用固定installed exe与独立data-dir。原869a唯一startup FAIL始终保留。[原图及失败](../20261013-owned-runtime-installed-gui-preparation/user-provided-startup-failure-evidence.json)
- [x] 主要页面和文档问答最小闭环已复核：林青128000正确、5引用准确来源/父块、晨星A Wiki目录/表格、4模型和系统信息已打开。文档上传解析及四role/五题复用原已交证据，不重复收费测试；未采样本次正文增量/P95。[答案](../20261013-asar-fix-installed-ui/016-reply-observation.png)、[来源](../20261013-asar-fix-installed-ui/019-source-chunk-view.png)、[完整真实UI结果](../20261013-asar-fix-installed-ui/REPORT.md)
- [x] 两次fresh真实托盘菜单“退出”指针操作，与原Main/Core/各8成员exit0/Job0共同核定；重启恢复合法QA身份、2KB16文档10027摘录与原chat/question/RID/林青128000/5引用。Key opaque hash/profile保持，GUI正常写入导致DB SHA变化，未宣称GUI前后DB字节不变。旧失败保留。
- [x] 使用结束后Source专用QA设备/原开发服务已清；Native设备页撤销5旧copied QA设备、菜单退出登录回到空login输入；独有600私有QA认证文件及Root3助手已guard精确删除，没有口令归档。真实模型配置/Key与业务资料保留。[最后认证清理](../20261013-asar-fix-installed-ui/root-consumed-auth-ui-cleanup.json)。SourceCore/Vite/esbuild已按原pidfd精确停止，QA验收设备正常API清理至活跃0（不是UI注销PASS）；Source数据/Key/媒体保留，600私有QA口令已在最后安装版验收后删除。[Source清理](../20261013-source-test-cleanup/REPORT.md)。取消的Langfuse私有fixture已按Root明确的fixture消费者范围精准删除：0700根、7个绑定文件/6子目录、空data/receipts、project资源0和端口0依据保持；系统FD不可读限制如实记录，不断言全机FD0。原pending回执未改，[本次删除结果](cancelled-langfuse-fixture-cleanup-done.json)另记；该fixture清理只计取消的可选部署准备，不计服务部署通过。
- [x] 最终安装包路径/SHA、installed exe、独立data-dir及正常运行命令已填写。[最终报告入口](../../desktop-refactor/FINAL-REPORT.md)。最终包401913207B/SHA `4edc4d970ccf383b9dd48a6ef38bce1b192e071a1c450a186c0bd63c54abc52e`；退出重启和最后认证文件清理均已取得实际证据，旧869a不作为新修复成功入口。

## 按用户指示跳过／未验证

本轮跳过重复full套件、重复大证据审计/冻结/patch重建，以及非Windows平台交付验证。长尾权限竞态、极端输入、全格式/全页尺寸/IME/DPI、陌生PID压力、崩溃及卸载全组合等未覆盖余项保留“未验证／本轮跳过”，不补PASS；普通退出重启与数据保留仍在上述必做范围。

可选外部服务的真实部署验收本轮跳过，包括Langfuse/Neo4j等未完成条件。LinuxDocker/现3000可达及私有3300/18080/18173 config --quiet0仅准备，未up/Core/UI/保存重启；Windows缺docker.exe。已迁移能力及原相关测试保留，跳过部署不等于删功能或宣布真实服务通过。[readiness](../20261013-local-services-live-readiness/REPORT.md)、[未消费fixture](../20261013-local-services-live-readiness/iteration-2/REPORT.md)

六项必做现均有实际证据，本清单只复核和整理结果，没有重跑旧套件/收费验收或冻结。最后只读页面scope核对actual0，2KB16docs/原chat两completed消息5引用正确；6新成功调用6241tokens、重启无重复、active0、QA未撤销设备0，最初错误全局计数actual1保留。[最终安装汇总](../20261013-asar-fix-installed-preparation/FINAL-RECEIPT.json)。用户授权精简范围完成；38组/69UI保持真实状态。安装器0.6.2/Core系统0.7.0版本一致性整理未做，列低优先限制。
