# 旧实现退役可执行准备收据

## 当前addendum：10项删除未执行，Langfuse autostart缺口已上报

删除前完整重读10文件/runbook，实际15项只读门禁全部通过：[原始前置结果](entrypoints-execution/before-verification.json)。当前source_inputs468与正式Windows `dd5b9d2f…`逐项一致，10项无候选Git变化且不在该集合；301归档、174映射/基线文档、保留能力/许可SHA一致。Root的正式package-only实际0和原HANDLE/Job active0收据只读核对，没有修改构建manifest。

完整行为审查发现旧manage runserver在外层进程实际调用Langfuse opt-in Docker autostart；当前TS dev入口只保存对应设置，UI仍承诺下次开发启动生效。这是原静态计划漏项，Root已赞同并要求**整个10项group暂缓**。全部301源码仍存在，entrypoints_retired=false、full_retirement_executed=false；没有unlink、业务suite、服务、Docker或模型调用，其他291/真实数据不动。

[AUTOSTART-GAP.md](AUTOSTART-GAP.md)已给出完整旧语义、current UI/README证据、Neo4j不具同类autostart、最小TS owner落点（避开30秒ready与最长120秒服务预算冲突）及真实锁/CLI/Docker/Orca验收方案。Root安排实现/验证后再协调退役，不请求用户重复授权。原prepare freeze/历史收据及301非运行源码归档不改；原计划/REPORT的旧字节已单独保存，[原文绑定](entrypoints-execution/prepare-doc-preservation.json)。以下记录保留原准备阶段事实，不改写成已执行删除。

addendum收尾13项核对actual0，含默认只读runbook、README链接及diff：[完整结果](entrypoints-execution/autostart-gap-final-verification.json)。旧freeze绑定中的两份当前文档经上述原字节副本可精确复核，其他绑定仍在原位置逐字节一致。收尾时source_inputs观察到Root另行协调的界面新迭代：新增Platform.recent-sync测试、改api/index.ts及Platform.vue；[当前真实差异](entrypoints-execution/current-source-inputs-observation.json)标记与原468不同，不将新迭代来源写回原dd5manifest。没有执行被暂缓删除的after测试/buildsuite；另一个代理的698项Core结果由Root集成，未重跑。

## 原准备阶段收据

2026-10-13。`retirement_executed=false`、`production_modified=false`、`goal_complete=false`。本轮只写执行计划、本目录及自有临时helper。未删除/移动生产源码、测试、依赖或用户文件；未启动服务/GUI/模型，未执行业务suite、build或Git写操作。

Root可审阅[执行计划](../../desktop-refactor/LEGACY-RETIREMENT-EXECUTION-PLAN.md)、[301项总表](RETIREMENT-FILES.md)、[逐路径机器清单](candidates.json)、[完整拟删除差异](prospective-deletion.diff.txt)和[默认只读runbook](execution-runbook.source.py.txt)。当前源码冻结未释放；脚本默认只核查，删除分支未执行。

原265候选SHA全部相同，当前候选Git状态为空。补齐36个根旧测试/runner/真实库及旧环境诊断，形成301项清单，全部精确字节副本已保存为非运行 `.txt`。不删除 `tests/test_readme_links.py`、`tests/test_frontend_contracts.py`、根eval配置/数据集、当前TS/worker业务或兼容测试。源快照不是旧Django可运行归档，也不是用户数据备份。

174基线历史链接/100目标都有原文档:行号、源SHA和可点击精确快照，[source-map](HISTORICAL-SOURCE-MAP.md)。DATA/PARSER基线字节保留；未来旧位置消失时须使用此addendum，不谎称原直接链接依然可用。其他历史文档的旧路径按301项总表查找。freeze/历史失败/私有452快照没有修改。

当前默认root tests不启动旧runner；auth PBKDF2已静态gold+独立oracle，auth E2E当前真实TS入口且历史最终原3项3PASS/exit0来源SHA匹配。原初版3FAIL收据保持历史事实。AES-GCM仍需要独立 `cryptography` Python测试环境。当前 importer/schema/passwords/credentials/graph legacy/租户渠道业务、公有registry/MT19937及所有许可保留。DOC/PPT旧新字节相同；旧xls不同于新原创xls且许可来源未解决，因此只精确保存原资料、未伪称等价或添加许可归属。手工chunking/retrieval含placeholder模板原样保留，状态不改为gold。

[verification.json](verification.json)的35项核查全部通过，工具chunk `0a7386`实际exit0；其中 README本地链接、runbook默认只读及git diff检查均有完整stdout/stderr/退出码。它是文档、SHA与已有收据复核，不是重新运行业务测试或Windows验收。

初次finalizer在生成verification前误用了不存在的registry字段 `legacyManifestSha256`，actual1/chunk1ac02a；已按真实source的 `artifactManifestSha256`/`manifestSha256` 和实际id校正，生产未改，[原工具错误](finalize-initial-tool-error.json)。随后初次链接检查在verification.json尚未生成时actual1/chunk0a62e3，原34/35结果留在[顺序失败](verification-initial-order-failure.json)；文件生成后同一只读核查35/35实际exit0。没有隐藏失败、降低断言或重放suite。

首次helper仅提取原候选+绝对import旧测试298项；读取动态源码扫描和旧数据诊断后范围修正为301；现终态清单301项。原265候选仍0变化。旧AST312/1048保存，当前tracked扫描314/1054，原1048无缺项；新覆盖manage3条/旧服务第三方3条，[口径差异](comparable-import-delta.json)明确，不将扫描口径当源码改动。当前worker旧业务绝对导入0。

HEAD仍dd5a356，逻辑index仍b36c6d28823e225a3c3daa8e75a74c2956982a21b64b4e8a0093e62cd795f278。Root及其他人的当前文档/证据变化在[前置](status-before.stdout.log)/[后置](status-after.stdout.log)保留，未覆盖或推断作者。两个自有临时helper按最终SHA归档后精确删除，[清理](helper-cleanup.json)；冗余602份空单路径status日志已精确合并为候选汇总日志，[合并回执](consolidated-empty-log-cleanup.json)。

下一步由Root在正式prepare结束并解冻后选择第一批精确10个旧入口/requirements/脚本；全部301项则必须完成相应业务门禁。首次撤入口不新增或删除业务能力。任何源SHA或候选Git状态改变，runbook退出并要求重新绑定当前源码；不清用户数据库、WAL/SHM、media、.settings/.secrets/.env、缓存、图库、私有快照、安装或备份。整个Goal仍active。

补核默认通用Playwright/mobile配置：均只启动Vite/preview，不启动Django。通用配置包含真实auth spec但自身不启动Core，默认Vite proxy8000；多数其他spec明确page.route替身。故应使用已验证auth配置，不能把通用npm run test:e2e描述成自含的整套真实业务E2E。没有启动或复用8000服务；这属于测试入口说明/隔离范围待Root整理，不是本轮已证明的生产业务遗漏。
