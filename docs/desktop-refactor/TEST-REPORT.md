# 测试报告（持续更新）

本报告保留构建和失败历史。此前核心693PASS/0FAIL/2条件skip及plain compiled2/2不覆盖当前B类型筛选/auth测试delta；侧栏前端361/361与Vite build退出0。历史6e37来源Windows prepare/package/绑定/专有升级均实际0，94文件/12表/vault保留，但应用未启动/hidden和visible均未执行。当前筛选真实SQLite RED→8/8+44/44、真实mouse分类复验及auth12/12+17/17有独立证据，旧生产认证不变；新delta尚未纳入已安装6e。A有界认证、B DOM清理和此前99ba/5cab restore/normal clone/D/H子项保持，hidden d40b/45ef与新版1024/余页仍待验。最新准确边界见末节，38组整组通过仍仅M-01/M-02，Goal active。

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


## 实际分块、统计优化与Windows产物（2026-10-12 00:42）

Orca正常注册了独立无模型验收账户与空间，实际2.88MB/40,000行上传只提交一次。根15439ms、reader1342ms、Worker分块4053ms、同步发布6676ms，10000正文/1429父块及末行事实完整，Embedding/辅助/图谱/Wiki缺配置明确跳过。24次health观察21次200、3次约3秒超时；两次与发布重叠，第三次开始已晚于发布结束，不能全部归因于发布。全局usage101→101、该空间0模型/0用量，观察器与Windows构建并行，不计算P95。响应性仍属产品失败，完整应用owner、只读WAL与共享取消的实施计划已记录，阶段1正在独立实现。[真实持续观察](../refactor-evidence/20261011-root-model-free-large-live-health.json)、[边界评审](LOCAL-PUBLICATION-RESPONSIVENESS-REVIEW.md)、[实施计划](CORE-OWNER-WORKER-PLAN.md)。

真实编辑短TXT后新额度98765的FTS1、旧额度0；禁用后0、启用后1、删除最后子块后0，文档保留。旧短MD删除先确认取消、再重新打开确认并删除，SQLite核对仅该文档软删、2分块与marker索引清除。其后实际新建标签、上传选择该标签、recursive256/child256，数据库有效配置和标签一致；标签/关键词组合筛选无结果时清除不可见选择，批删/移动禁用，清筛选恢复3文档。类型选择、移动和批删等仍继续测试。此范围都是自建对象、无模型，不能代替删除/编辑后的真实模型问答。[完整真实步骤](../refactor-evidence/20261011-root-chunk-counts-labels-real.json)、[原单文档删除后置核验](../refactor-evidence/20261011-root-gui-chunk-document-deleted.json)。

保存分块仅刷知识库/文档列表导致抽屉总数和父关系陈旧，另发现请求期间新输入被错误清除脏标记。编译Vue行为回归3项实际RED→21/21 GREEN，完整前端338/338、0失败/取消/跳过，TAP95632.490ms；npm命令96157.471ms、Vite44722.142ms，均exit0，109份已列输入SHA前后相同。Orca817–831实际禁用保存后同一抽屉立即2→1、无父关系；重新启用仍1条，FTS0→1，稳定截图实际查看。首次自然401通过正常refresh恢复且成功PUT仅一次，业务PUT47.9/33.3ms、重读页11.6/12.4ms，非工具命令时间。[修复设计与回归](CHUNK-SAVE-REFRESH.md)、[完整前端命令](../refactor-evidence/20261011-root-chunk-save-refresh-checks/result.json)、[禁用后](../refactor-evidence/20261011-root-chunk-fixed-disabled-real.json)、[启用后](../refactor-evidence/20261011-root-chunk-fixed-reenabled-real.json)。

统计两个入口原各读10份块正文/metadata，新真实SQLite专项RED2失败→GREEN5/5、相关95/95、typecheck/build均exit0；保留禁用、父块、类型、namespace/soft-delete与实时权限语义。专属核心PID3033028在无活动任务后精确正常退出，新PID3504717启动相同数据目录。旧空闲GET五次1513.4/1631.2/1621.3/1638.0/1604.1ms，新实际三次127.7/143.6/137.7ms；同库大文件保留，后续短文档新上传和父块清理使总数11429→11431→11430，条件并非完全同一静态数据。只能说明这次读取改善，不能宣称发布并发或P95通过。[统计设计及精确检查](KNOWLEDGE-COUNTS-PERFORMANCE.md)、[真实源码与运行](../refactor-evidence/20261011-root-counts-and-chunk-live-source.json)、[精确停止](../refactor-evidence/20261011-root-browser-counts-source-graceful-stop.json)、[实际GET与步骤](../refactor-evidence/20261011-root-chunk-counts-labels-real.json)。

388项冻结源码正式Windowsprepare1474.954秒、package765.214秒均exit0；Windows24/24+runtime6/6、SQLite3.53.4/vec0.1.9/精确FTS和向量ID、私有IPC、Python11格式/110锁定依赖及受控真实Electron NextAuth通过。ASAR10条白名单、25282 runtime清单精确匹配。安装包401791992字节、SHA256700609da8c047f4d935788dc3fd974136384cd5848517d3b1c2acafc16987a7e，位于Windows专用Marlin TS Current Worker Installers 20261011。尚未执行该包安装/GUI；它早于本次统计和分块刷新，4份现有文件SHA已不同，并新增了统计回归。不可作为当前最终交付，owner实施后还需正式刷新、安装与真实页面验收。[产物SHA与门禁](../refactor-evidence/20261011-root-current-worker-windows-build/artifact-receipt.json)、[Windows原始门禁](../refactor-evidence/20261011-root-current-worker-windows-build/package/windows-gates.json)、[ASAR审计](../refactor-evidence/20261011-root-current-worker-windows-build/package/asar-audit.json)。

Orca809–813页面命令连接关闭、tab list仍正常；新建同源第三页恢复实际操作，没有重启或覆盖用户Orca工作。824使用错误CSS类未找到元素，纠正后825才真正保存，不计前次通过。820截图仍在抽屉过渡，831稳定画面实际查看且620px抽屉与按钮完整。已消费构建/health探针按精确SHA删除，正在使用的GUI驱动和私有认证留到全Goal清理；用户四模型与数据未清除。[已用脚本清理](../refactor-evidence/20261011-root-builder-monitor-helper-cleanup.json)。

## 阶段2来源冻结及真实发布读取：2026-10-12 02:56

[冻结清单](../refactor-evidence/20261012-root-query-source-freeze.json)绑定270份输入和423份实际编译产物。`node --import tsx --test --test-concurrency=2` 的相关domain25文件174/174、runtime15文件33/33；`npm run typecheck`、`npm run build`均退出0；`MARLIN_CORE_OWNER_COMPILED_TEST=1 node --test test/core-owner-compiled.test.ts`实际plain Node入口2/2、skip0、execArgv空；桌面四文件消费者12/12。六条命令日志与source-before/after位于[检查目录](../refactor-evidence/20261012-root-query-final-checks/)。这是相关检查，不声称重新执行前端或完整核心套件。

IPC加密journal与真实强杀/Refresh20/20、相关19/19见[冻结清单](../refactor-evidence/20261012-ipc-receipt-freeze.json)及[实现边界](IPC-RECEIPT-RECOVERY.md)。最初两个夹具错误、产品RED及修复后日志均独立保留。Auth issue到adapter持久journal的早期窗口、协调器确认入队到owner落盘的窗口仍存在，不能从测试推导全链路原子性。

同一隔离目录`/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`正常关闭旧核心并启动新核心PID4110766，来源绑定见[重启证明](../refactor-evidence/20261012-root-query-live-proof.json)。Orca第915步实际点击2.88MB/四万行文档重解析，917/920实际点击Chunk；源文档ID`bbe5614c-3e56-484a-8a8d-edd4cda41b42`、任务`25191127-8f73-40c8-a038-de0436f2bc22`。真实API回应200，Chunk抽屉是否可见尚待核实，不能只凭请求成功算页面通过。

[228条HTTP原始结果](../refactor-evidence/20261012-root-query-publication-live.json)及[阶段分析](../refactor-evidence/20261012-root-query-publication-live-analysis.json)：health144次142成功/2超时，成功6.70–193.87ms；统计41/41为98.38–2570.54ms；正文22/22为775.36–2347.39ms且全文摘要一致；分块21/21为1727.67–2448.61ms、total11429/当前20条。实际任务根23.579秒、publish_local12.806秒；发布阶段读取亦全部成功，GUI自然轮询真实覆盖该阶段，未宣称手动点击命中原生COMMIT时刻。1次health超时早于任务，错误只记录URLError，需要补充原因；不能把两个超时均归因于写入。任务含采样负载，不能直接与之前不同条件样本比較，不计算P95。

**性能验收未通过**：分页每页20条却先读取全部分块及大元数据，真实SQLite只读回归已复现。分页修复和共享attempt真取消实现继续进行；原始日志不覆盖。模型配置摘要保持一致、usage全局101/本验收空间0；采样账户专用设备正常退出并核查已撤销，用户设备及Windows四模型保持完整。前置错误模型表名/pidfd缺失均发生在发信号前，独立保留，不计产品失败。

## 阶段3统一检查：2026-10-12 03:48

[来源清单](../refactor-evidence/20261012-root-cancel-source-freeze.json) SHA256 `120dea90cc8ea26d4f7388589181fe5ea7f12f7f3603ea397a1e6f645d80a77e`，350份输入/435份编译产物。六条命令的输入前后相同；Node22.23.2，业务/任务相关265/265、运行时相关46/46、桌面四文件14/14、plain Node编译入口2/2，失败/取消/skip均0，类型检查和构建退出0。[检查命令与原始日志](../refactor-evidence/20261012-root-cancel-final-checks/)。对应命令时长204.111/213.055/29.861/14.741秒，类型23.583秒、构建23.731秒，不能作为产品延迟。本轮无前端产品修改，不重复计此前338项，临时统一检查脚本已删除。

分页仅读取当前页完整内容；真实HTTP/IPC native INSERT暂停取消、桌面8个caller abort等待真实ACK、无任务认证快照不能取消后续claim、认证顺序及JSON状态保真均有独立原始RED→GREEN，见[实现、审查与限制](DOCUMENT-CANCEL-RUNTIME-IMPLEMENTATION.md)。测试工厂/屏障和初始夹具错误均明确标记，不能用它们代替Orca点击或Windows安装版。当前来源正常重启后大文档性能、Orca业务取消、Windows最新包及剩余页面仍待验收，Goal保持active。

## 阶段3真实运行与分页：2026-10-12 04:26

旧PID4110766在0活动任务时正常SIGTERM退出；当前PID245516的exe/cwd/完整启动参数、350份来源和435份实际编译产物、同一隔离目录及模型摘要见[重启证明](../refactor-evidence/20261012-root-cancel-live-proof.json)。首次停机准备误用不存在的content列，在任何信号前已失败并纠正；不算产品缺陷。04:25再次逐项核对全部350/435摘要未变。没有修改真实用户、四模型或现有设备。

最初[782条观察](../refactor-evidence/20261012-root-cancel-publication-live.json)全部200，但关闭动画尚未执行的抽屉挡住重解析按钮，**没有产生新任务**，只计空闲观察。原生Orca页签未实际选择时，typed tab switch虽成功也没有渲染当前页面；真正点击原生页签后，过渡结束，Chunk抽屉visible/transform0。[当前实际可见截图](../refactor-evidence/20261011-browser-model-page/959-current-source-visible-chunk-screen.png)已查看，未修改CSS或强制动画。

952真实点击重解析，任务95747dfe-2d54-4298-a87a-66ef8c3db8ad完成。根24.048秒、publish_local13.577秒；[168条真实读取](../refactor-evidence/20261012-root-cancel-live-reparse-observation.json)全部200，health110次2.17–99.59ms，统计20次89.13–143.96ms，全文19次248.79–665.36ms，分块19次44.08–163.21ms。实际发布区间内56次全部200，含37次health、6次统计、7次全文、6次分块。全文SHA/2880000字符、11429分块、模型SHA及全局usage101/当前空间0前后一致。[按阶段分析](../refactor-evidence/20261012-root-cancel-live-reparse-analysis.json)。条件为两个HTTP线程、每次独立TCP及Orca自然轮询，不作可靠P95或不同负载前后比较。

分页按钮初次位于抽屉视口外，960点击没有切页，不计通过。963聚焦底部页大小输入使内容滚到底部，967对可见第2页真实点击；[968只读核对](../refactor-evidence/20261011-browser-model-page/968-current-source-page-two-confirmed.json)显示当前页2、第50–52块父上下文及真实?page=2&page_size=50成功88ms。第一次22.6ms/401后正常续期200，保留两请求，不把工具耗时当产品延迟；未保存翻页等剩余行为未执行。

973和984运行快照确有取消按钮，974/985工具报告click，但浏览器没有发cancel-parse请求，任务实际completed，**两轮均不计取消通过**。977/978与[实际截图](../refactor-evidence/20261011-browser-model-page/979-main-table-visible-screen.png)证明850px表格在803px横向容器中，右侧按钮中心被裁切；982聚焦没有滚动，987横向scroll被当前CLI拒绝。两轮287条全部200、289条288成功/1正文409，均无超时；409响应体未捕获，原因待核实。真实完成的重解析合法更换分块/FTS标识，不能从数量一致声称取消回滚。[三轮来源、哈希与分析](../refactor-evidence/20261012-root-cancel-live-rounds-analysis.json)。三轮采样独立验收设备均正常logout并核实撤销；用户设备不变。Windows正式native门禁期间暂停浏览器业务操作，取消键盘验收随后继续；Goal仍active。

随后995先核对键盘焦点为重解析，996实际Enter启动、997实际Tab、998核对焦点为取消，999实际Enter。浏览器[1000请求与页面终态](../refactor-evidence/20261011-browser-model-page/1000-keyboard-cancel-requests-terminal.json)有唯一cancel-parse请求，开始时间20:29:50.0489Z位于实际publish_local区间，200/866.1ms。任务1ee3709f-2e6c-421d-91a2-d84122d4b75a及attempt6 root/publish_local均cancelled，root18.160秒、发布11.202秒，running span0。正文、11429完整分块行、10000 FTS行的哈希前后全部相等，模型及usage不变。[250次观察](../refactor-evidence/20261012-root-cancel-live-cancel-keyboard-observation.json)全部200，health162次最慢121.44ms、统计30次271.19ms、正文29次526.68ms、分块29次97.36ms。单次真实键盘取消不作P95，未冒称鼠标click。[逐项断言与分析](../refactor-evidence/20261012-root-cancel-keyboard-live-analysis.json)。1002/1004实际打开并展开解析记录，最新状态已取消/18.2秒，[稳定截图](../refactor-evidence/20261011-browser-model-page/1006-current-cancel-record-visible-screen.png)已查看。采样专用设备正常退出并核查撤销；observer脚本按最终SHA消费删除，[收据](../refactor-evidence/20261012-root-cancel-live-observer-cleanup.json)。Windows安装版及其他取消时机仍待独立验收。

## 模型CRUD真实页面与Windows新包核对：2026-10-12 05:12

同一隔离browser-qa目录、TypeScript核心PID245516、Orca第6页签及专用空间3，开始时0可见模型。本轮使用自定义OpenAI兼容厂商、默认对话角色、`https://models-qa.example.invalid/v1`与临时合成凭据。全部业务写入经真实Orca表单、可见按钮或Tab/Enter，数据库仅只读后置核对，没有向该地址或真实厂商发送请求。逐步操作、页面结果及原始证据见[模型页面验收记录](MODEL-CRUD-BROWSER-ACCEPTANCE.md)。

| 实际操作 | 结果与证据边界 | 原始后置核对 |
| --- | --- | --- |
| 创建自定义默认对话模型 | 默认与名称落库，页面可见1/已配置1，合成凭据以`enc:v1:`存储 | [创建](../refactor-evidence/20261012-root-model-crud-created.json) |
| 名称编辑、Key留空保存 | 名称持久化，输入不回显，仍显示已配置且有效加密；创建时未记录明文摘要，不能证明创建前后明文逐字相等。重新加密的密文摘要实际不同 | [编辑](../refactor-evidence/20261012-root-model-crud-edited.json) |
| 地址变更、Key留空保存 | 表单不关闭，数据库仍为旧地址；与编辑后基线比较，合成Key明文和密文摘要均未变，随后取消编辑。短暂提示未捕获，不宣称验证文字 | [拒绝保存](../refactor-evidence/20261012-root-model-crud-endpoint-rejected.json) |
| 清Key先取消、再确认 | 键盘取消关闭且Key摘要保持；再次确认后凭据为空、模型保留、配置数0且清Key按钮禁用 | [取消](../refactor-evidence/20261012-root-model-crud-clear-cancelled.json)、[确认](../refactor-evidence/20261012-root-model-crud-cleared.json) |
| 删除先取消、再确认 | 取消后模型仍在；确认后仅临时模型软删，可见数0且凭据已空，不称物理删除 | [取消](../refactor-evidence/20261012-root-model-crud-delete-cancelled.json)、[确认](../refactor-evidence/20261012-root-model-crud-deleted.json) |
| 1289×659高级长表单 | 初始footer在视口外；正常聚焦描述后PageDown实际滚动163px，保存按钮到y520.39。真实点击可见保存使空Key表单保持，随后可见取消关闭；短提示未捕获 | [滚动](../refactor-evidence/20261011-browser-model-page/1098-model-long-form-keyboard-scroll-geometry.json)、[保存点击](../refactor-evidence/20261011-browser-model-page/1100-visible-model-missing-key-save-click.json)、[表单保持](../refactor-evidence/20261011-browser-model-page/1101-visible-model-missing-key-poststate.json)、[取消关闭](../refactor-evidence/20261011-browser-model-page/1103-empty-model-form-cancelled.json) |

原四个真实模型的完整行摘要及`.secrets/credentials.key`哈希每次均与[开始基线](../refactor-evidence/20261012-root-model-crud-before.json)一致；全局model_usage始终101，本轮新增厂商调用0。临时模型已通过界面软删、合成Key已清除，[核对脚本已删除](../refactor-evidence/20261012-root-model-crud-audit-cleanup.json)。视口外点击无业务效果、首次清Key鼠标取消未关闭弹窗等尝试保留，实际生效操作另有页面与数据库结果；未将送达回执、工具等待或未捕获toast当作通过。此轮仅补齐UI-SET-002/003/004的自定义对话模型子项，I-03仍未完成；全部厂商/角色、换地址加新Key、内置模型、思考保存及最终安装版仍待验收。

新正式Windows来源350输入/435仓库编译产物，clean prepare退出0、1640.0424356秒；Windows前端338/338（327780.6498ms）、Core24/24（13936.5534ms）、production Runtime6/6（9915.5091ms），Vite、真实native SQLite/FTS/vec及私有IPC、11解析fixture和阻止Django导入、受控Electron NextAuth均通过。追加随包Node/Python编译Owner原断言2/2，0失败/取消/跳过，9805.7467ms；无开发loader，真实小文档发布经嵌套compiled chunk Worker且0模型用量。命令与fixture时间不能替代实际启动或页面性能，[构建范围](../refactor-evidence/20261012-root-cancel-windows-build/README.md)明确区分受控窗口与手动业务验收。

正式package退出0、858.5982447秒，完整25303文件runtime与10项ASAR白名单审计通过，145份随包core JavaScript与冻结编译来源一致。[产物收据](../refactor-evidence/20261012-root-cancel-windows-build/artifact-receipt.json)记录安装器401834288字节、SHA256 `633a2efe7e8cc1115be94cfc0a675882e4ebb3872a50afb7e62f6a5617c8ad6c`，位于Windows专用`Marlin TS Cancel Worker Installers 20261012`目录；[根代理独立核对](../refactor-evidence/20261012-root-cancel-windows-independent-audit.json)确认37份证据、350来源、435编译与installer摘要全部相符。安装器仍未执行或安装，不能把准备、打包或受控Electron门禁计作J-03和安装后业务GUI通过。

[版本只读审计](../refactor-evidence/20261012-root-cancel-windows-build/version-audit.json)从实际ASAR读得桌面0.6.2，核心package为0.7.0；系统页返回核心0.7.0字面值，通用“版本”标签未区分组件。app.getVersion预期由桌面package决定，但本轮没有启动产品调用该API；未来字面值漂移仍是已记录限制。历史失败、原低分报告及371/388等旧包记录保持原样。Goal仍active；根代理继续专用目录新包安装/升级保留、可见安装版GUI及[矩阵](TEST-MATRIX.md)剩余全页面、生命周期与配置子项，此处不预填成功。

## 正式包实际升级与聊天显示复测：2026-10-12 05:55

阶段3冻结的Windows安装器已在专用`Marlin 安装验收 20261010\应用`执行同版本代码升级。[实际收据](../refactor-evidence/20261012-root-cancel-install-preparation/executed-upgrade.json) SHA256 `6f5d202d3d9ff0771858c41405e9aae4d161cdd7aa6e4b3d28e741221c65e5b8`，state=verified，NSIS bootstrap退出0，owned Job活动进程0、所属完整进程树退出。安装器401834288字节、SHA256 `633a2efe7e8cc1115be94cfc0a675882e4ebb3872a50afb7e62f6a5617c8ad6c`；25378安装文件、25303 runtime文件与350来源/435编译冻结身份完全匹配，实际ASAR一致。306601.077ms是该次安装器执行观察时长，不是产品启动或页面响应。桌面仍0.6.2、核心0.7.0，不称不同版本语义迁移。

12张业务表完整行、90份数据文件和1份凭据材料均精确保留，前后retained SHA同为`bde751bac05fa8c271d8532d21bdd8f1ed72b1de5a1cdd0d556d7eed049551f9`，integrity=ok/FK=0。此安装专用基线是1用户、1知识库、2设备，模型/用量/任务均0，与保留原四模型的可见QA是不同目录。保护的四模型QA进程身份保持，未清除用户数据或重放旧核心；收据明确application_started=false/manual_gui_verified=false、API/paid调用0。安装成功不代替启动、登录恢复、正常退出或安装版业务页面通过，后续实际启动/GUI由根代理继续。

此次安装之后，新增[聊天显示修复](CHAT-SCOPE-TRACE-DISPLAY.md)和核心维护轨迹投影：输入框实际一直提交显式`knowledge_base_ids: []`，零选择提示改为本轮不检索知识库资料，行为不变；检索降级按真实`stage/reason`显示，保留原始代码；维护投影保留`stage/status/state/graph_state/warnings`，`success`仅明确布尔值，否则为null。前端依真实状态或历史显式布尔结果展示，无结果为“未明确结果”，警告和权限状态不包装为完成。`vector_reindex_required`可能来自有意未构建向量的大文档，此显示修复没有自动重建或厂商请求。

| 源码验证 | 实际结果与范围 | 原始证据 |
| --- | --- | --- |
| 真实SFC/Chromium新回归 | 有效产品RED0/4，后定向9/9退出0、9316.166ms；新四项含范围发送载荷和真实轨迹结构，另有既有Chat五项 | [RED](../refactor-evidence/20261012-chat-scope-trace-display/red-components.tap)、[GREEN](../refactor-evidence/20261012-chat-scope-trace-display/green-components-corrected.tap) |
| 完整前端 `npm run test:unit` | 342/342，失败/取消/跳过0，命令93203.489ms；不算Orca或安装版通过 | [原始TAP](../refactor-evidence/20261012-chat-scope-trace-display/full-frontend.tap)、[来源/命令与SHA](../refactor-evidence/20261012-chat-scope-trace-display/freeze.json) |
| 真实SQLite维护轨迹与相关核心 | 两项有效RED0/2，TAP1964.71807ms；相关61/61、失败/取消/跳过0，TAP32799.675399ms，不是全核心或厂商检查 | [RED](../refactor-evidence/20261012-root-maintenance-trajectory/red.tap)、[相关GREEN](../refactor-evidence/20261012-root-maintenance-trajectory/related-green.tap) |
| 核心类型检查与构建 | 根代理对应命令退出0；本次文档更新只读复核两份日志，没有重跑测试或构建 | [typecheck](../refactor-evidence/20261012-root-maintenance-trajectory/typecheck.log)、[build](../refactor-evidence/20261012-root-maintenance-trajectory/build.log) |

首次前端0/4是内存esbuild夹具未处理实际TDesign CSS导入，不算产品RED；首次修改后8/9中的scope超时是夹具误以为发送会关闭选择弹层，改用真实点击textarea关闭后重选，不改产品行为或放宽内容断言。两个失败原始日志均保留在显示设计。只更新旧E2E对应期望，未执行旧Django E2E；两份消费后的前端临时脚本已精确删除。

维护新投影部署前，旧浏览器核心PID245516/startTicks15055703的exe/cwd/全部参数与数据目录精确核查，0活动任务后使用pidfd仅正常停止它，实际确认退出。新核心PID823067/startTicks15745115使用相同目录和参数，health=ok/runtime=typescript。六表完整行SHA前后相等：sessions10、messages22、session_events168、models5、model_usage110、desktop_jobs56；原四模型SHA `d40a1e1151bb95245db98a69ef8bbd3ce046b3544a908eab83e9d9ae7037a137`、凭据材料SHA `1dfc55e984d6f848395d93ac327ce9c6f5fbcfd997bcf89b9fd2d96c9d2238f5`保持，0运行任务。首次停机脚本的Python缺少pidfd_open，在发信号前拒绝，仅为夹具解释器能力问题，原记录保留；随后核实际Linux接口而没有扩大进程范围。[前置](../refactor-evidence/20261012-root-maintenance-trajectory/live-before.json)、[初次环境失败](../refactor-evidence/20261012-root-maintenance-trajectory/live-stop-first-environment-error.json)、[正常退出](../refactor-evidence/20261012-root-maintenance-trajectory/live-stop.json)、[重启后](../refactor-evidence/20261012-root-maintenance-trajectory/live-after.json)。

Orca1172真实刷新、1173恢复已有对话，1174实际点击轨迹，1175快照确认两轮原真实回答继续显示，维护为“记忆检索：未明确结果”“记忆提取：已保存”“图谱状态：无权限”及原`memory_graph_permission_denied`警告、“回合后处理：完成”。两条检索均显示“向量检索：需要重建向量索引（vector_reindex_required）”，没有`[object Object]`或空阶段。该步骤只重新读取已有轨迹，没有重新发送问题、新增模型请求或改写既有低分报告；前述model_usage110来自已消费历史请求，不能把本次零新增解释为整轮聊天零调用。[实际点击](../refactor-evidence/20261011-browser-model-page/1174-maintenance-fixed-open-trace.json)、[真实轨迹结果](../refactor-evidence/20261011-browser-model-page/1175-maintenance-fixed-real-trace.json)。

对话其他真实子项见[完整页面验收记录](CHAT-SCOPE-BROWSER-ACCEPTANCE.md)：从知识库入口取消预选后发送17×19，保存的主任务与维护任务范围均为显式空数组，答案323、零引用且无检索/工具事件；两库选择后发送负责人/预算问题，保存两个ID、答案林青/128000及两条手册引用，来源按钮实际打开手册片段#6。刷新保持四消息与两库选择，置顶后取消回今天；上下文窗口128000、已用估算482、压缩阈值120000，工具过滤及调用时query/top_k Schema实际展开。空范围主任务7.072s，多库主任务29.554s，分别来自真实任务时间，不计首段、全部后台维护完成或P95；真实模型调用为3+4次、1453+4791=6244tokens，只计这两个回合，不代表全局model_usage110的全部来源。

稳定刷新后，实际focus/Enter从序列7条切到时长12.4s，再切时钟29.5s；1169–1171开发HMR期间的未生效第三模式不计通过。修复后真实移除两库、打开弹层显示0已选与“本轮不检索知识库资料”，随后刷新恢复持久两库草稿，不发送新问题。[最终只读核查](../refactor-evidence/20261012-root-chat-scope-fixed-reloaded.json)确认该会话仍4消息/4任务/36事件/7用量、6244tokens，is_pinned=0；原模型和密钥SHA保持。鼠标来源/过滤未生效、早期任务JSON层级错误均按页面验收记录保留，后续正常键盘操作另计。多库答案仅命中标准答案库手册，不能写成跨库联合事实通过；本轮没有新增Embedding/ReRank调用，不计四角色整组通过。

本轮新增前端与核心显示差异尚不在刚升级的正式包中，须最后重新正式绑定、打包并进行安装版复核。以上源码检查、已安装代码保真与浏览器显示证据分别记录，不相互替代；默认未指定范围、快速发送/早停/网络恢复、清空/删除/批量、图片附件、模型切换、长历史、子Agent/记忆开关及其余全页面仍需分别验收。已安装冻结包启动/GUI仍未计通过，Goal保持active，不记完成。

## 集成来源冻结、评测生成复验与环境恢复：2026-10-12

本节纳入07:14后的发布核对及根代理最新Windows准备观察；上文“尚未启动/未执行”为对应旧阶段，不覆盖本节新增子项。只读复核原始证据并更新三份主文档，没有再次运行测试、构建、GUI、模型或进程操作。原H的103文件冻结不修改，旧低分、未知调用与失败收据继续保留。

### 源码修复与检查

原H实际manual生成请求5题，仅第一题保存，第二调用失败，累计2次调用1648 tokens。第二次completion1024、reasoning964；当时没有记录厂商finish_reason，不能将推测的截断写成已观测length。实际编辑、取消删除、单题发布v1、创建v2及确认删除自有v2已有真实UI证据，但发布1题不满足五题RAG前提。[原真实验收及冻结](EVALUATION-BROWSER-ACCEPTANCE.md)。

生成修复按已核厂商端点复用auxiliaryThinking：受支持GLM为on/low、maxTokens4096，DeepSeek使用既有off策略，未知端点保持原1024预算与供应商默认。仅本次辅助调用参数变化，保存的对话思考配置不变。单题仍最多请求一次，失败保留已保存候选及complete已返回的usage；finish_reason只保留受限公开枚举。缺finish_reason/非法message在Runtime envelope校验前失败的既有审计边界未被修复，不能声称所有供应商响应都能记录usage。[设计](EVALUATION-GENERATION-THINKING.md)、[只读审查](EVALUATION-GENERATION-REVIEW.md)。

| 检查 | 实际结果与限制 | 证据 |
| --- | --- | --- |
| 辅助思考专项 | 实际产品RED4/4失败→GREEN4/4，真实SQLite与明确的本地HTTP模型替身；不算厂商请求 | [最终RED](../refactor-evidence/20261012-evaluation-generation-thinking-final-red.tap)、[GREEN](../refactor-evidence/20261012-evaluation-generation-thinking-green.tap) |
| 相关评测/模型与类型构建 | 55/55，失败/跳过/取消0，完整TAP22802.507251ms；根代理core typecheck/build退出0，文档更新未重跑 | [相关TAP](../refactor-evidence/20261012-evaluation-generation-thinking-related.tap)、[检查来源与审查](EVALUATION-GENERATION-REVIEW.md) |
| 前端RAG至少五题门槛 | 专项RED4/4失败→GREEN4/4，Evaluation相关28/28；保留原确定性≥1条件，core仍独立校验当前授权/来源 | [RED](../refactor-evidence/20261012-evaluation-minimum-samples/focused-red.json)、[GREEN](../refactor-evidence/20261012-evaluation-minimum-samples/focused-green.json)、[相关](../refactor-evidence/20261012-evaluation-minimum-samples/evaluation-related-green.json) |
| 最终前端全套与构建 | 347/347，失败/跳过/取消0；命令100279.461ms、TAP99849.293531ms分别记录。构建退出0、44777.204ms，>500kB包体警告保留；不算GUI/安装版 | [最终全套](../refactor-evidence/20261012-evaluation-minimum-samples/frontend-all-case-green.json)、[构建](../refactor-evidence/20261012-evaluation-minimum-samples/frontend-build.json)、[门槛说明](EVALUATION-MINIMUM-SAMPLES.md) |
| desktop smoke readiness | 提取实际生产renderer模板/host表达式，在隔离真实Chromium DOM验证异步空壳；RED6/6失败→GREEN6/6、相关11/11及语法检查退出0 | [RED](../refactor-evidence/20261012-desktop-smoke-readiness/red.tap)、[GREEN](../refactor-evidence/20261012-desktop-smoke-readiness/green.tap)、[相关](../refactor-evidence/20261012-desktop-smoke-readiness/related.tap)、[计时/条件边界](DESKTOP-SMOKE-READINESS.md) |

源码smoke现在要求真实路径对应的可见登录main与可用输入/按钮，或认证后workbench的可见业务main/控件，15秒超时pageReady=false/ok=false。mounted、pageReady和renderer等待分别计时，startup_ms区间为runtime.start前至renderer readiness结果、截屏前；不承诺全部业务接口完成。回归是DOM fixture，未执行真实authGuard或新版Windows应用。

### 修复后的真实生成与门槛

环境恢复后，原v1本页正常access401→refresh200，旧数据集GET200；真实页面显示至少5条有效已批准题的RAG禁用理由、已发布单题不可变/新版本指引，确定性运行按钮仍可用。这只是按钮/指引子项，尚未执行单题确定性运行或下载报告。[本页实际续期与门槛](../refactor-evidence/20261012-evaluation-real-recheck/015-recovered-v1-auth-and-gate-dom.json)。

另一次真实manual/simple/count5点击完成5/5，新草稿`6c630a4d-309d-4dfd-8bac-b31bfdd20bec`包含P1首次响应、交付数量、现行版本、负责人和传感器采购小计五个不同事实，答案分别为15分钟、80套、v3.2/2026-09-30、林青、948元。当前五个不同chunk的Unicode source_start/end、quote、file_hash与source_generation均精确一致，全部pending_review、无validation_errors；这次只读来源核对没有执行审核写入。[生成后的真实页面](../refactor-evidence/20261012-evaluation-real-recheck/025-generated-five-public-dom.json)、[五题与当前来源核对](../refactor-evidence/20261012-evaluation-real-recheck/026-current-source-and-five-review.json)。

新5次真实厂商调用全部success，finish_reason全部stop，prompt674+completion175=849 tokens，reasoning17、cached0；各厂商调用1022/968/1131/1021/790ms，Browser ResourceTiming生成请求5549.8ms、n=1，不能写成P95或未来保证。[真实调用记录](../refactor-evidence/20261012-evaluation-real-recheck/024-generation-second-readonly-observation.json)。07:09来源核对时五题待审核；随后真实UI逐题展开来源、审核发布，07:14后置确认published、5 approved/0 pending；后续一次真实五题Ragas已由根代理按Goal授权，尚未启动，没有新Ragas报告或质量通过结论。[真实发布点击](../refactor-evidence/20261012-evaluation-real-recheck/047-five-reviewed-publish-click.json)、[发布后置](../refactor-evidence/20261012-evaluation-real-recheck/049-after-five-publish-readonly.json)确认五题发布及旧v1/v2、四模型/vault摘要保持；[持续复验说明](EVALUATION-REAL-RECHECK.md)仍在更新，以上状态以本节证据时点为界。

### 分块未保存保护

同一11429块大文档实际编辑后，翻页、关闭抽屉及切类型筛选三种操作均保留当前草稿且阻止切换，未提交保存。Readonly同一事务的前后摘要相等：文档`27e5f1d33e83772642f43bd61942ef76e2547719ffe1d48296514c50593468bf`；完整11429份chunk行`e2d4d82db93d985925cf5c1785d3e9b33044d5c41c67830909d222d03d502235`；10000份FTS行`e5a4b0f41f611e14f7f6f405bd623757db80e1675676b58bc2b4a820bc773166`，数据库测试标记0。未捕获的短toast不计提示验证；刷新仅丢弃本次自有草稿，回login不计会话恢复。服务中断与认证观察单列，不归因于分块写入。保存后翻页及新安装包仍待验。[完整实际操作与限制](CHUNK-UNSAVED-BROWSER-ACCEPTANCE.md)、[前置](../refactor-evidence/20261012-root-chunk-unsaved-before.json)、[后置](../refactor-evidence/20261012-root-chunk-unsaved-after.json)。

### 旧安装版观察与新版构建

旧350来源/435编译安装版hidden smoke截图只有背景，mount3231.9168ms只能证明app挂载，不能记作登录页或工作台pageReady、可交互冷启动。原[hidden failed收据](../refactor-evidence/20261012-root-cancel-installed-launch-preparation/executed-hidden-smoke.json)保持原状态；后续[独立只读核对](../refactor-evidence/20261012-installed-postvalidation-review/executed-postvalidation-continuation.json)明确mount_only=true/page_ready_not_verified，未重放hidden，无法还原当时existing_installed_application_refused的确切原因。

根代理随后对同一旧安装版PID27784进行了真实文件picker打开/取消、1440×900与1024×768、最小化/恢复及标题栏关闭。关闭后窗口hidden但process_present=true；这些仅是旧包窗口与选择取消子项，没有实际上传、完整托盘退出或所属Job全0结论。尺寸观察DPI96，不计125/150%或中文IME通过。[原生证据目录](../refactor-evidence/20261012-installed-postvalidation-review/)、[1440](../refactor-evidence/20261012-installed-postvalidation-review/window-1440.json)、[1024](../refactor-evidence/20261012-installed-postvalidation-review/window-1024.json)、[最小化](../refactor-evidence/20261012-installed-postvalidation-review/window-minimized.json)、[恢复](../refactor-evidence/20261012-installed-postvalidation-review/window-restored.json)、[关闭后仍运行](../refactor-evidence/20261012-installed-postvalidation-review/window-closed.json)。原受保护四模型QA25268是另一进程/数据目录，不能合并为本次已安装数据或全生命周期通过。

最新[集成冻结](../refactor-evidence/20261012-integrated-readiness-generation-source-freeze.json) SHA256 `04384889060e32a1249c151c83ea04ee1a772a02f4799b831ab976ac87c9b6fc`，451份builder实际来源输入、5份额外测试、520份本地编译产物。Windows正式prepare session34203在途；根代理已读取该Windows日志前端347/347、失败/跳过/取消0、TAP389141.8721ms，之后仍在Vite生产构建，不能算prepare整体退出0。源已审runner SHA256 `9ce1ccc3f41dd6b28a132cda61c33be5deffb662785fcf4eafdeea036f97a0ef`；[准备命令](../refactor-evidence/20261012-integrated-readiness-generation-windows-build/prepare-attempt.json)记录`--refresh --prepare-only`和当前精确来源，不预填成功。尚未完成新准备/NSIS、产物审计、安装及新版smoke/GUI生命周期；旧633a2efe…安装器属于此前350/435身份，不能当最新包。桌面0.6.2与core0.7.0继续区分组件。

### 浏览器核心服务中断与恢复

旧PID1064192/session55312在`2026-10-11T22:45:26.930Z`记录application.stopping后exit0，8000无监听，page6经Vite代理载入数据集GET500。停止原因尚未查明，不能称认证权限缺陷、自然会话失效或分块保护引起。本代理没有终止该PID/session的操作，本轮文档维护没有操作任何进程。根代理同配置恢复PID1171965/startTicks16194111/session8225，health=ok/runtime=typescript。[恢复前](../refactor-evidence/20261012-browser-core-recovery/before.json)、[恢复后](../refactor-evidence/20261012-browser-core-recovery/after.json)。

恢复前后7表完整行数量/SHA相同：sessions10、messages22、session_events168、models5、model_usage112、desktop_jobs56、generic_resources11；无活动任务，原四模型及vault摘要保持。恢复后的三个受核来源/编译SHA保持：generation.ts `3aadf4d0ca222d188862c88f953d8a52bcc1044102fae504d9e774b7990a01a2`、usage-audit.ts `e17bb906dfda38817a8788aa0def9049b7ef185a6c0888693d52d26108422f2a`、编译generation.js `8eb01572c0045e9501da96ca8df6350609c4962097e00e95c0bb0da88bac6184`。随后本页正常refresh200/GET200是独立真实子项，不解释根页1246的具体login跳转，也不计跨页签/跨设备全部认证通过。恢复没有模型重放，之后授权的新五题生成消费单独记录。

Goal仍未完成。已发布新五题的Ragas/历史/实际报告下载及质量、最新Windows正式产物/安装生命周期和矩阵其他页面子项等待完成；任何源码回归、旧包窗口操作或单次请求时长均不替代这些终态。

## 旧来源准备终态与仅分块422：2026-10-12新checkpoint

本节补充以上当时“prepare在途/确定性尚未执行”的后续结果。本次仅维护三份主文档及独立checkpoint，不改专项源码/说明或原证据，不运行GUI、API、模型、Windows进程、测试或构建。[逐组A–J依赖审计](../refactor-evidence/20261012-main-docs-post-prepare-checkpoint/PENDING-A-J.md)及本checkpoint来源/SHA记录另行冻结。

旧集成freeze SHA256 `04384889060e32a1249c151c83ea04ee1a772a02f4799b831ab976ac87c9b6fc`的Windows正式`--refresh --prepare-only`已exit0；实际结束`2026-10-11T23:23:23.225697Z`，命令1019.1703614秒、ownedProcessTreeClosed=true。Windows前端347/347，失败/跳过/取消0，TAP389141.8721ms；Vite生产build41.74秒，正式native gates均OK。prepare.log实际92652字节、SHA256 `e761521101b066e8f7cf4dae100807855fb04ab672c2acf73ddeeb60e0be2ac9`。[执行收据](../refactor-evidence/20261012-integrated-readiness-generation-windows-build/prepare-execution.json)绑定451实际来源+5额外测试，installerExecuted=false/manualGUI=false。此prepare早于下述两处修复，根代理明确不执行旧freeze package；不能将它称最新NSIS、最新安装或修复后Windows通过。

真实Orca原已发布单题v1按主recursive、无比较、keyword、Rerank=false核表单后只点击一次“仅分块”，POST422 `Persisted image barrier indices are invalid`，没有报告成功。[实际设置](../refactor-evidence/20261012-evaluation-real-recheck/060-free-chunking-exact-config-dom.json)、[唯一点击](../refactor-evidence/20261012-evaluation-real-recheck/061-original-v1-only-chunking-unique-click.json)、[实际结果](../refactor-evidence/20261012-evaluation-real-recheck/062-original-v1-only-chunking-result-dom.json)、[后置只读](../refactor-evidence/20261012-evaluation-real-recheck/063-after-zero-provider-only-chunking-readonly.json)确认0新增厂商用量、四模型/vault及旧v1/v2保持。该失败不归于供应商、权限或旧core服务中断，唯一正式五题Ragas尚未启动。

实际PNG持久化canonical空、parser_blocks空，合法parser_image_block_indices=[0]；`parsedSource`旧fallback伪造空text0，与真实image0碰撞。最小修复保留空text集合、实际图片barrier和full corpus，原非空legacy fallback保留；重复/负数/非整数/text碰撞索引仍拒绝。另空semantic保留配置校验及取消检查，在空/空白canonical时直接0块、selected/requested仍semantic，诊断`semantic_embedding_skipped=empty_text_source`，不dispatch空embedding callback、不误报missing callable或假降级。实际ModelRuntime空数组原本返回0usage、无厂商请求；不能把新回归说成供应商拒空或已发生付费失败。[真实字段](../refactor-evidence/20261012-evaluation-real-recheck/065-actual-parser-image-barriers-readonly.json)、[完整设计与RED](EVALUATION-IMAGE-ONLY-SOURCE.md)。

| 检查时点 | 实际结果 | 限制/证据 |
| --- | --- | --- |
| image-only中间修复 | 专项5/5，2654.519ms；当时相关50/50、195471.534ms及typecheck退出0 | 使用原chunker6407f25e…，不覆盖随后空semantic；[中间专项](../refactor-evidence/20261012-evaluation-image-only-source/focused-green.json)、[当时相关](../refactor-evidence/20261012-evaluation-image-only-source/related-evaluation-green.json) |
| 加空semantic后的专项 | 实际RED5PASS/3FAIL、3790.258ms→8/8 GREEN、3795.620ms，0厂商/GUI请求，前后3源码SHA相同 | 真实隔离SQLite/corpus及明确vectors callback；不是live或Windows重验。[RED](../refactor-evidence/20261012-evaluation-image-only-source/semantic-red.json)、[GREEN](../refactor-evidence/20261012-evaluation-image-only-source/semantic-green.json) |
| 新源码类型 | 末次读取final-typecheck.json已exit0，18946.272ms，23:36:32.868063Z结束；绑定isolated c09ea054…、chunker0b127317…、测试66d05ded… | [实际命令收据](../refactor-evidence/20261012-evaluation-image-only-source/final-typecheck.json)，本代理未重跑 |
| 最终专项相关/构建/独立冻结 | 最终相关39/39、失败/跳过/取消0，命令194402.871ms/TAP194329.937681ms；Linux build退出0/21124.519ms，3来源/6编译文件独立冻结d219145e… | [最终相关](../refactor-evidence/20261012-evaluation-image-only-source/final-related-evaluation-green.json)、[源码/构建冻结](../refactor-evidence/20261012-evaluation-image-only-source/freeze.json)；不是root全项目新freeze、live免费重验或Windows验收 |

新版固定安装/启动harness已被根代理完整读并认可，默认review_only，Linux无执行guards24/24；实际新source freeze、成功prepare/package/ASAR和installer大小/SHA尚未绑定。[准备清单及精确命令](../refactor-evidence/20261012-integrated-install-preparation/README.md)不等于已安装。根代理先真实开菜单/打开27784知识库并核画面，title-close转后台，再fresh右键核菜单owner=27784并点击退出。原session8022退出1，visible收据failed_manual_review_required/owned_bootstrap_not_reaped；原run在JobAccounting.active0后只等bootstrap5000ms，不记具体WAIT_TIMEOUT或WAIT_FAILED，未知原因保留。后来独立同代次Win32 audit已证实该bootstrap退出0及窗口已无，不能把原failed改成verified。本次没有打开或结束任何窗口/进程。

安装前必须等旧应用正常托盘退出，再采当前完整数据文件+12表+key固定基线；旧90文件摘要在旧visible运行前采集，profile/日志可能正常变化，不强求它仍逐字相同，也不因此跳过当前全文件保留核验。独立audit的12表仅device_sessions摘要变化，其他11表与旧before一致、current94files及key摘要保持；旧27784退出证明不等于12表/旧90文件逐字相同，也不覆盖新包。新upgrade/pageReady截图、可见业务、有界收尾守卫/正常退出/崩溃恢复与卸载保留均待最终来源包执行。Neo4j真实连通仍缺条件，Langfuse/联网/MCP等按实际配置/服务及GUI分别补证；其余可用核心GUI按依赖审计继续，Goal未完成。

原[visible failed收据](../refactor-evidence/20261012-installed-postvalidation-review/executed-visible-retained.json) SHA256 `eed36cf93ab86d5cb104c3887941b9ed259108136a3dba4daa7e92a42cfd0285`保持；[独立退出核对](../refactor-evidence/20261012-installed-postvalidation-review/exit-exact-readonly-audit.json) SHA256 `1aa9f47d71acf6e3186143f003b8fe5ad338e09a969d5359ba0c1414774db0c3`使用QUERY_LIMITED|SYNCHRONIZE同handle先Wait0=0、ExitCode0、FILETIME134362309196213069匹配，10553918窗口无。终止对象QueryFullImageName失败31是在已证实signaled/代次之后，不凭路径查询失败推断退出；保护25268同FILETIME134361236166333286、Wait258/ExitCode259/原路径仍活。deny-write DB锁、零WAL、integrity/FK通过；仅device_sessions变化、其他11表等于旧before，94份当前文件、key保持，all_business_tables_unchanged=false。新harness复用的5秒bootstrap等待也需根已授权的30秒有界只读收尾：同handle signaled+ExitCode0+JobActive0全部必需，WAIT_FAILED立即捕lastError拒绝，不广泛kill；本checkpoint未修改或实际运行harness，不将额外timeout写成产品性能优化。

根后续已保存[全项目新freeze](../refactor-evidence/20261012-integrated-image-readiness-source-freeze.json)，SHA256 `85b54e940a951c2d2f8a3dfa5d2267445ac8599e073c713dabe81299e0395c88`，452输入/5额外测试/520本地产物；这与d219…专项3来源/6编译不同。根通报精确pidfd退出原1171965用300.561ms，新live1368229/startTicks16454258同目录16表完整行跨restart均等，源/dist绑定专项最终冻结。新独立Windows prepare目录20261012-integrated-image-readiness-windows-build待根运行，暂无成功prepare/package/installer身份。本checkpoint没有启动live、GUI、模型或Windows，未收到免费重验/唯一五题Ragas评分终态；以下交接继续按待执行清单，不预填成功。

## 中文召回、唯一五题Ragas与Clock冻结：2026-10-12新checkpoint

本节补充前述历史“未启动/待重验”，仅文档归纳，未重复GUI/模型/构建或进程操作；Clock测试的实际执行另有独立原始证据。

中文整句FTS零召回已按Unicode三字重叠terms修复，搜索/元信息/确定性BM25基线共享解析，SQL scope/有效状态仍在LIMIT前，英文与短literal LIKE保留。真实SQLite RED6/6失败→GREEN6/6；相关首次102/103唯一旧扩展路径断言失败保留，修改仅chat fixture为真实no-hit seed后该组9/9，余94来自同未变产品摘要；类型/构建退出0。根代理已正常接入同目录核心PID1464221/startTicks16570927，16表跨restart/四模型/key摘要相同。[修复与原始检查](RETRIEVAL-CHINESE-QUERY.md)、[独立只读审查](RETRIEVAL-CHINESE-QUERY-REVIEW.md)。原v1仅分块200/471.5ms、新五题仅检索200/586.3ms，各Hit/MRR/Recall=1、0新增厂商调用，均实际历史下载并打开新报告；stored effective策略不误称重分块，新五题source overlap precision均值.6067，不宣称所有候选精准。[真实召回与文件](EVALUATION-CHINESE-QUERY-BROWSER.md)。

唯一新的真实五题Ragas已completed/5题/coverage1，run `9a8de0eb-a2bf-48cc-8883-7474b1cd037d`，164.721秒（n=1，后台Windows构建并行）；45调用全部成功，Answer5/Judge30/Embedding10、39505tokens，0unknown/failed/retry/resume。Faithfulness=1、Answer Relevancy=.9472539593197356、Context Precision=.9999999999；Context Recall/Answer Correctness=null/未运行。真实历史下载并打开8275字节报告，SHA256 `2d94a554c2f9ae468c1dc853a4e14140c5aafc52de985547d1dd5d7778b8e0c2`，5样本、配置/来源/45用量准确；正常refresh后报告GET200，不重跑评分。删除只取消、报告SHA保持，原2库/gold2文档13块/13Wiki/3评估集/4模型/key均不变。报告不含逐题厂商Answer文本/独立Ragas分布，不能说逐条人工审核了回答或外推整体质量/P95；原H1/5失败、旧低分与未知账本保持，其他H/正式安装版仍未完成。[真实页面、账本与文件](EVALUATION-CHINESE-QUERY-BROWSER.md)。

当前最新[集成freeze](../refactor-evidence/20261012-integrated-poll-clock-source-freeze.json) SHA256 `46a4ad77664f71d593f6f53a7504ed95e1651c8a806ec80fe5b16af66112007e`，454构建输入/5额外测试/523编译文件。与39feca…相比只改解析记录轮询测试，产品/依赖/编译产物不变。旧39f Windows clean prepare真实346/347、exit1、845.318秒，一项Node2100ms等待断言失败；原失败不覆盖。旧Windows单文件隔离诊断5/5、49.075秒不抹全套失败。测试改用官方Clock、1999/1ms边界、真实response barrier及终态6000ms无新增reads；相关5/5、TAP6084.821ms，原所有行为断言保留。根代理新prepare session41187正在同Chinese Query Final Build目录由正式builder全清staging、重新npm ci与完整前端检查，没有复用失败payload；截至本checkpoint没有新prepare成功收据、package/installer或最新安装版通过。[测试设计与RED/GREEN](PROCESSING-RECORDS-POLLING-TEST.md)、[旧失败收据](../refactor-evidence/20261012-integrated-chinese-query-windows-build/prepare-execution.json)、[旧单文件对照](../refactor-evidence/20261012-processing-poll-windows-diagnostic/execution.json)、[新准备命令](../refactor-evidence/20261012-integrated-poll-clock-windows-build/prepare-attempt.json)。

安装/启动harness收尾已修并根全读，主SHA `6926f38880facafb627f417af36e54ab7a7c333b4718a129f5706d1ebc37bfbf`，固定Chinese Query Final Build路径、review_only/未绑定产物；30秒同handle reap必须signaled+ExitCode0+Jobactive0，WAIT_FAILED立即抓lastError拒绝。实际Linux单位12/12、非执行guards24/24、受限AST2/2保留原ownership/cleanup，不能当Windows退出通过。旧27784 failed收据及独立同代次退出证明不变，当前baseline须重采完整文件/12表/key，不混用旧90/current94files。[新审阅资料](../refactor-evidence/20261012-integrated-install-preparation/reap-revision/README.md)。D02/H安装版可复用浏览器QA的独立离线backup/restore副本计划，但尚未复制/恢复或验证原登录口令；不能注入token或改admin密码，也不能用旧空retained DATA冒充资料与报告已在安装版。[只读副本计划](OFFLINE-INSTALLED-QA-CLONE-PLAN.md)。

旧85b refresh在主动CJK源码变化后source gate拒绝，exit1/658.335秒，部分payload已改变而旧manifest仍043848，不能重写manifest或声称可复用。随后39f使用新的empty Chinese Query Final Build目录完整prepare，最终346/347失败/845.318秒、ownedProcessTreeClosed=true，log88560字节/SHA a6dc272a60feb17ae56fcc3b62b994a12399572cfd951066b323fb8cac9d337f。新46a只改此测试，正式builder在自己的stage全清reset后重新npm ci与全347，不把旧单文件5/5或Linux新5/5当新Windows全套通过。当前尚无新安装器SHA可填。[85b原失败](../refactor-evidence/20261012-integrated-image-readiness-windows-build/prepare-execution.json)、[39f原失败](../refactor-evidence/20261012-integrated-chinese-query-windows-build/prepare-execution.json)。

Goal仍active：该小样本评测不填满H，也不替代其他核心页面、来源修改/删除/隔离标准题、外部服务、正式IPC和新版Windows完整生命周期及最终数据/临时材料清理。本checkpoint链接/差异和文档SHA见[验证](../refactor-evidence/20261012-main-docs-chinese-poll-checkpoint/validation.json)。

## 搜索设置、真实MCP与最终核心检查：2026-10-12新checkpoint

本节只归纳实际源码检查/GUI证据和Root终态通报，维护三份主文档及独立验证，不再执行GUI、API、厂商、Windows或进程操作。上述旧46a“prepare在途”现有失败终态；新的cf2a构建也因真实WebSearch显示缺陷中止，不预填当前交付。原38组和A–J的未验条件仍保留，H旧冻结/低分/unknown/原1/5失败不变。

| 这轮检查 | 实际结果及范围 | 证据 |
| --- | --- | --- |
| 搜索Provider与MCP前端 | 真实编译父/子组件与API的缺入口及安全DTO回传先RED0/2；最终相关28/28，全套360/360、0fail/skip/cancel、TAP114486.299607ms；Vite build退出0/41.87秒 | [设计与失败历史](WEB-SEARCH-PROVIDER-UI.md)、[来源及原日志冻结](../refactor-evidence/20261012-web-search-provider-ui-implementation/freeze.json)。既有包体警告保持，不计页面P95。 |
| 核心有效端点护密 | 原`base_url`-only带Key服务添加另一host的`url`且留空Key实际能保存，受控SQLite probe确认缺陷；同一实际生效端点校验后RED8/10→GREEN10/10、相关106/106 | [probe](../refactor-evidence/20261012-web-search-endpoint-alias-probe/execution.json)、[最终相关及typecheck/build](../refactor-evidence/20261012-web-search-core/alias-verification.json)。原typecheck退出2与最小类型修正后退出0均保存；无真实数据/厂商。 |
| 核心完整suite | 109文件、695项=693PASS/0FAIL/2条件SKIP，命令700.755615秒，source/dist前后相同。正常Django兼容测试解释器与独立parser解释器分开，不把无Django的parser目录prepend到所有测试PATH | [完整终态](../refactor-evidence/20261012-web-search-alias-final-core-checks/full-execution.json)。这条命令不能写成695/695或零skip。 |
| compiled Owner补验 | 真实plain Node/无tsx入口2/2，0fail/skip，16.380500秒，同source/dist身份 | [独立终态](../refactor-evidence/20261012-web-search-alias-final-core-checks/compiled-execution.json)。不以Linux补验代替Windows加载。 |

旧108文件685项中的3fail完整保留；两项compiled误以tsx同时开启opt-in由plain Node补验，旧Unicode编辑zero期望命中了保留的文档标题，Root只修fixture标题并增加编辑前召回/原始FTS内容断言，不改查询产品语义。后续109文件692项的688pass/2fail/2skip也保留：密码兼容测试使用了无Django的parser环境，另300ms真实HTTP夹具前置有调度竞态；Root分离实际解释器并使用受控timer/真实请求barrier，原业务取消与300ms期限断言保留。最终695/693/0/2是修正后新的实际命令，不覆盖旧失败。[原108命令](../refactor-evidence/20261012-final-core-suite/core-suite.log)、[原109终态](../refactor-evidence/20261012-web-search-final-core-checks/full-execution.json)。

真实MCP修复续验通过原服务留空Key改名称、禁用/启用；随后唯一Agent回合实际initialize、tools/list与tools/call，工具12×79=948，持久化与最终回答包含新回执`62243c11-8d31-4df1-b4ff-9f411d5635ba:2`。setup`:1`只作服务自检。4条成功model_usage（不是评测invocation ledger）共3353tokens，usage162→166；chat.turn与maintenance各attempt1/completed，0active，远程图谱权限warning仍可见。主任务18.737秒、tool70ms，维护4.675秒与主任务尾部有27ms重叠；仅单样本、全套/构建并行，不相加作独占墙钟或P95。原MCP编辑400/316.2ms保留。实际删除先取消保持全行SHA，再确认仅自有服务软删；原2库、gold2文档/13块、13Wiki、3数据集、4模型及vault SHA相同。最终152份browser证据、49检查和30链接已冻结，4个消费临时脚本已归档删除；Root精确SDK pidfd SIGTERM及server close/exit确认，不触碰应用进程。[实际页面及协议/账本](MCP-REAL-AGENT-BROWSER.md)、[browser冻结](../refactor-evidence/20261012-mcp-real-agent/browser/freeze.json)、[SDK终态](../refactor-evidence/20261012-mcp-real-agent/server-stop.json)。本轮不覆盖禁用后Agent零调用、任意外部MCP、正式安装IPC或联网搜索Agent。

WebSearch真实GUI仍未终态：自有SearXNG的创建、合成Key留空编辑名称/同host URL、测试2结果、503错误、清Key取消exact→确认→合成Key恢复已有记录。另一次匿名公共DuckDuckGo测试200/5结果/1387.3ms是实际搜索适配器请求，不是GLM调用或Agent引用成功；global KV原NULL、usage166，付费Agent/global保存待修复后继续。[实际公共结果](../refactor-evidence/20261012-web-search-real-browser/browser/074-ddg-public-test-network-dom.json)。保存新URL后仍显示原测试成功/失败，[027实际DOM](../refactor-evidence/20261012-web-search-real-browser/browser/027-search-failure-config-snapshot.json)与[037恢复URL后card](../refactor-evidence/20261012-web-search-real-browser/browser/037-search-url-restored-card.json)证明显示缓存未失效的新缺陷。Root最小产品修复只在成功保存后失效该Provider测试结果，SEARCH-UI-12真实组件RED1失败（旧结果1!=0）→GREEN1/1，保留无自动测试及另一Provider结果的断言。[实际RED](../refactor-evidence/20261012-web-search-result-invalidation/red.tap)、[GREEN](../refactor-evidence/20261012-web-search-result-invalidation/green.tap)。实际相关29/29、命令51.053270秒/TAP50971.591828ms；新完整361/361、0fail/skip/cancel、命令115.302290秒/TAP114782.407608ms，4源码前后同SHA，修复child为c1560c1d…、测试5632f2fa…；生产build已退出0，命令44.427519秒、Vite44.81秒分别记录，包体>500kB警告仍在；原URL变化P2已真实Orca五断言全部通过、0新增模型/原保护exact，受控HTTP200/503/200与应用200/502/200对应；global KV仍NULL，Agent搜索与完整GUI全组及正式包仍未完成。[实际P2复验](../refactor-evidence/20261012-web-search-real-browser/browser/113-p2-actual-browser-regression-and-server-snapshot.json)、[专项说明](WEB-SEARCH-CONNECTION-RESULT.md)。[相关](../refactor-evidence/20261012-web-search-result-invalidation/related-execution.json)、[完整](../refactor-evidence/20261012-web-search-result-invalidation/full-execution.json)、[生产build](../refactor-evidence/20261012-web-search-result-invalidation/build-execution.json)。原360检查只属于修复前来源。

Root已于01:50正常接入同一browser-qa核心PID1920563/startTicks17169521，health真实TS；16张受核表完整行SHA、四模型/key、usage166跨restart相同。[重启后置](../refactor-evidence/20261012-web-search-live-transition/after.json)。这不能解释此前1064192停止原因，也不是静态离线源；此文档维护没有进程操作。

cf2a[集成freeze](../refactor-evidence/20261012-web-search-integrated-source-freeze.json) SHA256 `cf2a6b7a9b4d3b011d3b94e35c8ab421eb926cf8188aca46b1b126393ef4daec`绑定457输入/5额外测试/523本地产物，保留上述当时检查。正确构建host`C:\Python313\python.exe`具有pip；01:53:49UTC新的完整prepare启动，不复用旧失败payload。[attempt](../refactor-evidence/20261012-web-search-integrated-windows-build/prepare-attempt.json)。随后因新P2，Root请求精确owned child26724 exit125，wrapper77001实际exit1；[正式失败receipt](../refactor-evidence/20261012-web-search-integrated-windows-build/prepare-execution.json)为exitCode=null/errorType=RuntimeError、1131.285707秒、02:12:40UTC终态，log SHA `3949734c8f6daf2fe303fbe56a951f3d5bed94036258b623fccce46a3b4e6951`。Retained-handle cleanup5秒超时，不能写child终态125或ownedProcessTreeClosed=true；Job finally KILL_ON_CLOSE已执行，stage写者是否全退仍待Root独立只读核验。同一prepare.log在取消前已有7个Windows新Web/MCP单测失败（349–354、356），不是取消造成；尚未输出完整360统计，不能写Windows360通过或只有取消失败。后续实际Windows诊断已证实原esbuild importer为反斜杠、matched=false，真实client GET csrf但零POST test。[原诊断](../refactor-evidence/20261012-web-search-result-invalidation/windows-fixture-red-execution.json)exit1/49.400660秒，owned tree已退出；仅fixture改用fileURLToPath生成的实际本机API路径精确比较，生产认证链未改。实际Windows单文件14/14、0fail/skip/cancel，命令130.517703秒/TAP129958.156ms、source不变、owned tree已退出，仍不是旧整个360全套或新prepare通过。[新诊断终态](../refactor-evidence/20261012-web-search-result-invalidation/windows-fixture-green-execution.json)。没有最新版package、installer、安装或pageReady通过事实。

旧46a[prepare终态](../refactor-evidence/20261012-integrated-poll-clock-windows-build/prepare-execution.json)实际exit1/1085.572985秒、owned tree closed；前端347/347、Vite/Core build通过后，Root误用缺pip的安装版Python作build host而失败，属于构建环境问题，原log SHA bc38af1d…和receipt不改写。39f346/347调度失败、官方Clock5/5、旧043848 prepare成功及350/435安装史继续分开，不用它们代替cf2a之后的新正式交付。

最新[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json) SHA256 `5cabb11adcff22acf3c02f6cb70dce381acc3b19597d662ac95c6e2d471a7bac`，457输入/5额外测试/523编译，4份必需终态绑定；core5cc596…未变，前端新freeze5b7b27f8…。新正式prepare session10779已于02:28:55UTC启动，使用全新`Marlin TS Search Result Final Build 20261012`及独立`Marlin TS Search Result Installers 20261012`，不复用cf2a失败stage。当前仅有[实际attempt](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-attempt.json)，尚无prepare成功、package/installer或新版安装事实，Goal仍active。

离线D02/H安装复核已有[新harness准备](OFFLINE-CLONE-HARNESS.md)：13/13仅临时假数据、默认review_only、主脚本8876ff…保留待Root全读。Native readonly backup会创建原目录WAL/SHM的真实假数据探针已保留，因此改为原目录只读字节复制→owned raw/snapshot原生与正式备份，普通文件SHA/嵌套库逻辑摘要/密钥解密/FTS/60bit均回归。真实源尚未读取/复制，必须新正常停机和全目录无侧文件清单绑定；Windows restore、正常口令登录与安装版D02/H仍未验，不注入token或改admin哈希。6926安装/启动harness仍为已审准备，旧failed receipt不改写。Goal保持active，最新Windows链路、A–J剩余子项、外部条件、最终临时材料与数据清理待完成。[本checkpoint验证](../refactor-evidence/20261012-main-docs-web-search-mcp-checkpoint/validation.json)。

## WebSearch真实终态、离线导出与Windows prepare：2026-10-12此前checkpoint

这是只维护主文档的增量，前一[846 checkpoint](../refactor-evidence/20261012-main-docs-web-search-mcp-checkpoint/freeze.json)保持原字节；不执行GUI/资料读取/进程/厂商调用。以下最新事实覆盖此前相应“仍在途/未导出”的待办，历史观察不改写。

联网搜索真实续验已经终态：自有SearXNG的CRUD/空Key保留/清Key取消确认、默认选择、off/on保存刷新和SEARCH-UI-12新旧结果失效均有真实Orca步骤。唯一GLM回合实际一次web_search返回2来源、35ms，答案37天与哈希/关联记录要求正确；4成功模型调用3846tokens，主任务17.913秒、维护5.660秒（有27ms重叠，不能相加/P95），usage166→170/两任务completed/0active。两条答案链接分别实际打开200/142.9ms与200/167.9ms。另匿名公共DuckDuckGo单次连接200/5结果/1387.3ms只算连接，不是公网Agent质量。四模型/key/gold/Wiki/评估/MCP保护SHA相同，自有两服务取消删除后仅各自确认soft-delete。原P2与工具误点回执保留；禁用后Agent零HTTP、Google/Bing、任意外部服务、正式Windows搜索IPC仍未验。[真实完整续验](WEB-SEARCH-REAL-AGENT-BROWSER.md)、[219份browser证据](../refactor-evidence/20261012-web-search-real-browser/browser/freeze.json)。

GUI最后确实保存off/空默认，raw值为`{"enabled":false,"provider_id":""}`，并非原NULL；随后Root在精确owner正常退出、活动/待确认IPC为零、无未知写者的离线窗口，只对tenant2.web_search_config做精确CAS恢复原NULL。其他tenant字段/受核业务表不变，维护不计GUI reset通过。[实际正常停机及维护](../refactor-evidence/20261012-offline-source-stop/stop-receipt.json)、[冻结后只读补记](../refactor-evidence/20261012-web-search-real-browser/browser/maintenance-followup.json)。此前PID1920563重启不变的证据仍是历史时点；后续实际导出以停机回执为准，不把live目录当静态备份。

Root实际Linux离线导出已exit0：72表、26backup文件、24相对媒体引用、0外部引用，原source完整目录/文件保持，Root再次逐项核26文件。停机时原27文件/62目录/197530706字节与22908chunks是来源基线，不是Windows复制或完整Chromium profile镜像。export-result SHA `ed33ffc2…`；offline-clone-manifest SHA `2ec148969a1274d3ef7ebfb1c1ce1f577758b1592bbe88f4e6cb07de8e845a87`，backup-manifest SHA `23b4b109f54145b483699a76b73b40376e38fee02cc44db13f7d2c6de4acb913`，二者不能混用。8876脚本已按原SHA归档并精确消费删除，原native readonly侧文件失败探针保留。[实际完成回执](../refactor-evidence/20261012-offline-source-stop/export-execution.json)、[结果](../refactor-evidence/20261012-offline-source-stop/export-result.json)、[消费清理](../refactor-evidence/20261012-offline-source-stop/consumed-script-cleanup.json)。Windows restore、原口令正常登录、D02/H IPC仍未执行。

最新[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)仍为SHA256 `5cabb11adcff22acf3c02f6cb70dce381acc3b19597d662ac95c6e2d471a7bac`，457输入/5额外测试/523编译，core5cc596…/前端5b7b27f8…未变。全新Search Result Final Build的正式prepare session10779已真实exit0、owned tree closed，1806.243694秒，结束02:59:01.514429 UTC；Windows完整前端361/361及正式生产/native门禁通过，prepare receipt SHA `38613d5d78244762b54d4c3b097597ddca3576f4624ae4210dc5c38999abdb0d`。[实际prepare终态](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-execution.json)。随后正式package session79579已真实exit0、owned tree closed，824.2763883秒，结束03:16:15.320527 UTC；[实际package终态](../refactor-evidence/20261012-web-search-result-integrated-windows-build/package-execution.json)SHA `0b0b9a41a780009da7195291814418a9422aecd9f95820437cf876d0eabbd838`，[ASAR审计](../refactor-evidence/20261012-web-search-result-integrated-windows-build/asar-audit.json)SHA `0fc8849d955fdf6e8d74695e1e9f87c9c01ae9e8ff1e788ae5e307b79cb6f31f`。Root提供实际installer401841299字节/SHA `99baabeeb82dd4af6312356810a91d0a2b51ec1c62726a8de3d917305fe5a8f6`，位于独立Search Result Installers。artifact绑定session59599尚在进行，最新升级、pageReady/GUI生命周期未执行；构建和installer产出不算正式安装通过。旧cf2a中止、7项Windowsfixture失败、39f346/347与46a缺pip失败全部保留，Goal active。

独立Windows restore/launcher已完成review_only准备：主脚本SHA `d79d502ba816332fde4323cbeb2e963cee731870d00c3fc5e6987bf29855860e`，18文件冻结SHA `1aab0f0f1f80df09af52716b3f8029bade6764f4778ed7cd530f5fae8a5b9310`；Python18项假文件/Fake SDK守卫、Node6项纯函数、语法/default检查均通过，15links0bad。这些无实际Windows SDK/复制/restore/GUI/付费调用，不作为安装验收。正式restore保持完整72表合同/2400秒有界Job；visible-clone仅绑定未来实际installer/upgrade后执行，7200秒持有/每5秒进度、同handle30秒reap，保护25268原代次。Node附加审计不重复hydrate全vec shadow，完整shadow摘要仍由正式restore验证；未知原口令不注入token/改密码。[已冻执行准备](OFFLINE-WINDOWS-RESTORE-LAUNCH-HARNESS.md)、[准备freeze](../refactor-evidence/20261012-offline-windows-restore-launch/freeze.json)。6926旧安装harness与所有failed receipt不改写，Root审阅后实际运行并另写收据。

A–J剩余项保留：先完成最新产物绑定/专有升级，再复验空页pageReady、正常登录和clone D02/H、托盘退出/卸载保数据；之后依矩阵补权限与并行认证、聊天早停/续流、文档格式与恢复/保存后翻页、非空库关联删除、Wiki/图谱剩余操作、H取消/恢复/其他模式和设置重启。Neo4j/Langfuse/真实搜索厂商及手机/DPI属于需条件的用例；已完成的受控WebSearch与MCP不覆盖它们。最终数据/临时材料清理与各页面完整延迟仍待验，不将38组或全Goal改成PASS。


## 安装、离线恢复和正常登录：2026-10-12此前阶段checkpoint

本次仅维护三份主文档，读取public收据并检查链接/差异；未执行GUI、Windows生命周期、数据库/API、模型或产品修改。此前checkpoint的“绑定/restore/login未执行”已被以下实际结果取代，原失败证据不改写。

最新99ba…安装器已完成artifact绑定和专用中文空格目录同版本代码升级：session39435实际exit0，NSIS345243.731ms、所属树全退，25379安装文件/25304runtime与5cab身份匹配；当前94数据文件、12业务表及凭据材料精确保留，桌面0.6.2/core0.7.0不混用。[实际升级](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/executed-upgrade.json)、[前置当前基线](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/readonly-baseline.json)。

新版隐藏smoke session56937实际exit1，原d40b…收据保持失败；产品进程自身退出0，结果UnknownVizError不能证明页面挂载失败。[原隐藏失败](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/executed-hidden-smoke.json)。独立可见诊断产品ok=true/mounted=true/pageReady=true/login、IPC协议1/无HTTP/nodeExposed=false；startup_ms3170.3416区间为runtime_start_to_renderer_readiness_result，PNG1264×821/SHA3e89…经Root实际看图确认可读登录页。但末尾native_candidate_path_unavailable导致整体exit1/45ef…，不能标整个诊断通过，也未证明默认隐藏截屏已修复；单样本不作P95。[完整诊断失败收据](../refactor-evidence/20261012-installed-smoke-visible-diagnostic/executed-visible-smoke-diagnostic.json)、[Root实际画面复核](../refactor-evidence/20261012-installed-smoke-visible-diagnostic/root-visual-review.json)。

Windows离线副本正式restore已真实exit0：72表/26文件/24相对媒体，完整表摘要在正式restore验证，79个加密字段认证仅输出统计，FTS/vec与精确60bit ID通过，active_work/pending_auth均0、0认证/模型请求。正式restore72233.36ms与附加audit5708.672ms分别计，两次所属树正常退出；原Linux source未打开。[实际恢复收据](../refactor-evidence/20261012-offline-windows-restore-launch/executed-restore.json)SHA ca9c1d3435769a44250ae188d7457de090260fedc3012190fc137fccb0faef4c。

新的正常可见启动已实际执行session95508，Marlin PID33404/FILETIME134362525493273091/HWND7210358，仅正常--data-dir打开已恢复独立副本；7200秒专有Job仍持有，尚未托盘退出或完成后置审计。[启动事实](../refactor-evidence/20261012-installed-clone-visible-launch/visible-clone-started.json)。Root只读核实正确自有QA记录后，经正常GUI填写并登录；未重置密码或注入token。005实际https://marlin.local/platform/knowledge-bases正式IPC页显示本账号2库/16文档/10027摘录/0处理中，不把它与全副本22908块或浏览器后续4库混为同一范围。D02引用、H报告及其他页面仍待正式安装链路复核。[无秘密口令可用性](../refactor-evidence/20261012-offline-windows-restore-launch/root-owned-source-login-availability.json)、[实际登录后页面](../refactor-evidence/20261012-root-native-clone-gui/005-after-login.json)。

B浏览器HTTP续验已实际完成新建自有空库、置顶、收藏过滤仅1库、复制为空副本、刷新；原库置顶而副本未置顶保持。04:40后置核对protected_unchanged=true、usage174、原2个可见库及media/.secrets/.settings摘要保持；两个自有空库尚未清理。025搜索框已有copy名称却仍4个article，Enter未计搜索通过，焦点送达原因未确认，不直接归为产品检索缺陷，也不计新安装版B通过。[收藏实际结果](../refactor-evidence/20261012-root-kb-list-followup/013-pinned-filter-list.json)、[复制后清单](../refactor-evidence/20261012-root-kb-list-followup/017-all-copied-list.json)、[刷新保护核对](../refactor-evidence/20261012-root-kb-list-followup/reloaded-readonly-db.json)、[未通过的搜索结果](../refactor-evidence/20261012-root-kb-list-followup/025-search-copy-result.json)。

A代理仍独占认证GUI。038 snapshot实际runtime_unavailable/closed connection、exit1属于工具环境观察；039 status随后ready/connected，不能继续写当前runtime永久不可用，也不据此认定产品认证失败或所有A用例已通过。[连接关闭](../refactor-evidence/20261012-auth-browser-isolation-real/038-d1-settings-snapshot.json)、[随后恢复](../refactor-evidence/20261012-auth-browser-isolation-real/039-runtime-after-connection-loss.json)。

Goal保持active。最新升级、restore与正常登录已实际，不再列为未执行；正常clone退出/后置业务及媒体凭据审计、D02/H正式IPC、其余A–J、默认隐藏smoke、崩溃恢复/卸载保留仍待验。两个自有B空库及临时材料待验收结束后按既有授权清理；38个稳定组不扩充，整组通过仍仅M-01/M-02。


## 正式安装副本正常退出与报告另存：2026-10-12此前阶段checkpoint

本轮仅只读核public收据和已保存PNG/JSON，更新专项和三主文档，未GUI/Windows/API/模型/数据库/产品操作，FINAL由Root负责。此前“33404仍运行/退出审计未完成”已由以下实际终态取代，旧失败原字节保持。

最新正式安装副本已完成正常GUI读取、关闭到后台、唯一托盘退出和限定后置：session95508实际exit0/chunk1bf1c7，收据b357…的bootstrap0/Job active0/完整所属树退出，reap无termination。3879232.337ms是整段停留/验收寿命，16651.61ms是同句柄bootstrap reap等待，均不是启动或页面P95。before/after的protected_tables、managed_files、protected_desktop_meta和24媒体精确相等，identity_races空，受保护25268存活守卫保持；device_sessions25→26、refresh_tokens128→130和desktop_meta53→54是正常认证变化，不称全部72表/profile字节不变。[实际正常终态](../refactor-evidence/20261012-installed-clone-visible-launch/executed-visible-clone.json)SHA b357b6662430471f23c1db5dc73d62528ffe14d8b3924a07f9224768275cad55。

正式IPC已真实恢复旧资料/会话，当前图片来源点击到准确#2描述、原图可见；旧手册引用提示不存在，未计该旧引用通过。五题报告实际另存新installed-20261012.json，8275字节/SHA2d94a…与原reference全同，samples5/历史calls45/配置pipeline/source/metrics一致，原下载未覆盖、CR/Correctness仍null/未运行、无新增模型。1440×900与1024×768/DPI96评测表格可读，但1024侧栏两导航按钮accessible name为空，Root确认待修，不计全布局或J-04通过。049resize脚本、056工具F4、托盘null标题查找等失败均保留且不归产品；071退出后post app_not_found未重放，完整退出另依b357收据。[安装版具体子项与原回执](INSTALLED-CLONE-GUI-ACCEPTANCE.md)、[实际新报告核对](../refactor-evidence/20261012-root-native-clone-gui/report-download-after.json)。

Goal保持active：仅补当前图片引用、报告另存和正常退出/限定审计子项，D/H/J及38组不全通过，整组通过仍仅M-01/M-02。hidden UnknownVizError尚未修、可见诊断45ef整体exit1保持；1024侧栏名称缺失、崩溃重开/最新包卸载保留、其他页面及外部条件继续。B搜索/两个自有空库清理仍待Root终态，A代理零GUI等待Root租约；原四模型QA与原资料继续保护。

## A认证终态、B DOM清理与侧栏新来源：2026-10-12此前checkpoint

本次只完整阅读原文档、公有专项和原生收据后维护三份主文档，不操作GUI、产品、数据、模型、端口或Windows生命周期；FINAL及各专项/旧证据不改。此前“A等待租约、B两空库未清、1024源码待修”不覆盖下述新事实。

A隔离浏览器补验已终态：专用127:5184与两个独立persist profile，原D1默认600秒自然expiry→refresh→唯一真实mouse撤销→login；共享D2两页真实mouse logout后另一页无手动reload自动login；另新代次D3撤销而D4仍正常读取，owned已登录页实际关闭后从自有blank打开新document恢复身份。自然过期与独立保持为两个案例，不合并成同一次多设备过期测试；整Orca重启、最终撤销后再重开、该logout时另一active设备保持、late refresh和权限仍未验。4个自建设备已全部退出、0模型/任务；自有core exit0/Vite exit143，12助手/临时QA口令/cache已清理，数据/profile留给Root。注册夹具提交者不确定与工具迟到/断连原样保留，不计计划注册点击通过。[完整边界](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)、[178证据/41断言/81链接冻结db5b33](../refactor-evidence/20261012-auth-browser-isolation-real/freeze.json)。

B浏览器续验已清理两个自有空库，页面恢复原2库/16条目/10027摘录，protected表与managedfiles摘要相同、usage174。完整名称搜索、取消/确认删除、取消置顶和空收藏经标准DOM button.click进入正常前端流程；普通CLI click/keypress虽报送达却没有相应请求，不计真实鼠标通过，也未直接调用Vue业务函数/API。原025未生效、076未稳定断言失败和旧空页面观察保留；其他筛选、编辑、相似名称、重启和非空关联边界及安装版B仍待验。[实际续验及边界](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)、[最终保护核对](../refactor-evidence/20261012-root-kb-list-followup/cleaned-readonly-db.json)。

旧99ba安装版1024收起侧栏的三入口无正确名称仍保留失败。源码Platform.vue仅补type/aria-label/title/aria-current，Linux当前前端361/361与Vite build退出0；独立正常登录页102只读DOM核三名称、提示及知识库当前页正确，未改viewport，不能替代新安装版1024 UIA/实际导航。新[来源6e37](../refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json)为457输入/5额外测试，438 core产物保持、85前端产物绑定新Vite，共523；旧5cab与99ba产物身份不重写。[修复与原始收据](SIDEBAR-ACCESSIBLE-NAMES.md)。

Windows新Sidebar stage仅copy已实际exit0/owned tree closed，81263文件/2146851880字节（约2.15GB）、809.733秒，收据[f601](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-execution.json)与[原生终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-native-terminal.json)一致。这是经验证旧依赖复制到独立stage，不是新门禁、package或安装。正式--refresh --prepare-only已[开始](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-attempt.json)，native session30038/GUI租约释放见[启动回执](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-native-session-start.json)；本checkpoint尚未收到prepare终态，新NSIS/升级/1024复验均不预填成功。

Goal保持active，38组整体通过仍仅M-01/M-02。A新增仅上述有界子项，B DOM续验不冒充真实鼠标；1024侧栏源码已修但新版安装复验未完成。hidden UnknownVizError和45ef整体exit1保持；新prepare等待实际终态，崩溃恢复/最新包卸载保留、全页面与外部条件继续，原四模型QA与既有资料保护。

## 6e37实际升级、B类型筛选与认证测试清理：2026-10-13当前checkpoint

6e37侧栏历史来源已完成Windows正式prepare/package和同版本代码升级。prepare session30038实际exit0，Windows前端361/361、Core24/24、compiled Runtime6/6、Python11及真实SQLite/vec/64bit、受控Electron门禁通过；package session60561实际exit0，所属树关闭。安装器401841335字节/SHA `aabd44bc71a7a36b3d583720f8292b4035efe1c69159740db513931293568556`，仍属457输入/5额外测试/523产物的6e37身份。[prepare终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-execution.json)、[原生门禁](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-native-terminal.json)、[package终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/package-execution.json)。此前copy0/f601、81263文件/约2.15GB仅为独立stage准备，不能替代上述门禁。

Root唯一artifact绑定session53429实际exit0/收据3a21，绑定时state为verified_uninstalled；随后fresh baseline session55914实际exit0/90e7、唯一升级session74424实际exit0/718bd256完成安装。25379安装文件/25304runtime匹配，94数据文件、12业务表和1份凭据材料精确保留，原QA25268/FILETIME134361236166333286不动，integrity=ok/FK=0。NSIS329421.107ms仅安装命令耗时，所属树/owned bootstrap均0、无强制reap；desktop0.6.2/core0.7.0属于同版本代码升级。application_started=false/manual_gui_verified=false，尚未运行新包hidden或visible，更未验证1024导航。[artifact绑定](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/artifact-binding.json)、[实际前置](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/readonly-baseline.json)、[实际升级](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/executed-upgrade.json)、[原生终态](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/upgrade-native-terminal.json)。

B类型筛选的真实缺陷已修复：两库旧存储type均为document，旧真实mouse/HTTP200选择文档却混入Wiki库；查询现复用既有indexing投影在分页前互斥分类，不改历史type。真实SQLite两项具体分类断言RED 2FAIL→本文件8/8、相关44/44，core typecheck、测试strict/noEmit及build均退出0。新page749b7cae真实鼠标选择本空间+文档为1库/14条目/10020摘录，HTTP200/119.7ms；本空间+RAG+Wiki为1库/2条目/7摘录，200/327.6ms，Root实际看图确认。047/049真实恢复全部分类/全部范围，050恢复2库/16条目/10027摘录/0处理中，200/158.5ms。均为各n=1浏览器请求时间，不是P95、整体页面延迟或优化对比；恢复分类时一次401后200重试保留，未另核refresh原因。近期/本空间已有mouse与请求证据，老日期排除仍未证明；此前完整名搜索/删除/取消置顶的DOM备选不改记为真实鼠标。B-01仍partial。[专项与真实步骤](KNOWLEDGE-BASE-TYPE-FILTER.md)、[132证据冻结5cd1d3](../refactor-evidence/20261012-root-kb-type-filter-checks/freeze.json)。

Root仅精确pidfd SIGTERM停止旧Source2245508/startTicks17581590，原session7456退出0；新Source3833788/startTicks22088558/session72606已ready。重启和最终readonly审计的12张保护业务表、24份媒体与1份凭据文件精确相同，active jobs0/usage174，本轮没有新增KB或模型调用；认证/审计变化不纳入全字节相同。Python未导出pidfd、argv首项差异及028快照flags不支持均保留为工具问题，不计业务失败。新筛选源码及下述auth测试清理都不在已安装6e37，旧安装/完整核心检查不能继承为当前源码通过。[实际服务代次](../refactor-evidence/20261012-root-kb-type-filter-checks/source-owned-exec-observations.json)、[最终保护核对](../refactor-evidence/20261012-root-kb-type-filter-checks/source-final.json)。

默认Core认证测试对Python/Django的依赖已按原断言意义移除：合成Django黄金向量与独立PBKDF2规范oracle覆盖Unicode、迭代、错误密码、旧hash认证和新随机盐hash。真实无Django解释器下原兼容项RED 0/1是测试依赖缺口，不是生产认证失败；修复后auth12/12、相关17/17、核心typecheck及测试strict检查退出0、无skip，生产passwords.ts/auth index哈希完全不变。未运行当前源码完整套件或GUI；旧Playwright auth配置仍依赖Django，退役清理只属partial，不删除兼容能力。[设计与真实结果](PBKDF2-COMPATIBILITY-CHECK.md)、[独立冻结108f](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/freeze.json)。

Goal保持active，38组整体通过仍仅M-01/M-02，69个UI稳定编号不扩张。A有界子项、B DOM备选与后续真实mouse分类分别保留；6e37包虽实际升级，尚未启动/1024复验，当前筛选与auth测试delta另待新来源完整检查和交付。hidden UnknownVizError和45ef整体exit1保持，崩溃恢复/最新包卸载保留、全页面、late refresh/权限及外部条件继续；原四模型QA与既有资料保护。
