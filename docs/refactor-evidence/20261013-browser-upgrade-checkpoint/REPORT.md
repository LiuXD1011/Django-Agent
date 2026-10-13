# 浏览器错误恢复、autostart复审与owned升级文档检查点

2026-10-13。本阶段仅维护 STATUS、TEST-MATRIX、TEST-REPORT、FINAL-REPORT 四主文档及本目录。完整阅读 AGENTS、四现存文档与原027b检查点报告后，从本阶段实际before字节生成完整四文件差异；不使用未暂存diff作为范围依据。原027b冻结SHA `027bce7878630f8c00fc78ae76c1968d275f011f4a8cdde5dc38e5ace143ac76` 与全部旧收据保留。

本次小范围绑定为7份已完成报告、27份关键收据/来源及当前4主文档；不重复历史155绑定/1022链接/74native大审计，不重跑产品测试、构建、GUI、模型、服务或数据库操作，不接触Windows GUI/新副本准备，不执行Git写入。

- [Root Orca结果](../20261013-kb-detail-load-state-orca/REPORT.md)：报告SHA `427be4bea8459860cf906cb24786b37955c5a7688889293b00119a80fa93888d`，002真实404持久错误/按钮可见命中/正常返回2库16条目10027摘录，以及真实Vite500持久错误后Retry恢复14文档200已验；003另一次真实500保留2最近记录/安全错误/按钮，服务恢复后侧栏pointer重试list200/93.6ms清error，再main Retry恢复2文档200。正常文档/Wiki/解析记录入口回归；CSS裁剪失败与后台动画工具问题保留。限实际Orca1289×921，headless1024不冒称实际Orca。12保护业务/25文件SHA同原基线，models5/usage174/active0、0新增付费；不扩展为全部设置表/DB字节不变。
- [详情布局独立审查](../20261013-kb-detail-layout-review/REPORT.md)：KnowledgeDetail017504cd…定向25/25含layout，spec/quality通过、finding0，另2项docs pending布局通过。414/414属于详情轮历史，随后422不累加；首轮review未覆盖CSS的边界和原RED保留。
- [最新侧栏修复](../20261013-sidebar-network-recovery-fix/REPORT.md)与[独立审查](../20261013-sidebar-network-recovery-fix/INDEPENDENT-REVIEW.md)：Platform80828289…保留原001逻辑，定向27/27、前端422/422/build0，无阻塞finding；Root上述实际003后续复验闭合对应开发浏览器缺陷。原api22a48/Platform468及145/161/182不覆盖。
- [autostart iteration-2](../20261013-local-services-autostart/iteration-2/REPORT.md)与[独立复审](../20261013-local-services-autostart-review/iteration-2/REPORT.md)：R1/R2生产结论accept、Unicode1420输入actual0，service8c4b…；完整差异d8f48869…15路径/6修改9新增，当前Core324相对旧315。RED0/6→6/6、focused28/28含6重叠、原review replay3/3、typecheck/build0、fresh plain Node local-services-compiled2/2。E1首次漏6modified的包保留，baseline重建已闭合；原首轮RED/0/3保持。旧315默认full698=696PASS/2个core-owner compiled条件SKIP与另行Owner compiled2/2仅属旧来源；新iteration-2的compiled2/2是local-services，不是重跑旧Owner2。当前324完整验证正在独立进行，本检查点不等待、不写新full通过；真实Docker/Orca设置保存启动/native Windows仍待，10旧入口/301候选保留。
- [869a实际owned升级](../20261013-owned-runtime-install-preparation/REPORT.md)：报告SHA `7a374f6382bab94a937c5e9c5e98830e81a233690347f216060998ad98b759ad`，固定旧468包同owned中文空格目录升级恰一次；inner NSIS0/97.606s、harness child0/wholeJob0，原outer工具35809因GBK读取UTF8汇总错误整体1保持。installed0ee5a94b…核25380安装文件/25305runtime/12ASAR/native b3875cb7…、12表/94文件/凭据SHA全等；独立readonly83147另actual0/36.152s、bfbe7393…再次确认原tool1未改。旁实例实际0，不虚构保留PASS；未产品GUI/模型，旧468不含后续sidebar/detail/autostart，最终新Source包另需构建验收。

[最终Source身份](../20261013-kb-detail-load-state-orca/final-current-core-live-services.json)：当前Core4156949/start26982794/session68767、Vite3622392/start26564747/session52034仍live。两次被停旧Core分别3622114/26564594、4096365/26929578，均精确原pidfd正常终态，旧exec21756/66476各0；本阶段未重复查询或操作它们。当前Core使用LANGFUSE_AUTOSTART=false进程环境、0设置保存，不计真实Docker启动通过。Root2个helper与finalizer已归档精确删，私有QA口令/profile66b/page d330供未完Goal保留。

Root原validation的76份成功工具记录、57报告链接/3来源是原归档计数，不是76项业务PASS。本阶段只校本次新增修改的链接、完整before差异/重建、关键SHA与稳定编号。38组/69UI顺序不变，整组PASS仍仅M-01/M-02；002/003不推成整组通过，其他业务、普通GUI/新副本、最终包/生命周期/卸载、IME/缩放/单实例/崩溃及真实延迟仍待。strict53956整体1、25268历史退出原因未知及所有原失败保持，Goal active/incomplete。

本阶段来源与完整副本见[before](before.json)，完整scope差异见[four-owned-documents.diff](four-owned-documents.diff)，本次实际文档校验见[validation](validation.json)，自有文档helper的归档和精确删除见[cleanup](consumed-helper-cleanup.json)，小范围SHA绑定见[freeze](freeze.json)。[Git只读前后观察](git-readonly-observation.json)独立记录HEAD和逻辑stage，不冻结它们，不推断外部变动作者、不回滚或覆盖无关文件。

本次首个文档finalize实际exit1：校验器在创建本次diff之前检查报告对它的链接，属于自身文件生成顺序错误，未改产品或原证据。原失败与该版本helper见[actual1记录](validation-initial.actual1.json)及[原源码](final-validator-initial.source.py.txt)；改为先生成完整diff再检查，最终结果另记，不覆盖原1。
