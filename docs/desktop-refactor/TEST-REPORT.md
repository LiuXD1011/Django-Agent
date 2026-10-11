# 测试报告（持续更新）

本报告保留各次构建和失败的历史事实，后面的记录补充当时尚未执行的步骤。最新结果见末尾Worker集成、SQL诊断与Orca实际回归；五题已实际完成但原质量不通过，正式包页面及其余矩阵未完成项不计通过。

## 已执行的旧实现基线

| 命令/操作 | 条件 | 结果 | 新应用验收计数 |
| --- | --- | --- | --- |
| `APP_DATA_DIR=/home/liuxuedeng/.local/share/marlin-refactor/20261010-baseline/legacy-data python manage.py check` | 旧Django，复制的数据/配置/密钥 | exit 0，0 issues | 0 |
| `cd frontend && npm run test:unit` | Node v22.23.2，当前Vue源码 | 140通过，0失败，约957ms测试执行 | 0 |
| Windows PowerShell查询原生node/python | Windows 11，PowerShell5.1 | node.exe/Python313可调用 | 0 |
| Orca worktree/tab读取 | 当前主工作区 | 客户端在线，已有空浏览器页 | 0 |
| 原DB只读元数据核对 | 项目根 `db.sqlite3` 的 backup副本 | 4用户/2空间/2库/7文档/1400块/46会话，0有效模型 | 0 |

上述耗时是检查命令执行时长，不是产品启动/响应性能。

## 新核心基础验证（2026-10-10）

| 实际验证 | 结果 | 范围 |
| --- | --- | --- |
| database + credentials | 6通过 | 真实SQLite/FK/事务/FTS5/sqlite-vec/60bit；临时凭据，不是厂商测试 |
| migration | 4通过 | 隔离31表fixture、幂等、拒绝坏key/媒体/hash/未来版本、备份恢复、清单外文件不复制 |
| auth | 11通过 | 真实SQLite/两个进程refresh竞争、Django密码真实双向兼容、设备/个人空间/角色 |
| models | 16通过 | 受控本地HTTP/SSE协议、thinking、embedding/rerank/vision、坏响应/取消；厂商实际调用未执行 |
| parser worker | 22 Python + 8 TS通过 | `/tmp/marlin-parser-isolation-20261010` 未安装Django；真实文档与实际子进程 |
| 实际数据副本 import CLI | exit0，约4743ms | 源版本0025，31表计数及摘要、1430文件约80.7MB、缺新列默认；[无秘密摘要](evidence/20261010-legacy-import.json) |

首次实际导入源为私有baseline/legacy-data，目标为 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-import-check`，未覆盖原始用户数据。31表原始digest与目标digest因JSON规范化、受控媒体相对路径及新增字段可不同；不能仅以行数推定字段全部保真，继续验证逻辑归属和JSON大整数。目标索引明确needs_rebuild，不计作检索业务通过。业务cache尚待纳入补充一致副本。

## 最新验证与真实问题

| 验证 | 实际结果 | 证据/条件 |
| --- | --- | --- |
| 前端 `npm run test:unit` | 145/145，0失败，971.810ms | [TAP](evidence/20261010-frontend-unit.tap)，含服务身份和旧CSRF Cookie回归 |
| TS parser桥 | 12/12，0失败，2762.430ms | [TAP](evidence/20261010-parser-bridge.tap)，实际Python进程与退出/坏帧 |
| TS HTTP认证 | 6/6，0失败 | [TAP](evidence/20261010-http-auth.tap)，真实HTTP+SQLite+签名CSRF+设备轮换 |
| 知识域+检索 | 52/52，0失败 | knowledge22+retrieval30，真实FTS/vec；UI尚待验收 |
| 实际完整副本导入 | 31表/2445文件，30647.723ms | [摘要](evidence/20261010-legacy-import-full.json)，包括完整业务缓存 |
| 重复导入 | repeated=true，4653.567ms | [摘要](evidence/20261010-legacy-import-repeat.json) |
| 备份与独立恢复 | 44表/2446文件备份8517.988ms；恢复后FK零错误 | [备份](evidence/20261010-legacy-backup.json)、[恢复核对](evidence/20261010-legacy-restore-check.json) |

Orca数据目录为工作区外`20261010-browser-qa`，Vue入口localhost:5173，API实际TypeScript核心localhost:8000。初始化暴露的服务身份提示及旧CSRF Cookie兼容问题已修复；新Orca页实际点击、填写专门账号与自选密码、提交后进入知识库，初始化请求139.9ms。[实际操作记录](evidence/20261010-orca-initialization.json)。知识库创建通过实际焦点键盘提交，319.8ms；列表87.6/96.2/252.1ms是各次请求的独立观测，不能汇总为P95。其他按钮仍有工具报告点击却没有DOM/API效果的问题，不计通过。

用户已在稳定Windows桌面配置四模型，并通过真实点击发送取得GLM回答391；其他三模型的首次实际调用已在后文核验；厂商Ragas评测尚未执行；最新Windows基线安装及smoke已通过，最终包仍待收尾。受控HTTP/Ragas数学计算证据与厂商验收分开；下列正式IPC已通过，但不等于安装版通过。上表测试命令耗时不能冒充页面性能。

## 正式传输与迁移文档的后续证据

| 验证 | 实际结果 | 证据/范围 |
| --- | --- | --- |
| HTTP业务组合 | 18/18，10010.019ms | [TAP](evidence/20261010-http-integrated-business.tap)，真实SQLite/HTTP/SSE/取消/引用/Wiki/Agent/集成 |
| 私有IPC设备模式及流 | 5/5，6032.259ms | [TAP](../refactor-evidence/20261010-ipc-device-mode.tap)，私有凭据、真实模型协议流、恢复及无越权 |
| 独立桌面TS子进程 | 1/1 | [TAP](evidence/20261010-desktop-core-process.tap)，实际fork/退出/重启，不含Electron窗口 |
| 桌面运行时及来源/资源边界 | 9/9，6713.735ms | [TAP](../refactor-evidence/20261010-desktop-boundaries-runtime.tap)，实际Node子进程流逐帧ACK/持久化，来源与静态资源单元边界 |
| 前端原生传输 | 149/149，3648.765ms | [TAP](../refactor-evidence/20261010-frontend-desktop-transport.tap)，单元协议fixture，不算页面或厂商通过 |
| Vite构建 | exit0，47.55s | [构建日志](../refactor-evidence/20261010-frontend-native-build.log)，主包大小警告仍待优化 |
| 应用检索设置 | 1/1，2997.404ms | [TAP](../refactor-evidence/20261010-application-retrieval-thresholds.tap)，实际SQLite/FTS与保存阈值语义 |
| 完整迁移文档重解析 | 7文件SHA一致；355块；5954.621ms | [实际阶段记录](evidence/20261010-migrated-document-workflow-after-index-fix.json)，本地发布约3004ms，全部阶段结束；外部模型未配置而跳过 |

重解析首次65秒仍在本地发布，诊断发现单条索引操作逐条水合全部988条语料，10条索引读取9880记录与约679MB元数据，15999ms。限制SQL到目标块后，在相同完整副本完成上述重解析；保留[首次观测](evidence/20261010-migrated-document-workflow.json)。另一次WSL写日志提交约281秒阻塞有D状态证据，是环境观测，不作为产品请求延迟。

最新parser启动测量确认默认Anaconda直接启动108–150ms，supervisor路径264–696ms；独立venv直接9–21ms，supervisor65–129ms。保留真实80ms启动期限，继承管道清理和坏尾帧以实际进度握手再验证，生产超时未变。最新限定组合130/130通过，使用独立venv及tmpfs fixture；不计磁盘耐久或产品延迟。[命令及TAP](../evidence/20261010-document-workflow.tap)。

Windows隔离目录`C:\Users\lxd\AppData\Local\Temp\Marlin Desktop TS QA 20261010`已实际运行官方校验的Node22.23.2、SQLite3.53.4和sqlite-vec0.1.9，[实际加载记录](../refactor-evidence/20261010-windows-native-sqlite-vec.json)。首次Electron44.7.0窗口加载登录页后核心退出；[对照诊断](../refactor-evidence/20261010-windows-electron-v8-failure.json)确认Electron V8 15.2发给Node22的advanced序列化不能解码。已改用JSON通道，私有字节DTO与实际进程/流回归通过。修复后[Windows smoke](../refactor-evidence/20261010-windows-electron-json-smoke.json)实际退出0、mounted=true、nativeTransport=ipc、核心不监听HTTP；单次冷启动2512.984ms，不计可靠P95。可见窗口通过真实鼠标/辅助访问输入初始化验收账户后进入知识库，并实际点击用户资料及模型管理，核心持续运行；安装、完整生命周期和文档链路仍未通过。首次[失败smoke](../refactor-evidence/20261010-windows-electron-initial-smoke-failed.json)保留。

Windows独立Python3.13.16的[构建与锁定记录](../evidence/20261010-windows-python-build.json)包含110项精确依赖与许可证。直接worker完成11格式、28边界及带空格路径搬迁；Django导入失败。裸环境首次SVG失败定位为Cairo DLL搜索目录，可信Python env helper限定PATH并强制UTF-8。正式Windows Node→编译TS→Python链路[25/25通过](../evidence/20261010-windows-ts-python-bridge.json)，[进程边界7/7通过](../evidence/20261010-windows-ts-python-bridge-boundaries.json)。Windows asyncio初始化与访问隔离冲突修复后，两题Ragas受控HTTP计算通过，生产300秒超时未放宽；[诊断记录](../evidence/20261010-windows-ts-python-bridge-ragas-diagnostic.json)不算厂商五题评测。

评测核心16/16（218.926s）、Python边界6/6（1.091s）、前端评测15/15、前端完整单元162/162（3.610s）、最新core typecheck/build及Vue build（45.58s）通过。以上均是测试/构建命令时长；五题受控HTTP实际计算45次模型请求，未使用厂商Key，不能计入厂商质量结论。

Graph/Evaluation/附件/Actor路由接入后限定应用组合22/22通过，48973.097ms，包括实际审核发布、缺配置零调用、multipart私有源文件往返及会话删除清理。[TAP](../refactor-evidence/20261010-application-integrated-routes.tap)。该时长是整组测试命令运行时间，不是页面延迟。

## 新发现

- SVG解析产物字节/MIME已规范为真实PNG，Windows随包Cairo及正式TS bridge已验证。
- 旧向量关联60位整数必须在TS中保留精度；否则引用和向量可能错联。
- 旧数据库未包含工作区最新所有迁移，且历史有不可逆数据清空；新导入必须独立检查版本并保留记录。

## 最新桌面与浏览器验收

- Windows桌面已正常退出并重开，原验收账户、GLM历史回复及用户重新配置的四模型仍保留。对话真实输入17×23，实际回复391：[截图](../refactor-evidence/20261010-windows-glm-live-answer.png)。核心只读用量记录为对话6279ms、855 tokens；后续维护4977ms、873 tokens。[无秘密元数据](../refactor-evidence/20261010-windows-model-initial-call.json)。不将自动化工具等待计入调用耗时，不声称首段/P95已测量。
- 实际新建独立知识库，准备并通过原生文件选择框选择五份自编资料，确认队列后真实点击开始解析：[文件哈希](../refactor-evidence/20261010-model-fixtures.json)。五份文档parse_status完成，Embedding五次359–699ms；OCR2473ms、图片描述3901ms，验证码ORCA-QA-7421、设备32、日期2026-10-20均与标准一致。问答中query embedding228ms、ReRank200ms，现行负责人林青、预算128000、代号MX-A-2026正确，并引用三来源。[实际四模型记录](../refactor-evidence/20261010-windows-live-upload-models.json)。四角色实际调用通过，不代表整条业务链路或全部标准问答通过。
- 原上传label不能通过键盘或辅助访问正常操作，四入口改为原生button。实际Chromium组件Enter/Space触发filechooser、多选/accept/capture及重复文件行为由RED转GREEN；前端163/163、Vite build通过。这是组件和构建证据，不能代替桌面实际上传。
- 真实SQLite发现未索引NULL seq_id分块被FTS误召回，修复后新回归及相关检索39/39通过。Graph wrapper接入后应用缺Neo4j提示、显式空范围、评测路由及FTS限定5/5通过；缺外部服务仍明确提示配置，未声称Neo4j已连接。
- Orca ThreadingHTTPServer控制页实际点击送达确认，旧单线程服务器预连接诊断已纠正。新产品页实际退出、登录并进入知识库，登录请求737ms。[操作记录](../evidence/20261010-orca-browser-parser-worker.json)。其余页面逐项检查仍在继续。
- 首个真实NSIS已经构建成功，401698049 bytes、SHA256 adab54f7d5bdb3625a91eba75887cd633c79f333985d2635e8f0b1e6da27ff23，9项ASAR白名单与隔离依赖审计通过；后续包含aux/Agent修复的实际Windows164单元、Vite、tsc与SQLite/FTS/vec/IPC gate通过。此后第二基线包已安装并通过正式smoke，升级或卸载尚未执行；首包保留为非最终构建证明。
- 厂商实际调用暴露四份文档摘要failed：400completion大部分消耗在395–397 reasoning，原调用未恢复旧GLM辅助任务low策略；一条Wiki生成60014ms超时。列表仍统一显示“等待摘要/索引”，需显示真实失败状态。Agent list_knowledge_docs工具误用了knowledges不存在的is_enabled字段，问答正确但该工具失败。辅助thinking与有效输出成功判定关联62/62、前端完整164/164、文档工具真实SQLite20/20及类型/构建通过。编译修复已部署Windows可见QA，辅助摘要/Wiki及文档工具均已有真实回归；旧失败证据保留，未将HTTP200或解析完成计作整链路成功。
- 旧会话归属旧报告已纠正：46/46保留原有效owner，40条原本软删；副本实际Auth→Chat验证6条有效历史与22条消息可读、同空间peer6/6拒绝、40条软删逐条拒绝，输入hash未变。[实际核验](evidence/20261010-legacy-session-owner-verification.json)。未加入归属映射工具或重分配用户记录。

- 引用准确定位与评测遗漏已完成源码和组件/HTTP/IPC回归；联合前端187/187与构建通过。尚未部署正式原生复测；Agent文档工具真实引用收集和可选记忆坏JSON中止问答仍在修复。

## 安装版与扩展标准题的最新事实

基线第二NSIS实际安装到独立中文空格目录，exit0，应用和卸载器存在，单次安装170301.9354ms。[实际安装](../refactor-evidence/20261010-windows-nsis-installation.json)。安装版PATH仅含System32时smoke exit0，正式IPC、无HTTP、无渲染Node暴露及页面挂载通过；单次启动1450.8846ms，11716.0315ms是整体执行而非启动延迟。[安装版smoke](../refactor-evidence/20261010-windows-installed-smoke.json)。第一次PowerShell读取UTF8结果未指定Encoding而解析失败属于验收脚本问题，原smoke JSON本身有效；修正后独立新数据目录实际重复执行通过。基线不含最新修复，最终升级和卸载尚未执行。

《交付计划》通过原生重解析获得真实有效摘要及两Wiki页，完整root36673ms已关闭，pending=0。[阶段及用量](../refactor-evidence/20261010-windows-auxiliary-vendor-regression.json)。本地发布后仍显示旧failed摘要的问题已定位为workflow统计/轮询，源码24项回归通过；需在最终界面复核。

六次额外真实GUI题的答案已人工与自编资料核对：表格19件/1851元/无运费正确，图片ORCA-QA-7421/32/2026-10-20正确，电话与运费明确拒编，别名及服务政策正确；除表格以外未产生机器引用，完整验收记产品失败而非通过。相似实体题只有记忆关键词一次4946ms调用（84 prompt/256 completion/250 reasoning），随后turn/error，没有主Agent调用；当前代码将结构校验错误从可选记忆直接传播，正做精确降级与失败usage回归。[六题GUI记录](../refactor-evidence/20261010-windows-native-gold-extra.json)、[同request只读诊断](../refactor-evidence/20261010-windows-memory-failure.json)。UI首行原始Markdown匹配false只作观测，未误判实际渲染失败。

引用source定位/真实TDesign焦点与评测恢复能力联合前端187/187、core typecheck/build、评测专项16/16+原有4/4通过。[评测源码证据](../evidence/20261010-evaluation-retention-parser-worker.json)。受控模型结果不计厂商五题质量结论，下一步以正式原生链路验收。

## 当前Windows候选版复测

当前QA仅更新应用代码，435项文件SHA逐项核对，原始模型配置、账户、数据库和凭据保留；最终安装包尚未构建。[候选资源证据](../refactor-evidence/20261010-windows-candidate-refresh.json)。维护停止的一次AccessDenied被保留；后续精确QA路径检查确认无残留进程，不能计作正常退出。

在可见窗口通过真实“重解析”点击复测图片、现行手册、失效旧版和CSV后，四份摘要均成功、pending=0，root均为done，完整耗时30856/46427/33062/19373ms。图片OCR2492ms、描述3780ms、Embedding319ms、摘要1448ms；验证码、32台设备和2026-10-20日期与自编标准答案一致。现行手册负责人/预算、失效声明和CSV1851元合计也正确。原交付计划结果保留而未重复付费调用。[实际操作、阶段和厂商用量](../refactor-evidence/20261010-windows-document-vendor-regression.json)。其余未执行子项仍须独立验收。

安装版使用独立自建账户实测密码校验、取消、成功修改与后续登录，数据库只读验证新密码哈希有效、旧设备撤销及新设备创建；未修改真实用户密码。输入后页面已认证，但显式登录按钮点击未捕获，不把该动作计通过。[密码记录](../refactor-evidence/20261010-windows-installed-password.json)。管理设备入口及刷新实际可用，撤销/全体退出等仍未执行。[设备页面](../refactor-evidence/20261010-windows-installed-devices.json)。

冻结后的公开渠道、旧空间HTTP/IPC与既有认证经根代理独立组合18/18通过，11299.582043ms，核心typecheck/build均exit0；包含真实受控模型请求取消、不可越界工具和固定公共路由/CSRF。此为真实集成测试，不代表远程部署或GUI验收。[TAP及源码哈希](../refactor-evidence/20261010-root-frozen-legacy-channel.json)。旧Neo4j已经配置，但真实只读连接失败，WSL和Windows均无对应运行服务；实际原图数量未知，记录环境失败而非空图。

相似实体题已通过原生输入与发送重新执行：晨星A为星河科技/林青/128000元，B为海岳科技/周宁/12800元，预算不同且相差10倍，回复完成并保存1条真实工具引用。图片题重新执行返回ORCA-QA-7421、32、2026-10-20，保存5条实际读取引用；展开后点击第2条“查看来源”，打开图片文档的准确OCR分块并显示图片预览与识别正文。[真实GUI、事实审核及只读数据库证据](../refactor-evidence/20261010-windows-model-vendor-regression.json)。随后截图捕获遇到Windows锁屏，捕获像素不是应用，因此该图片已删除、不算视觉证据；已请求用户解锁，继续独立构建和浏览器工作。

Owned-process超时测试的TS/数据库fixture启动耗时超过3秒期限，已改为真实裸Node TERM-resistant进程树fixture；生产超时和退出断言未放宽。独立27/27通过，22114.354ms，仍检查实际超时、后代清理与其他子进程不受影响。[测试证据](../refactor-evidence/20261010-owned-process-fixture-regression.json)。

## 完整自动化基线与Graph来源回归

根代理在WSL Node22.23.2运行 `TMPDIR=/dev/shm node --import tsx --test --test-concurrency=2 test/*.test.ts`，430/430通过、0失败/跳过，382250.110953ms；另在desktop运行 `node --test *.test.cjs`，12/12通过、0失败/跳过，11032.493201ms。[原始TAP与条件](../refactor-evidence/20261010-root-full-checks.json)。这两项是自动化检查时长；核心全套早于随后发现的Graph metadata修复，桌面测试也不算Windows可见GUI验收。

独立只读审查用正常 `KnowledgeService.updateChunk` 修改source_refs，实测图节点 `2 → 0 → 2`：旧图重复导入把旧实体引用绑定到edited-page:99。[审查复现](../refactor-evidence/20261010-final-core-review.md)。归档metadata此前未参与比较，修复后与当前值使用一致来源投影，仅排除graph_relation_chunks和graph_indirect_relation_chunks。两个普通API来源编辑回归实际RED（Missing expected rejection），修复后在任何外部读取前409，保留失效状态、不改图publication；两个派生关联字段变化仍允许合法重复导入。迁移13/13通过，38861.092849ms；相关Graph/Chat/Application组合53/53通过，53868.57181ms；core typecheck/build均exit0。[RED/GREEN/TAP/源码及编译哈希](../refactor-evidence/20261010-graph-metadata-regression.json)。未向原Neo4j或模型厂商发请求，也未改用户数据。

Windows C正式Node/编译核心gate实际24/24、production Runtime6/6通过，198项源码快照一致；真实SQLite/FTS/vec、IPC和Python verify-only通过。独立Electron NextAuth/cookie/私有JSON/窗口边界链路退出0，自己的核心与fixture正常清理；Windows锁屏，所以不将此计作可见GUI或外部Langfuse验收。[C完整记录](../evidence/20261010-windows-nsis-build.json)。该快照早于新Graph修复，且未纳入新的Wiki和Markdown修改，尚未生成C安装器。

Orca知识库/设置实际按钮和键盘送达后没有出现预期DOM/业务变化，复用页还发生runtime连接关闭；只读核查知识库没有新增。工具连接问题与产品缺陷尚不能等同，相关子项仍未通过。[操作及只读核对](../refactor-evidence/20261010-orca-kb-input-delivery-root.json)、[设置页](../refactor-evidence/20261010-orca-settings-parser-worker.json)、[Wiki入口](../refactor-evidence/20261010-orca-wiki-parser-baseline.json)。

## 前端与源码启动复核

Wiki页补齐和标准Markdown图片分别有真实组件、受控HTTP及Chromium图片加载证据；此前联合前端232/232、Vite构建exit0，不计Orca/native页面通过。[Wiki](../refactor-evidence/20261010-wiki-page-program-verification.json)、[图片](../evidence/20261010-markdown-image-parser-worker.json)。

取消document-only来源后，generation fence阻止旧响应写入，却遗留citationLoading。新增清query/切新KB/无效source/实际手动Chunk四条正式回归均RED（1!=0）；三处读取开始复位loading后，关联37/37通过，23216.078341ms，完整前端236/236通过，45175.5095ms，Vite build exit0，50.13s。既有主包大小警告保留，命令时长不计产品延迟。[原始RED/GREEN及哈希](../refactor-evidence/20261010-citation-loading-regression.json)。

独立审查另外用installed TDesign Select真实输入和legend点击复现：pending搜索清空后spinner不消失、pending过滤图谱取消唯一类型后仍“加载图谱中...”。对应两条正式UI断言分别RED（1!=0），空查询/空类型分支复位loading后，关联58/58、0失败/跳过，45764.690294ms；完整前端238/238、0失败/跳过，52099.883265ms，Vite build exit0，49.29s。dist/index SHA `3e9e05e679066b0a361f6dd93e359dc17517b31ced5e745f268e0cf7e68bcba7` 已冻结。[原始回归和构建](../refactor-evidence/20261010-wiki-loading-regression.json)。原独立脚本三处修复均已复测，5项真实Core DTO组合、16项Markdown DOM、12种有限分数输入独立通过。[独立实际输出](../refactor-evidence/20261010-final-ui-review.md)。以上全部是headless组件/受控集成，不冒充Orca或Windows窗口操作。

根启动入口原专项44/44通过，2.708秒，包含真实受控Node参数/环境及npm转发；同报告明确没有执行Windows Electron GUI。[原始启动证据](../refactor-evidence/20261010-startup-summary.json)。独立读取gate语义、修改payload外Electron.exe及TERM-resistant后代的额外复现发现预检/清理缺口；正常44项不能覆盖这些缺陷，正在按正式prepared/gates契约修复。[独立复现](../refactor-evidence/20261010-final-startup-review.md)。POSIX后代存活不直接推定Windows相同结果，原生树验收另行执行。

根代理通过实际npm CLI启动已编译的TypeScript dev-server，独立新SQLite数据根、随机loopback端口：health/capabilities两个200，auth/me/knowledge-bases两个401，runtime=typescript、version0.7.0且service identity一致；没有创建账号或绕过认证。信号终止所属npm/Core进程组后监听确已关闭，NPM父的实际退出为SIGTERM（不是exit0），测试脚本exit0，临时数据删除。单次2114.52844ms为命令spawn到端口绑定，83.23/6.85/8.14/5.48ms为四条HTTP往返；不计Electron冷启动、页面或厂商延迟。[真实编译入口](../refactor-evidence/20261010-root-start-local-compiled.json)。

后续多格式真实上传的14份自编/既有原创fixture已复制到专用中文空格目录，SHA一致并保留MIT许可；含2.88MB、40000行文本与明确坏/空输入。未上传、未写用户DB、未发厂商请求，计数只为prepared。[哈希与标准预期](../refactor-evidence/20261010-format-fixtures-prepared.json)。

启动器三处审查缺陷修复后，Linux专项90项中85通过、5项Windows专用跳过、0失败，9.804秒；原生Windows专项5/5通过、0跳过，9.755秒。实际private JobObject在取消及parent提前exit7时终止所属后代，保留无关进程；stdout/stderr、中文/空格/shell/quote参数和退出码按原值传递。独立helper副本调用真实Win32失败，创建/分配失败后挂起child不执行marker，保留安全失败。41/26ms是独立Node夹具清理时间，不算Electron页面或产品退出延迟。生产源码已冻结，root再核4份源码及6份原始日志SHA/size一致。[稳定原始证据](../refactor-evidence/20261010-startup-review-fix-summary.json)。独立复核用旧3缺陷的4项最小selector实跑4/4、0跳过、2861.446824ms；Windows5项原始TAP和PS完整结构已复核但没有重复运行，未冒充额外原生结果。[独立复测](../refactor-evidence/20261010-final-startup-fixes-recheck-parser-worker.md)。

正式构建入口专项Linux35项中33通过、2项Windows专用跳过；Windows35项中31通过、4项POSIX专用跳过，0失败。实际Windows Job取消/提前退出/无关进程保留、junction拒绝、SQLite/FTS/vec/IPC及实际ASAR均执行。[原始Windows JSON](../refactor-evidence/20261010-windows-repository-windows-unit.json)、[Windows日志](../refactor-evidence/20261010-windows-repository-windows-unit.log)、[Linux日志](../refactor-evidence/20261010-windows-repository-linux-unit.log)。独立17项Linux、2项原生Windows和真实ASAR10资产/18完整worker及5篡改负例通过；5份构建源码前后SHA一致。[只读复核及实际输出](../refactor-evidence/20261010-final-windows-builder-review.md)。这些不计新NSIS、安装、手工GUI或厂商验收。

18:24只读再次获取QA窗口状态，没有恢复焦点或发送输入。UIA树仍可读，截图显示Windows锁屏，像素不计应用证据；精确截图和临时JSON已删除。0项产品通过，用户解锁请求仍待回复。[环境记录](../refactor-evidence/20261010-root-lock-screen-status.json)。

升级前独立安装目录只读预检确认验收用户/知识库存在、2设备、0模型、desktop_jobs/task_records均0、FK错误0及schema checksum；没有读取密码、API Key或改数据/进程，升级和卸载尚未执行。首次脚本未使用实际队列表名/status字段，读取当前schema后明确核对这两表；该脚本修正与控制台UTF8设置不涉及生产缺陷。当前已配置四模型的可见QA目录未触碰。[原生只读预检](../refactor-evidence/20261010-installed-upgrade-readonly-preflight.json)。临时脚本已删除。

正式Windows当前源码 `--refresh --prepare-only` exit0：360来源、73 Electron分发完整一致；根代理当时独立计算360源码SHA无差异。Windows前端238/238、0失败/跳过、228907.4419ms；正式核心24/24、12616.2785ms，生产Runtime6/6、4163.0318ms，真实SQLite/FTS/vec/IPC、Python11格式及110锁定依赖、独立Electron NextAuth全部通过。前端最终index SHA3e9e05...与WSL冻结一致；不能计作手工GUI、厂商评测或安装版通过。[实际准备快照](../refactor-evidence/20261010-windows-repository-prepared-build.json)、[正式gate](../refactor-evidence/20261010-windows-repository-gates.json)。

用户已回复解锁；实际只读Win32检查InputDesktop=Default、应用与探针session1、应用响应正常，但19:03及后续只读前台仍为 `LockApp.exe`，不能用Default推定桌面已解锁。Orca新截图仍是锁屏像素，恢复后键盘报window_not_focused，辅助访问点击回执未建立动作成功。重新读取Orca浏览器并点击“创建个人账号”后，登录页DOM及URL也未改变。已请求人工激活标题栏，停止重复恢复；这组结果0项产品通过，不将其归为已证实产品缺陷。三份非应用截图已删除。[解锁后工具状态](../refactor-evidence/20261010-root-unlocked-tool-state.json)。

真实Windows源码桌面CLI发现构建marker互操作缺陷：官方Python stage中的 `.marlin-build`为26字节CRLF，Node预检只接受25字节LF，因此exit1、305.2484ms即拒绝“目录不属于当前 Electron 构建”。该时长是失败命令总耗时，不是启动延迟；没有启动Electron、创建smoke目录或调用模型。初次验收脚本错误地按大小写访问SystemRoot，修正大小写后才暴露这个实际产品问题，两个失败分别保留；生产修复和正式来源刷新后仍需真实重跑。[实际产品失败及原始日志](../refactor-evidence/20261010-root-source-desktop-smoke-marker-failure.json)、[独立fixture错误](../refactor-evidence/20261010-root-source-desktop-smoke-fixture-failure.json)。

marker修复仅接受完整LF或CRLF值，保留所有来源、正式gate和进程清理检查；真实Windows失败先保留，受控回归12项中的CRLF一项RED，修复后20/20、0跳过，1505.184253ms。root独立核对4份source和两份原始日志SHA/size一致。此为受控启动器检查，真实Windows CLI须等待新的正式prepare后执行。[原始换行回归](../refactor-evidence/20261010-startup-marker-summary.json)。

实际NSIS构建内部exit0后，最终ASAR审计exit1：payload含 `python/Lib/site-packages/zstandard/__pycache__/__init__.cpython-313.pyc`，资源过滤按原设计排除它，导致完整清单不同。该401778343字节失败安装器保留在旧stage、未执行，不是交付。定位为生产器native shim未禁用字节码，仅增加 `-B`；真正解释器在Linux和原生Windows各先RED后GREEN，installed FileMatcher/copyFiles和ASAR正例、模块篡改/许可证删除/额外缓存负例通过。相关完整36项Linux34通过/2跳过、6.489s；Windows32通过/4跳过、18.737s，0失败。root重新核对2生产/测试源码与6原始日志SHA/size一致；锁、资源过滤、旧payload及旧manifest均未改。正在新的空Final Build重新生产110轮子runtime与正式prepare/NSIS，仅复用锁哈希验证的下载归档。[真实NSIS失败](../refactor-evidence/20261010-windows-repository-nsis-red.json)、[生产器回归与明确单元范围](../refactor-evidence/20261010-windows-repository-python-producer.json)。

独立安装目录升级前一致备份已经完成：源以mode=ro打开，SQLite在线备份写入专用Windows本地目录，连接关闭后复制到工作区外0700私有目录，核对12表计数、预期用户/知识库、integrity=ok、FK=0及解密材料副本哈希；root使用Linux SQLite再次独立核对，文件0600。首个备份脚本向WSL共享目录直接打开目标SQLite后挂起、目标0字节；核对脚本路径、PID与创建时间后通过保留handle仅结束该脚本，不停应用，保存失败事实并删除自己的空目标。修正后77.5538ms为单次备份脚本时长，不是产品备份按钮性能，没有读取密码/API Key、调用模型或修改四模型QA数据。升级和卸载仍未执行，完成的3份临时脚本已删除。[成功备份摘要](../refactor-evidence/20261010-installed-upgrade-private-backup.json)、[首次脚本失败](../refactor-evidence/20261010-installed-private-backup-first-attempt.json)。

## 解锁后的可见操作与新构建问题

用户回复窗口在前台后，19:47实际恢复QA窗口，像素为1280×860资料页。随后通过Orca Computer实际点击“修改密码”，观察独立弹窗和三个带标签字段；全部空值点击确认后显示三条对应错误，点击取消后返回资料页。provider回执为accessibility_action_unasserted，操作效果由实际后续树和像素确认，不能写成provider已验证。没有输入密码、调用有效密码修改、改Key或撤销设备。四份原始PNG及操作receipt已保存；这只是435文件候选版的四个子步骤，不计完整UI-SET-009或最终包通过。[实际可见证据](../refactor-evidence/20261010-windows-user-dialog-visible-recheck.json)。Orca产品页的“创建个人账号”点击也实际出现注册标题、注册按钮及新增确认密码输入，历史锁屏失败保持原样。

开发核心旧owned PID683120按精确exe/cwd/argv核验后，仅通过保留pidfd发送SIGTERM并确认退出；541.288ms是工具命令观察时长。新源码核心PID2057390使用同一隔离browser-qa数据，正常health/capabilities均200、runtime=typescript，Ragas源码为已修复版本。没有触碰四模型Windows数据或调用模型。[实际刷新](../refactor-evidence/20261010-root-browser-core-refresh.json)。

RagasBridge仅加入CLI `-B` 后，新增真实module import回归Linux由RED转GREEN；实际Windows当前编译Bridge、owned embedded helper也通过，完整文件路径/SHA库存不变、全树0 pyc、private Job清理。相关评测32、队列27、桌面进程3、parser5均通过，typecheck/build exit0；root独立新增回归1/1、995.105144ms并核源码/编译哈希。受控协议没有厂商调用，不计质量结果或GUI通过。[正式修复及原始TAP](../refactor-evidence/20261010-ragas-bytecode-fix-verification.json)。

全新Final stage首次干净准备在`npm ci`成功后失败：锁定Electron44.7.0官方包没有postinstall，exe缺失。正式builder改为显式运行固定官方install.js；真实生产代码的clean/refresh编排回归先RED，Linux37项35通过/2Windows专用跳过，Windows37项33通过/4POSIX跳过，root独立相关两项通过。官方固定archive、五锁、完整分发/资源审计未放宽。[真实干净失败](../refactor-evidence/20261010-windows-repository-final-clean-red.json)、[修复范围及原始日志](../refactor-evidence/20261010-windows-repository-electron-install.json)。

随后Final `--refresh --prepare-only`实际exit0，777.7149154秒；前端238/238、210445.4853ms，Vite40.24秒；Core24/24、14593.4579ms，生产Runtime6/6、4524.2877ms，native SQLite/IPC、Python11格式/110依赖及独立Electron NextAuth均通过、0 skip/paid。361源码、73 Electron分发、25279 payload文件绑定完成，prepared SHA `ffcf815c5c3ffb8ba65ea8103f2a047dbf93b093247aabc379d5f2d55763e997`、gates SHA `f09770b4be0d259eac36da214032f6214b29151ad5487e10a760d4d580c0a84e`。这些是准备/受控门禁，尚未NSIS。

root使用实际Windows固定Node运行新正式源码CLI，exit1、3564.7806ms，在创建数据/启动窗口前报“构建缺少TS/helper必要文件”。精确只读诊断唯一缺项是`better-sqlite3/build/Release/better_sqlite3.node`；实际锁定13.0.3 loader使用`prebuilds/win32-x64.node`，native gate本身已加载成功，0 Django路径。正在修正必需文件路径及实际布局回归；不会手改payload/manifest，旧失败JSON/log已单独保存。该耗时不是桌面启动延迟。[真实失败](../refactor-evidence/20261010-root-source-desktop-smoke-native-layout-failure.json)、[缺项诊断](../refactor-evidence/20261010-root-source-launcher-payload-diagnostic.json)。

## 当前正式候选、Orca操作与唯一五题厂商运行

SQLite launcher必需文件检查已按实际锁定better-sqlite3 13.0.3的`prebuilds/win32-x64.node`修复，Linux相关26/26、原生Windows14/14与root独立5/5通过。当前第二次正式Final refresh exit0、784.8570551秒；前端238/238、215533.1059ms，Vite42.86秒；Core24/24、14109.9448ms，Runtime6/6、4699.8215ms，native SQL/FTS/vec/IPC及Python11格式/110锁定依赖均通过。361源码/73 Electron分发/25279 runtime文件完整绑定，独立审查确认所有来源与清单一致。[路径修复](../refactor-evidence/20261010-startup-sqlite-prebuild-fix.md)、[正式刷新事实](../refactor-evidence/20261010-windows-repository-final-launcher-refresh-proof.json)、[来源独立复核](../refactor-evidence/20261010-final-launcher-refresh-independent-review-parser-worker.md)。

Root随后真实Windows源码CLI exit0；mounted=true、sandbox/private IPC/TS Core0.7.0、无HTTP监听。内部单次启动1604.8697ms，107553.7582ms是含完整来源/运行时哈希的命令耗时，不能互换或计作冷启动分布。隐藏smoke的PNG仅有背景，没有可见登录内容，因此没有手工GUI就绪通过声明。保护的PID15700与11816均保留。[根代理真实启动](../refactor-evidence/20261010-root-source-desktop-smoke.json)。

正式package-only exit0，835.4979442秒；NSIS、10项ASAR资产及25279实体runtime审计通过。候选安装器位于`C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Installers 20261010\Marlin-Setup-0.6.2-x64.exe`，401778413字节，SHA256 `1a9f6ccec8d154d9ed7019ab8b05416dc038e4c51ee23f4d816ca541268950bc`。内部/外部EXE、7sidecars与正式prepared/gates/manifest逐字节一致，原生独立审查另提取真实ASAR核10资产。root再次核11份raw、当前361source、EXE和三身份哈希。该包仍为candidate，安装/升级/卸载/最终可见页面另验，构建不会调用厂商。[正式NSIS原始证明](../refactor-evidence/20261010-windows-repository-final-nsis-proof.json)、[独立artifact与生命周期审查](../refactor-evidence/20261010-final-nsis-lifecycle-independent-audit-parser-worker.md)、[root独立复算及失败原字节归档](../refactor-evidence/20261010-root-final-artifact-and-paid-failure-archive.json)。

Orca同一真实TS核心中，以专用`orca-page-qa-20261010@example.invalid`账号先验证确认密码不一致提示，再改为一致注册；实际进入知识库，SQLite确认独立个人空间与owner关联。空名称保存未创建对象；新建`Orca 全流程验收 20261010`已成功，配置hybrid/auto父子分块按提交落库。随后真实置顶→收藏查看→取消置顶→全部→复制；空副本删除先取消后确认。9次click与后续snapshot逐步保留；SQLite核原库未删、pinned=false、副本软删、文档/分块/Wiki/索引关联残留0、integrity=ok/FK=0。只操作自建对象，0模型/付费；跨设备、重启和非空关联删除未验证。[注册与新建](../refactor-evidence/20261010-root-orca-registration-kb-create.json)、[置顶复制删除原始操作](../refactor-evidence/20261010-root-orca-kb-pin-copy-delete.json)。

受控loopback MCP服务使用安装的官方SDK1.32.1，真实TypeScript Core链路23/23、exit0、3681.308ms：initialize、tools/list、qa_add20+22=42、中文emoji qa_echo及4次DELETE/后续404关闭有实际协议响应。该服务只提供两个纯本地工具，没有mock产品API或模型请求；按固定30分钟lease正常退出。Orca另实际添加自己的MCP配置，打开编辑回填名称/URL、空Key及enabled；改描述/禁用保存，再打开编辑/启用保存。刷新与删除继续验，GUI Agent调用未计通过。[真实协议与正常认证](../refactor-evidence/20261010-local-mcp-real-core-parser-baseline.json)。

浏览器只读ResourceTiming保存22次既有KB/MCP网络观测，仅含path/status/时间/字节数，不读取cookie/header/正文。新库POST330.5ms、复制336.3ms、确认删除366.5ms、MCP修改324.3ms为单次网络请求；置顶一次401为318.1ms，正常认证恢复后同请求200为44.6ms；MCP创建同样401后正常恢复200，不是重复成功写入。列表请求13.6–348.3ms为混合状态/页面历史样本，没有据此声称页面paint/就绪、完整交互耗时或P95。[原始时间/status观测](../refactor-evidence/20261010-root-orca-kb-mcp-resource-timing.json)。

五题真实评测使用另一份私有Windows数据副本，正常IPC认证恢复后，从人工核对的6个原文切片创建5gold→逐题批准→发布v1→估算；准备usage126→126、fetch0，没有厂商调用。准备命令17169.3982ms包括build hash，具体私有IPC创建/审核/发布/估算24/11/9/27ms为单次API观测，不计GUI。[真实准备及gold](../refactor-evidence/20261010-five-gold-final-preparation.json)、[实际外层执行](../refactor-evidence/20261010-five-gold-final-preparation-execution.json)。

只执行过一次付费run POST，run `def03505-f77e-453f-b847-80d29ee9acc8`，dataset `65e6892b-aa68-4961-bf6e-cb9f32fd0b65`。实际19个unique invocation：5检索Embedding、5ReRank、5回答全部成功；judge前三次成功，第四次在60005ms记录model_timeout/result_unknown。任务interrupted、progress0.3、完成题0/5，coverage0，没有质量指标或可下载报告，不计五题评测通过。正常Core关闭后重新只读核对最终usage，原持久attempt/unknown ledger与失败保留，无自动retry/resume。actual job墙钟174973ms，评分阶段148308ms，outer命令227640.2011ms；API加总不当作墙钟，未知调用没有收到tokens也不等于无计费。[完整失败JSON](../refactor-evidence/20261010-five-gold-final-paid.json)、[实际安全log](../refactor-evidence/20261010-five-gold-final-paid.log)、[outer失败执行](../refactor-evidence/20261010-five-gold-final-paid-execution.json)。

独立原生Windows mode=ro诊断匹配全部19个usage/ledger invocation SHA，DB/WAL/SHM前后不变。第四次失败是ModelRuntime客户端60秒截止；cancel_requested_at为空，结束时lease还余约80秒，Ragas300秒worker预算未到。现有合法startup超时及模型参数均可调整，但改变timeout/thinking会使旧run的配置签名不匹配；同配置manual resume仍须明确ack unknown，已完成RPC可按key/hash复用，未知调用可能重复计费。没有证据证明thinking、JSON校验或厂商HTTP408/504是本次根因。[只读根因与恢复契约](../refactor-evidence/20261010-real-vendor-five-case-interruption-parser-baseline.md)。当前仅准备受控恢复工具，未再次付费；各项GUI与完成报告验收继续保留待办。

Final候选实际在专用`Marlin 安装验收 20261010\应用`执行NSIS升级，exit0，installer命令349204.3079ms为单次观察。安装后全25279个runtime文件哈希、ASAR和当前manifest精确相符；升级前在线备份中的12表所有行和密钥材料与升级后完全一致，integrity=ok/FK=0。仅NSIS维护停止专用旧installed进程，protected真实四模型QA handle/image持续有效。相同0.6.2版本代码替换不伪装为不同版本语义迁移；post-upgrade启动/登录恢复、normal quit、卸载和重装继续分别执行。[实际安装升级收据](../refactor-evidence/20261010-installed-code-upgrade.json)。

## 账号、设备与安装恢复的最新事实

Orca专用账号已完成聊天历史关闭/保存/刷新/再次开启，以及密码弹窗空值、确认不一致、错误旧密码、显隐、取消后字段清空和有效修改。成功修改后，正常登录实际拒绝旧密码、接受新密码并恢复原知识库；SQLite独立核对新密码有效、旧密码无效及原设备因password_changed撤销。只修改自建验收账号，真实用户密码/API Key均未输入或修改。[完整实际操作与只读断言](../refactor-evidence/20261010-root-orca-account-history-password-real.json)。

首次有效密码修改实际401，后续新登录才成功；撤销他设备与退出全部设备也分别复现401。脱敏网络记录与只读设备access_expires_at核对证明，这三次请求发生在自然access过期之后，没有改时间或数据库模拟过期。该事实与源码敏感操作缺少提交前续租的路径一致；不能据此声称所有refresh条件都仍有效。错误旧密码与错误登录还分别显示英文Old password mismatch和Invalid credentials，记为待修产品问题。续租及中文提示补丁仅在隔离副本验证，尚未合入或部署。[安全请求状态](../refactor-evidence/20261010-root-orca-safe-auth-network-83ed178a-4e01-47d0-8b43-12e37d3b56be.json)、[前两次过期时间核对](../refactor-evidence/20261010-root-orca-sensitive-operation-expiry-db.json)。

新登录后，Orca真实确认撤销专用第二设备，DELETE200且该设备独立正常HTTP me/refresh均401；当前设备仍可操作。随后确认撤销当前设备，DELETE200并回到login。全体退出先因自然access过期401，另一次正常新登录后实际POST200并返回login，SQLite核本账号所有设备撤销、原库保留。迟到refresh不复活仍待验收；未把工具click回执但零HTTP的第一次动作计为业务提交。键盘辅助脚本最初固定三个Tab，实际新设备列表有四个可用停靠点；只读确认activeElement为SUMMARY后再真实Enter，记为验收脚本假设错误，没有修改DOM或放宽业务断言。[完整设备步骤与独立断言](../refactor-evidence/20261010-root-orca-device-management-real.json)、[撤销第二设备后的独立请求](../refactor-evidence/20261010-root-orca-other-device-check-revoked.json)。

MCP页面已实际完成添加、编辑、禁用、启用、刷新、删除先取消后确认。SQLite以实际resource_type=mcp_services核对自己服务的软删记录，未改其他对象。服务未配置Key，因此不宣称已经验证既有Key留空保存；聊天Agent调用及联网搜索也未计通过。[七个实际步骤与数据库核对](../refactor-evidence/20261010-root-orca-mcp-crud-real.json)。

正式安装生命周期前三次失败的收据保持原字节，第三次post-upgrade后置CIM条件的原失败原因仍无完整现场证据。新的受控恢复阶段核对已完成的正式smoke和正常IPC认证，不重放这两个动作：mounted=true、TS私有Core、me200、原库200，0模型调用。正常refresh只改变device_sessions，其他11张业务表与升级前备份完全一致，不能把认证后的12表写成原字节不变。实际卸载随后exit0，单命令40720.154ms，安装目录与登记均移除；再用同一个安装器重装exit0，单命令156414.643ms，全25354安装/25279 runtime文件库存匹配。两个阶段均确认12表所有行、数据文件库存及解密材料与保留基线一致，integrity=ok/FK=0，四模型QA进程仍活。重装后认证恢复正在执行；这些进程探针不算可见GUI、正常托盘退出或全部J组通过。[第三次原失败](../refactor-evidence/20261010-root-installed-post-upgrade-third-failed.json)、[恢复升级后证据](../refactor-evidence/20261010-root-installed-recovery-recover-post-upgrade.json)、[真实卸载](../refactor-evidence/20261010-root-installed-recovery-uninstall-retain.json)、[实际重装](../refactor-evidence/20261010-root-installed-recovery-reinstall.json)。

## 证据规则与早期准备记录（持续适用）

最新集成：续期与中文提示12文件补丁按原/新SHA已合入，原字节私有备份保留。根代理全前端300/300通过后，在可见原生模型页1280×860观察到排行裁切；真实Settings组件/CSS浏览器回归同尺寸RED，排行right1279超过内容right1207。最小容器查询修复后1440×900、1280×860、1024×768、390×844均GREEN，随后前端301/301、0失败/跳过（54484.646172ms）及Vite构建exit0（45.94秒）。构建主包1.49MB警告仍存在，不能计作页面性能已优化；原生QA和正式安装包尚未部署本修复。[全部前端TAP](../refactor-evidence/20261010-root-sensitive-ui-layout-full-unit.tap)、[布局RED](../refactor-evidence/20261010-model-settings-layout-red.tap)、[布局GREEN](../refactor-evidence/20261010-model-settings-layout-green.tap)、[真实原生截图](../refactor-evidence/20261010-root-native-model-ui-78d940d4-5739-4564-8e19-f8a592f929ed.png)。

Orca真实错密码登录401后显示“邮箱或密码错误”，用当前验收密码正常登录后恢复原库；资料页弹窗错误旧密码实际POST400，显示“当前密码不正确”并保留字段与弹窗。未修改真实管理员密码。正确密码表单已准备，等待自然access到期复测续期，不调整系统或数据库时间。API结果与页面观察分别记录。[脱敏请求序列](../refactor-evidence/20261010-root-orca-safe-auth-network-88bdd4de-4825-49b5-9849-682c1305c0b1.json)、[真实旧密码中文提示](../refactor-evidence/20261010-root-orca-owned-field-d936093f-7fe4-41ed-b752-5eb2389b5a29.json)。

安装恢复后置核对已完成：原post-reinstall探针实际smoke/正常认证成功，随后CIM计数1失败；原失败与7份raw逐字节归档，原因未证实。后续只读核对原探针/来源/当前完整安装库存，前后计数0、11张其他业务表及密钥精确保留，device_sessions正常refresh改变，核对期间数据不变、integrity/FK正常、四模型QA存活。没有重放认证或安装/卸载/模型请求，不把该核对算作正常托盘退出或可见GUI。源码冻结解除后已合入新补丁，旧安装器身份不代表最新源码。[严格后置核对与证据绑定](../refactor-evidence/20261010-root-installed-post-reinstall-postconditions/readonly-postconditions.json)。

评分预算补丁6文件已按SHA合入主仓库；3个产品文件与此前候选完全一致，仅两项新增测试改用MARLIN_TEST_PYTHON绝对路径以支持真正Windows helper。根代理隔离9/9、typecheck/build通过，主仓库检查继续。没有改模型60秒超时、thinking、指标、签名或未知账本；旧五题run仍是0/5完成、未知调用未重放，不能计厂商评分通过。[集成收据与补丁](../refactor-evidence/20261010-root-evaluation-budget-portable/integration.json)。

升级前只读检查HKCU/HKLM的32/64位注册视图，已登记InstallLocation/UninstallString均为专用安装目录，没有同GUID机器安装；当前Marlin及Node辅助进程都在该目录树，CIM可用/Process execution policy=Undefined。首个验收脚本只允许exe直接父目录，误拒绝合法 `resources/runtime/node/node.exe`，未停进程或安装；使用目录树边界后通过。新安装器执行前仍重查登记/来源/所属进程。[登记预检](../refactor-evidence/20261010-installed-registry-preflight.json)。

厂商五题的私有数据准备通过：原四模型visible-data以mode=ro和SQLite在线备份生成另一份独立Windows静态目录，父ACL仅当前用户/SYSTEM/Admin。12表计数、7业务文件SHA、integrity=ok/FK=0经root再独立核对；5资料、19分块、28Wiki、2会话/22消息和四有效模型保留，另有1软删模型记录。首个脚本错误地要求四条总模型，只创建了自己空目录/ACL、没有快照或模型请求；改为核对未删除模型后完成。原QA没有非终态任务、未写原数据、未复制Chromium profile、未输出Key；418.5279ms仅为单次复制脚本时长。正常IPC登录恢复/机器gold审核及paid Ragas尚未执行，H-02不计通过。[副本摘要](../refactor-evidence/20261010-real-vendor-evaluation-private-copy.json)。两份已完成临时脚本已删除。

随后root在真实Windows staged Node22.23.2运行同一编译Core+CoreIpcAdapter预检，exit0。保留的原desktop会话经正常 `auth/me`401→`auth/refresh`200→`auth/me`200恢复；只轮换私有副本会话，不猜密码/重置/注入身份。五资料hash/状态、当前enabled分块/codepoint引用、PNG实际OCR标识、四角色configured及1024维ready索引检查通过，原文6切片和5固定参考答案人工核对有效。fetch=0、usage126→126，所有scope GET成功，私有Job清理。1330.3969ms只是预检命令时长，2/15/3ms是三次实际私有IPC认证请求的单次观测，不计GUI/厂商延迟。root独立核对5编译JS和worker SHA与当前WSL dist一致。尚无数据集写入/发布/评测运行；H-02依然未通过。[完整事实与gold](../refactor-evidence/20261010-real-vendor-evaluation-preflight.json)、[实际命令摘要](../refactor-evidence/20261010-real-vendor-evaluation-preflight-execution.json)、[精确协议和后续边界](../refactor-evidence/20261010-real-vendor-evaluation-preflight.md)。root完成的临时runner已删除。

构建期的producer缓存修复之后，另一处运行期缺陷由独立真实import复现：RagasBridge使用 `['-u', worker]`，Linux实际Bridge协议成功却在自己的worker树新增 `__pycache__/owned_fixture_module.cpython-38.pyc`，库存不变断言RED；唯一变量加CLI `-B`的对照零新增。Windows仅在独立copied embedded3.13.16 helper树运行等价CLI，未改/执行正式stage的Python：原CLI产生cpython-313.pyc，`-B`零新增；私有Job清理/副本删除。额外env-only实测同样dont_write_bytecode=true，初次“隔离一定忽略env”的推断已纠正，不作为缺陷事实。root读回两平台JSON/原始LinuxTAP并核当前源SHA；没有模型请求。正式修复及当前源码重新构建仍待执行，不能把候选-B对照计成产品已修复。[LinuxBridge RED](../refactor-evidence/20261010-ragas-bytecode-parser-worker-linux.tap)、[Linux事实](../refactor-evidence/20261010-ragas-bytecode-parser-worker-linux.json)、[原生等价CLI](../refactor-evidence/20261010-ragas-bytecode-parser-worker-windows.json)。

固定目录 `docs/desktop-refactor/evidence/` 保存无秘密的检查摘要、截图、结构化结果。认证/解密材料仅存工作区外私有验收目录，不能进入证据。之后每项结果记录日期、版本、数据目录、命令/真实步骤、模型非秘密配置、预期实际、耗时和证据路径。

## 自然过期回归与新正式Windows准备（2026-10-11 00:05）

Orca专用账号在access自然过期、refresh idle/absolute仍有效时，实际确认改密码、撤销其他设备、退出所有设备。三次均有 `GET me401 → POST refresh200 → GET me200 → 业务写入200`，成功业务写入各一次；只读前后数据库确认改密撤销旧设备、撤销其他不退出当前、全体退出所有验收设备。后续正常登录拒绝此前密码、接受私有文件中的当前密码并恢复原库；真实用户凭据未改。全体退出第一次click回执虽然成功但零HTTP/无业务变化，未计通过；实际焦点按钮Enter提交后才返回login。[全部脱敏请求与前后断言](../refactor-evidence/20261010-root-sensitive-natural-expiry-real.json)。

三项业务请求的单次浏览器ResourceTiming为1022.9/75.9/75.0ms，从首个身份检查开始至业务响应结束的网络跨度为1612.2/644.9/653.6ms；包括浏览器调度和真实认证请求，不是纯服务端耗时、页面paint、自动化工具等待或P95。每项只有一次样本。独立被撤销设备正常me/refresh均401。[原始ResourceTiming](../refactor-evidence/20261010-root-auth-expired-resource-timing.json)、[独立他设备请求](../refactor-evidence/20261010-root-orca-other-device-renewal-check-revoked.json)。过期撤销当前、真实共享storage页签和迟到refresh、最终原生安装版仍未完成。

主仓库预算修复typecheck/build exit0，相关26/26、0失败/跳过，203691.872164ms；当前Windows正式payload的Python运行新增预算/取消/恢复9/9、0失败/跳过，7947.4361ms。用假Key与loopback HTTP夹具验证实际HTTP/SQLite/工作进程，不是厂商算法或质量验收。未修改模型60秒超时、思考策略、指标、配置签名和旧未知请求；旧五题仍0/5完成。[主仓库TAP](../refactor-evidence/20261010-root-evaluation-budget-main-related.tap)、[Windows原始TAP](../refactor-evidence/20261010-root-formal-integrated-prepare/root-evaluation-budget-windows-nine.tap)。

新正式Windows `--refresh --prepare-only`实际exit0、760.7469514秒。独立核366当前源码与prepared/gates/payload逐项一致；Windows前端301/301、219858.5348ms，Core24/24、13400.8699ms，Runtime6/6、4643.7579ms，均0失败/跳过。Vite39.10秒，主包大小警告仍存在。真实SQL/FTS/vec/私有IPC、Python11格式/110依赖及受控Electron NextAuth通过，10份原始文件按字节/SHA归档；这些构建检查不代替手工GUI和厂商。[最新正式准备归档](../refactor-evidence/20261010-root-formal-integrated-prepare/archive.json)。首个刷新失败是Node官方归档解压尚未完成，npm缺自身package.json，未执行前端测试；完整2032文件与官方ZIP逐字节核对后重新准备成功，原失败保留。[环境问题及核验](../refactor-evidence/20261010-root-formal-refresh-incomplete-build-host/diagnosis-and-complete-host-verification.json)。

当前QA模型小时图已通过实际原生截图确认；旧排行裁切在已加载旧资源中仍可见。85个新前端文件已核SHA同步，需正常重启后复核最新容器布局。[实际小时图](../refactor-evidence/20261010-root-native-model-ui-caefd18e-159d-4802-ac3f-3a85efccfaa4.png)。标题栏关闭后独立原生观察证明窗口hidden、5所属进程存活、无运行任务、模型记录SHA未变；仅计关闭后后台运行。Orca不暴露实际任务栏窗口，使用现有Explorer箭头的正常UIA Invoke；初次找overflow失败是PowerShell null标题封送问题，独立原生只读已找到可见overflow。实际Marlin菜单退出与进程清理、最终安装版继续验收。[关闭后状态](../refactor-evidence/20261010-root-visible-native-lifecycle-after-title-close.json)、[退出前状态](../refactor-evidence/20261010-root-visible-native-lifecycle-before-tray-quit.json)。

## 真实五题结果、检索与页面修复（2026-10-11 13:20）

五题原run `def03505-f77e-453f-b847-80d29ee9acc8` 在明确确认未知请求后仅恢复一次，真实完成5/5、coverage1。18次原成功调用和已保存检索/回答全部复用；新增47次、实际总66次请求，原未知调用保留，未重跑整个评测。实际下载JSON7760字节、SHA `d3036008d35de2f793a9a9593142aa3af3b9c81490ddd9f1a0e5ac45c4802e04`，已重开核对；GUI历史与下载仍未验收。[原始调用与报告归档](../refactor-evidence/20261011-root-five-gold-integrated/archive.json)。

真实faithfulness约0.956、answer relevancy约0.387、context precision约0.2；缺少的context recall/answer correctness为null。前四题未召回手册事实，第五题交付32与日期正确，不能以高faithfulness宣称回答质量通过。只读实际SQLite查明10个可检索分块只有3个符合当前generation指纹；旧指纹包含摘要、Wiki和流程metadata，正文不变的后处理也会使向量失效。[逐题事实](../refactor-evidence/20261011-root-five-gold-integrated/row-inspection.json)、[向量诊断](../refactor-evidence/20261011-root-five-gold-integrated/vector-fingerprint-inspection.json)。

R-VECTOR-METADATA两项真实SQLite回归先RED，再限定指纹为嵌入输入/来源身份，并在付费query embedding之前检查失效。相关53/53通过、11347.575706ms，core类型/构建exit0；这不是厂商或页面时长。新规则下旧索引须正常重建。Orca从专用知识库实际点击手册重解析，7/7可检索分块全部有效，后续摘要和工作流更新不使其失效。[修复设计](RETRIEVAL-REPAIR.md)、[全部原始RED/GREEN](../refactor-evidence/20261011-root-retrieval-pwa-repairs/checks.json)、[真实索引](../refactor-evidence/20261011-browser-model-page/126-root-index-after-reparse.json)。原低分评测报告未改写。

该次真实问题生成16423ms失败，1024 completion中1022为reasoning，错误model_output_invalid。源码只给摘要采用辅助low，问题与metadata继承普通对话策略。R-AUXILIARY-QUESTIONS真实SQLite/解析进程/受控HTTP先RED；三个短任务统一使用已有辅助策略后29/29、60251.40609ms，类型和构建exit0。普通对话high和原预算、超时、失败usage仍受断言保护。[设计](AUXILIARY-POLICY.md)、[实际日志](../refactor-evidence/20261011-root-retrieval-pwa-repairs/auxiliary-related-29.tap)。Orca修复后只再重解析一次：实际任务8446ms、Embedding762ms/710 tokens、摘要2705ms/523、问题1750ms/447、metadata2208ms/508，四调用全部成功、5个问题与无warnings，索引保持7/7有效。[真实厂商记录](../refactor-evidence/20261011-browser-model-page/146-root-short-auxiliary-retest-db.json)、[持久结果](../refactor-evidence/20261011-browser-model-page/147-root-index-after-short-auxiliary-fix.json)。这些是各一次样本，不声称P95或稳定速度提升幅度。

R-PWA-OCCLUSION实际安装提示覆盖ReRank/视觉按钮。真实App/PwaStatus+CSS的Chromium首先复现pointer interception，改为正常布局后四尺寸1280×860、1440×900、1024×768、390×844可实际点击，说明展开后账户也在视口内。首次GREEN夹具自己覆盖了手机sidebar隐藏，保留失败后按真实responsive规则修正夹具；业务断言保留。前端全套302/302、58899.037749ms，Vite exit0、45.86秒，原1.49MB主包警告仍在。[设计](PWA-LAYOUT.md)、[全部检查](../refactor-evidence/20261011-root-retrieval-pwa-repairs/checks.json)。Orca修复后真实点击ReRank、Embedding、视觉并核单一对应模型卡；135号文件名虽写vision，实际点击的是当时新ref的Embedding，按实际结果记录，137才是视觉操作。说明展开后notice bottom87、shell top87/bottom921、账户bottom921，无横向溢出，0厂商请求。[实际布局](../refactor-evidence/20261011-browser-model-page/142-root-pwa-real-layout-readonly.json)。

浏览器四模型已通过正常认证与可信Core转移到专用用户的空间，没有把Key放入renderer。初始MD/PNG实际上传后15次厂商调用全部成功：Embedding3、视觉2、KnowledgeQA9、ReRank1；保留标准答案与机器引用。Orca原问答来源按钮最初在输入栏后方，正常滚动后点击，正确doc+chunk路由、实际抽屉及林青/128000元正文已核对。旧114号截图在动画中，116号稳定截图才计可见片段证据。[稳定来源画面](../refactor-evidence/20261011-browser-model-page/116-root-source-drawer-stable-screen.png)、[正文与几何](../refactor-evidence/20261011-browser-model-page/115-root-source-readonly-geometry.json)。后续真实重解析额外8次调用中1失败已独立修复，上述15次不是本空间当前累计总数。

原生QA通过真实Explorer托盘菜单“退出”，后置只读核所属进程全部0及模型SHA不变；随后正常重启PID25268，账户与四模型恢复、排行完整。小时和15分钟通过可见坐标正常点击及后续实际图表/轴变化核对；不把UIA仅送达回执当作选择成功。1440×900/1024×768原生、崩溃恢复及正式安装版剩余项未完成。[正常重启](../refactor-evidence/20261011-native-model-page/restart-proof.json)、[实际15分钟图](../refactor-evidence/20261011-native-model-page/root-980264e8-d7d4-4afb-81f6-3ac5a148c673.png)。

366源码正式NSIS实际构建exit0、792.4191824秒，401781252字节，SHA `1c80e12b66059eab0e2dfa2de73b948886929fd6940ac53b3f877c1758a6c087`，路径 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Integrated Installers 20261010\Marlin-Setup-0.6.2-x64.exe`。完整25280 runtime、73 Electron和真实ASAR `555b30fca642151d3a8a75629d377a0e561fbf5713a7b6b71bd2b7ec52cfdc1a` 已独立绑定。[构建归档](../refactor-evidence/20261011-root-integrated-nsis-package/archive.json)。随后专用目录同版本代码升级exit0、单次installer命令388258.982ms；25355安装文件、25280 runtime匹配，12表、全部数据文件、凭据精确保留，integrity/FK正常，protected QA仍活，0API/模型调用。[实际升级收据](../refactor-evidence/20261011-root-integrated-installed-code-upgrade.json)。初次wrapper exit143发生在事务WORK生成前，独立进程/WORK核对后才执行一次实际安装。该包不含本轮检索/辅助/PWA修复，尚非最终交付；当前核心全套正在运行，最新源码仍需重新正式绑定与安装版GUI验收。

## 当前完整检查、联合题与原生尺寸（2026-10-11 13:44）

当前源码在WSL Node22.23.2运行 `TMPDIR=/dev/shm node --import tsx --test --test-concurrency=2 test/*.test.ts` 实际exit0，445/445、0失败/取消/跳过，409134.884962ms。原始日志SHA `ace6dd7a5cccc3cb441f7cc81464fa0c617b6259fa320f61c758c47ce9200373`，与本轮9个修复/测试文件的当前SHA绑定；未调用真实厂商，不能把全套时长写作页面性能。[结构化结果](../refactor-evidence/20261011-root-retrieval-pwa-repairs/current-core-full-results.json)、[完整TAP](../refactor-evidence/20261011-root-retrieval-pwa-repairs/current-core-full-445.tap)。

Orca从自己的知识库发起草稿，预选库保留，只点击一次发送联合题：P1故障响应及图片验证码/数量/日期。后台实际agent_duration_ms=24380；7次调用全部成功、4511 tokens，包含记忆关键词、两次Agent、两次query embedding及两次ReRank，不能把API时间加总当作墙钟或首段延迟。回答15分钟、ORCA-QA-7421、32、2026-10-20与自编标准一致；保留5条机器引用，其他三个附加来源的相关度偏低，未将本题包装成整体检索质量结论。[实际调用](../refactor-evidence/20261011-browser-model-page/156-root-policy-image-after-send-db.json)、[持久事实及引用](../refactor-evidence/20261011-browser-model-page/185-root-policy-image-live-answer-proof.json)。

正常滚动到引用后，164号文件名虽写image，当时新的@e42实际是手册政策来源，169号稳定截图确认15分钟与退订正文；179号按实际第二引用按钮点击后才打开图片描述来源，184号稳定截图确认原图以及三个字段。前置181号动画pending且分块在视口外，后置183号动画finished、分块x685、原图1000×440且已加载，不用动画中的182号截图宣称可见来源。[手册画面](../refactor-evidence/20261011-browser-model-page/169-root-policy-source-final-screen.png)、[图片画面](../refactor-evidence/20261011-browser-model-page/184-root-image-source-final-visible-screen.png)、[图片几何及加载](../refactor-evidence/20261011-browser-model-page/183-root-image-source-preview-stable-geometry.json)。没有重发问题或改写原五题低分报告。

原生QA窗口按准确PID/窗口/可执行文件及FILETIME核验后分别实际调整1440×900和1024×768。初次守卫把CIM微秒显示当作100ns精度，差6个tick，拒绝前零窗口动作；只读核对后使用实际完整FILETIME精确绑定，没有放宽PID或路径边界。[零动作诊断](../refactor-evidence/20261011-native-model-page/resize-1440-creation-precondition-failure.json)。1440模型排行与缓存图完整；1024排行正常换行，实际滚动到模型卡，并点击ReRank仅显示对应卡。密码卡与独立弹窗字段、确认/取消按钮均可见，真实取消后返回资料页，没有输入密码或改变设备/凭据。[1440实际画面](../refactor-evidence/20261011-native-model-page/root-9be5637d-a4d0-4ce4-9599-e5f9af05f943.png)、[1024排行](../refactor-evidence/20261011-native-model-page/root-b9613713-5b95-442a-b42d-f8526a9370b6.png)、[1024弹窗](../refactor-evidence/20261011-native-model-page/root-9e27bcd4-0dd5-481a-a062-fd4d2e1cedb4.png)。

窗口实际恢复1280×860，ReRank状态保留；原生模型所有行SHA仍为 `2b19b0c1e3fc561ac3a62dfd4dbb59f5b7eb807600c46111c280dfeacf6f7d4d`，没有非终态新任务。Windows DPI96，即100%；125%/150%、其他页面键盘/IME和最终安装版仍未验证。[尺寸恢复](../refactor-evidence/20261011-native-model-page/resize-restore.json)、[恢复后独立数据核对](../refactor-evidence/20261011-root-current-native-054049069302.json)。

新的正式 `--refresh --prepare-only` 已从368项实际源码启动，之后才执行 `--package-only`，两阶段各用单独私有Job与1800秒期限，零厂商调用；源码冻结持续到打包退出。旧366包和证据保留，正式stage只通过已审查构建入口刷新，没有手改payload或manifest。准备/打包及安装版状态按真实后续收据更新，此处不记通过。[来源快照](../refactor-evidence/20261011-root-repaired-windows-build/source-snapshot.json)、[唯一准备尝试](../refactor-evidence/20261011-root-repaired-windows-build/prepare-attempt.json)。

## Wiki及记忆复测（2026-10-11 15:33）

Orca仍使用同一TS0.7.0核心、localhost:5173、专用browser-qa数据目录及用户空间2，真实GLM配置保留。正常编辑276字符Wiki正文时，保存按钮bottom834.8超出659像素窗口，正常滚动仍无效。实际TDesign类型允许maxRows；最小限制12行后bottom592.8、正文内部滚动且完整保存。真实组件1289×659/1024×768两项由RED转GREEN，前端完整308/308、0失败/跳过、86293.037ms，构建exit0/48.88秒；这些命令时长不算页面延迟。[设计](WIKI-EDITOR-LAYOUT.md)、[原始TAP/构建与源码SHA](../refactor-evidence/20261011-root-memory-context-wiki-checks-v2/checks.json)。第一次归档脚本误用了layout日志文件名，未生成成功manifest；完整原字节在v2目录，不能把归档错误算产品失败。

真实页面通过正常控件创建版本1，编辑添加用户上传图片为版本2；刷新、搜索、重新选择后正文保持。表格、代码、KaTeX和目录、实体双链、缺失双链的“Wiki 页面不存在”均实际验证。图片HTTP200、322.6ms为单次资源网络观测，解码1000×440且可见；脚本标记false。删除先取消保持版本2，再正常确认仅验收页软删为版本3。只读对比原12页正文/source_refs/chunk_refs均未变，原图文档保留。生成页来源按钮打开正确手册#7政策分块，解析显示45.0秒全部结束，旧进度未复现为持续缺陷。[综合验证](../refactor-evidence/20261011-browser-model-page/407-root-memory-wiki-real-verification.json)、[可见图片](../refactor-evidence/20261011-browser-model-page/366-root-wiki-real-image-visible-screen.png)、[来源实际结果](../refactor-evidence/20261011-browser-model-page/385-root-wiki-source-route-result.json)。空标题首次点击在视口外未提交，不能计作校验通过。

记忆结构契约修复后，两轮六次模型调用全部成功、3672 tokens，但实际回答否认记忆并“不知道”，保存成功不算召回通过。随后能力与摘要/描述匹配修复使模型正确说明应用能力，却把旧MX-MEM-SHAPE-8542认作最新，原始用户时间证明最新是MX-MEM-CONTRACT-9653；该错误又进入后台摘要，失败完整保留。[真实错误及原文](../refactor-evidence/20261011-browser-model-page/397-root-memory-policy-timeline-failed-proof.json)。

时间来源修复只将既有有效授权会话中的可见用户原文、created_at与摘要一起提供；最多5条、每条4000字符并标截断，不读取助手/隐藏/已删/他会话原文，不新增模型请求。真实SQLite两项先RED，相关62/62、0失败/跳过、65334.971ms；类型与核心构建exit0。上一源码完整457/457、644723.648ms已归档；当前新增两项后的459完整正在执行，不能混用源码时期。[设计](MEMORY-AUXILIARY-POLICY.md)、[62相关及原始RED](../refactor-evidence/20261011-root-memory-chronology-checks/checks.json)。

新会话仅正常点击一次发送同一不含代号问题，RID021070ac：真实回答最新9653、引用原用户06:46:11时间，区分06:24:50旧代号，并识别保留的错误摘要。后台stored，三次调用全部成功：关键词2027ms、主回答21972ms、提取4110ms，3588 tokens；实际回答24220ms。源与召回会话不同，没有重新输入答案或删旧错误记忆。Neo4j状态forbidden，仅本地记忆通过；不是全套记忆开关/权限/正式安装验收。[实际事实与用量](../refactor-evidence/20261011-browser-model-page/407-root-memory-wiki-real-verification.json)、[实际回答](../refactor-evidence/20261011-browser-model-page/403-root-memory-chronology-live-answer.json)。

最新Windows准备已绑定371项当前源码，零厂商调用、源码冻结到打包退出；打包前门禁要求当前459项完整成功与SHA一致。此前368准备因前端301/302失败而停止，保留原失败；未放宽断言的Windows并发2完整302/302已通过。最新Windows准备/打包/安装仍不计通过。[最新源码快照](../refactor-evidence/20261011-root-memory-wiki-windows-build/source-snapshot.json)、[唯一准备尝试](../refactor-evidence/20261011-root-memory-wiki-windows-build/prepare-attempt.json)。

当前源码完整核心已实际exit0：459/459、0失败/取消/跳过，410196.753ms。原字节TAP与24份修复源码/测试SHA已归档并满足打包门禁，不能计作Windows页面或厂商延迟。[完整检查](../refactor-evidence/20261011-root-memory-chronology-full/checks.json)。

## 图谱、格式上传及正式包（2026-10-11 16:12）

Orca实际操作Wiki图谱：11节点概览、箭头开关（26关系线，6条双向）、概念过滤后7节点、空态、恢复11节点、A项目详情及邻域7节点、关闭详情、返回全库与适应屏幕。首次邻域按钮在视口外，click回执并未改变图；focus/Enter后才确认真实邻域结果。实际画布拖拽70×30像素改变对应translate；节点拖动60×40像素改变局部坐标，再因正常click聚焦居中。事件观察仅收集类型、坐标与trusted，未调用业务处理函数。[画布实际事件和位移](../refactor-evidence/20261011-browser-model-page/457-root-wiki-pan-effect.json)、[节点实际结果](../refactor-evidence/20261011-browser-model-page/465-root-wiki-node-drag-effect.json)。

搜索“晨星”正常请求HTTP200，选择B项目后抽屉显示海岳科技、周宁、预算12800；搜索不存在实体显示“暂无数据”。两次ResourceTiming为15.1/14.4ms，各一次本地接口观测，不代表页面就绪或P95。B项目来源正常focus/Enter打开手册#6，正确显示A/B不同预算与负责人；关闭来源、点击返回知识库，列表恢复。内嵌Wiki正常打开11页目录，没有新建/编辑/删除入口。[搜索请求及观察器清理](../refactor-evidence/20261011-browser-model-page/472-root-wiki-search-request-and-observer-cleanup.json)、[B来源真实结果](../refactor-evidence/20261011-browser-model-page/480-root-wiki-b-source-effect.json)、[内嵌只读](../refactor-evidence/20261011-browser-model-page/490-root-embedded-wiki-entry-count.json)。滚轮多次工具回执成功，但没有wheel事件且scale不变，记录工具送达问题，缩放未通过；没有注入wheel冒充真实操作。双击和正式原生链路仍待验证。

371项源码正式Windows准备exit0/834.625秒，前端308/308、270885.594ms，Vite exit0/37.83秒；核心、生产Runtime、native SQLite/IPC、Python及受控Electron NextAuth门禁通过。随后正式package-only exit0/783.492秒，完整ASAR与25280 runtime绑定，独占wrapper最终exit0。ASAR桌面壳代码未变，因此壳SHA与旧包相同；新的前端/核心包含在新的runtime manifest中，不能用壳SHA代替完整应用身份。[准备实际收据](../refactor-evidence/20261011-root-memory-wiki-windows-build/prepare-execution.json)、[打包实际收据](../refactor-evidence/20261011-root-memory-wiki-windows-build/package-execution.json)、[完整资源审计](../refactor-evidence/20261011-root-memory-wiki-windows-build/package/asar-audit.json)。安装升级已在专用目录发起，结果及最终GUI尚未验证。

格式库通过Orca正常新建。为了避免2.88MB文件触发大量Embedding，只在空验收库用正常认证HTTP设置keyword=true/vector=false/Wiki=false/graph=false；这是前置配置，不算关键词单独开关的UI验收。原四模型行SHA完全未变，临时配置设备正常退出。[前置配置事实](../refactor-evidence/20261011-root-format-keyword-prerequisite.json)。14份文件SHA与原准备一致；实际file input选择14份后，界面为待上传队列，数据库0文档/0任务/0新调用。重复选01文件仍14；空文件第一次视口外点击没移除，focus/Enter后实际降为13，再追加恢复14且空文件位于末尾。随后只点击一次开始解析，实际14文档入库并显示后台状态。[确认前数据库](../refactor-evidence/20261011-browser-model-page/502-root-format-before-confirm-db.json)、[实际移除](../refactor-evidence/20261011-browser-model-page/511-root-format-empty-removed-effect.json)、[唯一提交](../refactor-evidence/20261011-browser-model-page/514-root-format-fourteen-start-parse-once.json)。解析尚在进行，不把14份被接收当作14份解析成功；首两份只读进度脚本用了错误job payload路径而没读出任务，修正为实际`$.input.knowledge_base_id`后保留原观察并继续核对。[修正后的真实进度](../refactor-evidence/20261011-browser-model-page/518-root-format-correct-job-envelope-progress.json)。

## 大文本、图片与恢复（2026-10-11 17:14）

371项源码安装器已在专用中文空格路径实际升级，exit0；25355安装文件/25280 runtime与清单匹配，12表全部行、数据文件及解密材料精确保留，integrity=ok/FK0，四模型QA仍活。单命令368924.781ms只是安装观察时长。同版本代码升级不冒充版本迁移；本节之后的新修复不在此包中，必须重新正式绑定。[升级原始收据](../refactor-evidence/20261011-root-memory-wiki-installed-code-upgrade.json)。

十四份实际上传中，TXT/文本PDF/扫描PDF/DOCX/XLSX/PPTX/XLS的正文、表格、公式或图像识别有真实结果；中文、空格路径正常。损坏PDF失败；空TXT无正文且没有为空源发模型请求。SVG/HTML/JSON辅助处理已取消，不能以parse completed当作整链路通过。损坏PNG旧流程误计completed，大文本首次持续约96%单核CPU并让health五秒超时；原失败保存。两个已取消模型请求各约359秒，0收到tokens不能推定0计费，未自动重放。[首次真实异常](../refactor-evidence/20261011-root-large-text-runtime-observe.json)、[最新逐文档正文、分块、阶段与用量](../refactor-evidence/20261011-browser-model-page/551-root-indexed-large-terminal-proof.json)。

大文本四个已确认根因分别是保护区间按每个父块重复扫描全文、每个子块重复装载完整文档metadata、每片段序号冲突检查缺索引，以及启动只恢复队列没有协调文档/span。每个回归先RED；分块26、装载74、恢复56及组合106项通过、类型检查exit0。序号索引为非唯一，原碰撞拒绝仍有效；来源与权限过滤保留。不含模型的四万行真实解析→父子分块→FTS入库→末行检索通过，50437.710ms为测试命令中该用例时长。[修复设计](LARGE-DOCUMENT-FIX.md)、[106项相关原始TAP](../refactor-evidence/20261011-root-large-document-related-green.tap)、[真实本地完整流程](../refactor-evidence/20261011-root-large-document-local-full-pipeline.tap)。

按精确PID/创建时间/exe/cwd/全部参数只停止本任务隔离核心；四模型Windows应用未触碰。历史强制停止只用于无法及时响应的本地发布，未当作正常退出通过。最后一次正常SIGTERM后文档正文仍完整，旧尝试已取消，0新模型调用；重新启动后0running span、没有自动重放。第三轮本地发布在正常退出前实际已完成，后续取消状态如实保留，不能把它写成事务未提交。[精确最后正常停止](../refactor-evidence/20261011-root-sequence-index-owned-stop.json)、[重新启动只读证明](../refactor-evidence/20261011-browser-model-page/543-root-sequence-index-restart-proof.json)。

随后Orca只正常点击一次重解析。实际第四attempt完成109610ms：解析5356ms、分块3261ms、本地发布42440ms、后处理54142ms；1429父块/10000可用子块，2.88M正文完整，全部阶段结束、0running span。三个辅助请求分别23577/14677/14698ms，均成功，共7724tokens，5个问题，0warnings。Embedding、图谱和Wiki按该库明确关闭，不计本轮验证通过。120秒只读health观察65个样本、29次三秒超时，最大成功1589.255ms，因此流程完成但响应性能仍失败；观察器总时长不是产品时长。[唯一页面重解析](../refactor-evidence/20261011-browser-model-page/546-root-indexed-large-text-reparse-once.json)、[阶段和调用原始记录](../refactor-evidence/20261011-browser-model-page/551-root-indexed-large-terminal-proof.json)、[健康观察](../refactor-evidence/20261011-root-large-text-indexed-health-monitor.json)。

无模型、无秘密的真实四万行CPU profile确认重复SQL编译自身约16.4秒，逐片段关键词发布约29.5秒。实际查询计划已经使用ID和seq索引。新增有界连接内statement复用，不缓存结果或参数，get/all/run仍每次绑定；三项回归先RED，数据库/JSON/检索46/46通过、8213.773ms，类型检查exit0。DDL变更、事务回滚及容量淘汰也覆盖。单独再跑四万行流程通过、23479.775ms；两次单样本不能作为可靠提速分布，本地耗时仍需优化，不重复已成功的厂商请求来测量本地工作。[方案](SQL-STATEMENT-REUSE.md)、[46相关TAP](../refactor-evidence/20261011-root-statement-reuse-related-green.tap)、[本地四万行复测](../refactor-evidence/20261011-root-statement-reuse-large-local.tap)。

独立审查补上快速重启未到期租约的边界：只跟踪启动遗留任务，按当前租约到期再恢复，不抢持续续租的活任务；退出取消timer。文档恢复在写事务内再检查status/attempt，避免覆盖另一连接已认领的新尝试。真实SQLite/MockTimers回归先RED，99/99相关通过、103433.490ms，类型检查exit0；实际重启仍需主任务复核。[设计与完整证据](LARGE-DOCUMENT-RECOVERY.md)。

坏独立图片原被 `parse_image` 捕获为warning后返回空成功。仅缩窄为 `ImageTooSmallError`，坏PNG/SVG走已有parse_failed，正常小图与内嵌图warning、空文本、扫描PDF保持。Python25/25、实际TS定向4/4、parser12/12及typecheck通过；动态纯色有效图也核对。旧坏PNG已经有processed_at，真实重解析失败应保留原发布语义并显示本次workflow失败，当前前端状态修复和页面回归进行中。[设计](IMAGE-PARSE-ERROR.md)、[原始结果及临时脚本清理](../refactor-evidence/20261011-image-parse-review.json)。

列表还出现取消显示未配置、重解析完成后旧响应覆盖新统计的问题。核心增加仅状态/警告code/来源代际投影，仍省略大正文metadata；前端正在修复状态优先级、同页陈旧回复围栏和单个在途轮询。未把组件检查或手动reload计作自动刷新通过；当前完整套件和Windows新包尚未执行。[页面修复计划](DOCUMENT-STATUS.md)。

## 状态、关键词性能与原生设置（2026-10-11 18:15）

页面修复当前23项相关通过，完整前端326/326、0失败/取消/跳过、82278.648ms，Vite构建exit0/52074.649ms。首轮320/321中Wiki中文长正文失败来自测试HTTP夹具逐Buffer解码，修正流UTF-8解码并新增五条分割回归后7/7通过；失败记录保留，不计产品故障或放宽断言。[命令、原始日志、SHA和清理](../refactor-evidence/20261011-document-status-review.json)。

同一文档旧parse_status=completed但当前workflow=cancelled时，UI显示取消而筛选/计数仍已完成。统一核心有效状态后真实SQLite认证空间RED再32/32通过，typecheckexit0；原正文/原始状态不变。初次相关26/27失败为旧统计断言期待processing文档仍属于completed，已调整互斥类别并保留原正文、FTS和完成后断言；该green文件名不是成功结果。新Orca核心实际DOM已显示10完成/1失败/3取消，实际点击和坏PNG重解析仍待复测。[设计](DOCUMENT-STATUS-FILTER.md)、[32项完整证据](../refactor-evidence/20261011-root-document-status-filter-regression.json)。

关键词发布最终85/85相关通过，类型检查退出0。64ID批次在原同步事务中检验权限、全部seq碰撞、旧向量清理并一次发布；实际查询计划用VALUES/CROSS JOIN主键查找。四万行无模型完整流程最终subtest19892.036ms、完整TAP21949.081ms、process根15135ms；分块3650ms、本地发布8245ms。15.3%只比较同subtest23479.775→19892.036，不混用根/TAP范围，也不能称同步阻塞已解决。[发布设计](KEYWORD-PUBLICATION-PERFORMANCE.md)、[原始证据](../refactor-evidence/20261011-review-keyword-batch-evidence.json)。

关键词查询另有全库遍历：只返回1条仍解码12000片段。MATCH FTS候选先行并定向hydrate，权限/有效条件仍在LIMIT前，短词LIKE语义不变；6项RED后相关107/107、类型检查和链接检查通过。同一隔离12000片段库单次API4433.75→15.26ms，其中初始SQL3909.20→9.94ms，hydration12000→1、文档JSON各读1次。没有重跑四万行/profile/模型，也没有GUI/P95/并发结论；同期纯分块Worker与首批插入优化正在实现。[召回设计](KEYWORD-RECALL-PERFORMANCE.md)、[全部来源与一次测量](../refactor-evidence/20261011-review-keyword-recall-evidence.json)。

原生QA0.7.0、PID25268/window22482662，数据仍为专用visible-data。五参数10/.15/.3/5/.3→11/.2/.35/6/.35正常控件保存，离开至user再进入retrieval仍保持，随后全部恢复。Rerank实际取消勾选/保存，Windows只读SQLite=false，离开并重新进入实际像素仍未勾；再次勾选/保存后原六参数精确恢复。前后模型行SHA均2b19b0c...、usage126、active0，零新模型调用。此为366来源QA子项，Orca/websearch/维度重建和最新安装链路未验，工具等待不是产品保存延迟。[实际步骤、数据库与画面SHA](../refactor-evidence/20261011-root-native-retrieval-system-partial.json)。

系统信息页正常导航、滚动至可见“查看当前生效值”，重新核对前台后点击真实disclosure，树与像素均显示task_workers4、sqlite_timeout30、model_timeout60、log_levelINFO。路径、TS0.7.0、SQLite和已验证向量1024也实际显示；未修改startup，保存/重启/env覆盖仍待验。[展开实际画面](../refactor-evidence/20261011-native-model-page/settings-ec143bae-38fb-49ac-8616-0aff2337d84a.png)、[完整观察](../refactor-evidence/20261011-native-model-page/settings-ec143bae-38fb-49ac-8616-0aff2337d84a.json)。已消费的数值roundtrip临时脚本精确删除，活动GUI及私有认证仍保留到完成。[清理证明](../refactor-evidence/20261011-root-native-retrieval-consumed-script-cleanup.json)。

## Worker集成、SQL诊断与Orca回归（2026-10-11 19:20）

纯分块服务在源码36项及编译Linux/实际Windows链路通过。Workflow持有服务，实际非语义分块走Worker；语义/自定义token计数走原路径；cancel/close等待退出，实际队列与SQLite回归4项RED→4/4 GREEN、9722.550ms。首批chunks采用统一字段默认/编码的insertMany、原外层事务与UUID父子关系；139项相关通过，42.608秒。全局序号三次读取合为一条查询，最大整数/全局冲突/旧索引清理与原顺序保留，61项相关通过。都是隔离检查，不计GUI或厂商。[集成设计](CHUNKING-WORKER-INTEGRATION.md)、[集成来源与日志](../refactor-evidence/20261011-root-worker-bulk-local-integration.json)、[初次发布](INITIAL-PUBLICATION-BATCHING.md)、[序号读取](KEYWORD-ID-PUBLICATION.md)。

当前8份源码冻结后的独立3.2MB/四万行用例1/1通过，1600父/11200子和末行FTS事实完整，0模型。CPU诊断subtest15627.976ms、完整TAP17828.599ms；实际root14220ms、分块4332ms、发布6609ms。主线程publication work加权6513.011ms，FTS写语句self合计3319.844ms；ESM loader辅助线程不算分块算法线程，pub内JSON self18.262ms不能用全进程658ms替代。没有将加权采样相加为独立墙钟。[唯一原始命令与源码](../refactor-evidence/20261011-root-pub-current-profile/command.json)、[只读计算及限制](../refactor-evidence/20261011-root-pub-current-profile/profile-analysis.md)。

两条FTS SQL在相同caller中，采样不能分清；新增一次不改产品的CoreDatabase.run单调计时。该fixture1/1通过，subtest15900.359ms、根14306ms/发布6516ms；175批DELETE累计138.735ms、INSERT3221.971ms、11200登记UPSERT109.880ms。只记录类别/次数/时长，不记SQL绑定或Key；源码前后一致，临时探针和runner已删。删除份额小，未采纳候选OR REPLACE改变写入语义。工具/观察器开销包括在样本中，同期页面/组件活动可能重叠，不能当作无干扰比较、页面响应或P95。最新完整核心正在执行，新正式Windows包尚未构建。[真实SQL计时与原始TAP](../refactor-evidence/20261011-root-fts-sql-timing/command.json)。

Orca同一专用browser-qa数据、TS0.7.0入口，实际focus/Enter取消筛选返回3条；点击完成筛选返回10条。坏PNG实际重解析只提交一次，真实Python reader1916ms失败、root1935ms，root与stage均结束，旧raw parse completed保留；页面自动更新9完成/2失败/3取消，实际失败筛选两坏文件。usage98/模型SHA不变、0running span、零新付费。[591–610实际操作、SHA及只读结果](../refactor-evidence/20261011-root-document-current-status-ui.json)。

## 当前源码完整检查、真实阶段提示及正式Windows准备（2026-10-11 19:39）

核心完整542/542、0失败/取消/跳过，TAP442169.349ms；类型检查及构建exit0，命令15980.499/19961.792ms。前端333/333、0失败/取消/跳过，TAP98635.946ms，构建exit0、命令46453.607ms。每阶段前后来源一致；本次不把单元/集成和构建计为GUI或安装版通过。[核心](../refactor-evidence/20261011-root-current-core-checks/checks.json)、[前端](../refactor-evidence/20261011-root-current-frontend-checks/checks.json)。

真实Orca取消列表中已展开JSON，计算样式为灰条rgb(201,205,212)、深字rgb(78,89,105)，稳定截图683已实际检查；实际点击切失败过滤、展开坏PNG，显示“文件读取: 阶段处理失败”，failed bar1、LIVE0，截图690已实际检查。单次stage ResourceTiming325.3ms，不当作整页或可靠P95。usage98/模型SHA不变、无活动任务，无新模型请求。[完整实际步骤与哈希](../refactor-evidence/20261011-root-trace-error-display-real.json)。

旧专属Core正常SIGTERM退出，当前源码Core PID3033028启动且health正常，源码与完整542检查一致；数据目录保持service_id，不能以ID不变推断旧进程仍在。普通验收用户实际点击系统页只显示非敏感版本/存储/维度信息，管理员配置面板按权限不显示；该观察不代表管理员保存重启已通过。正式Windows因worker源码变化使用新专用目录执行完整干净准备，仍在运行。[当前Core](../refactor-evidence/20261011-root-browser-current-source-running.json)、[真实系统页面](../refactor-evidence/20261011-browser-model-page/694-root-browser-system-readonly-permission.json)、[正式冻结来源](../refactor-evidence/20261011-root-current-worker-windows-build/source-snapshot.json)、[唯一准备尝试](../refactor-evidence/20261011-root-current-worker-windows-build/prepare-attempt.json)。

解析记录旧徽标误读raw状态已修复，真实编译DOM5条新增回归各RED，相关32/32、完整331/331、90.808秒及构建exit0/40.13秒。真实Orca再点击状态下拉/失败、展开PNG、再切取消/展开JSON：2失败、3取消，中文“文档处理失败”，保留最近及历次轨迹；失败/取消stage API各一次ResourceTiming321.4/318.4ms，不能当作页面就绪或工具耗时。新增发现“文件读取: stage_failed”及取消长条白字可读性，最小补充正在收尾，最终整套与实际中文复测另记。[组件证据](PROCESSING-RECORD-STATUS.md)、[665–680实际结果](../refactor-evidence/20261011-root-processing-record-status-ui.json)。

Orca检索配置真实取消Rerank勾选→保存→user→检索，仍false；再次勾选并逐个focus/ArrowRight调整五数值10/.15/.3/5/.3→11/.2/.35/6/.35→保存→离页返回，全部保持。逐个ArrowLeft恢复并正常保存，SQLite有效六参数与原一致、usage98/模型SHA不变，0active job/0付费。原JSON为空，正常保存后包含显式默认值，仅称有效配置恢复；没有SQL手工改回。645误将keypress发给exec DSL被拒绝，后续正式typed keypress才改变控件，保留工具失败；661/673截图在白色过渡中，664/680稳定画面已实际检查，不将前置截图判为持久opacity缺陷。[611–664实际步骤与SHA](../refactor-evidence/20261011-root-browser-retrieval-real.json)、[已用脚本精确清理](../refactor-evidence/20261011-root-browser-roundtrip-script-cleanup.json)。维度切换/重建、websearch、系统保存重启及最终安装版尚未验。
