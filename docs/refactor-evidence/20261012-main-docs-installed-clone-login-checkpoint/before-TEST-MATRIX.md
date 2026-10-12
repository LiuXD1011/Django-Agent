# 真实验收矩阵

M-01/M-02及私有IPC集成已执行；Orca初始化、退出/登录与新建库已有真实证据，Windows可见窗口已完成初始化、四模型调用和五文件上传。未执行的并列行为及正式安装条件仍须逐项核验。稳定编号下每个并列行为继续拆分为独立用例，旧实现基线不能计入新应用通过。

最新检查为核心完整109文件695项=693PASS/0FAIL/2条件SKIP、700.755615秒，另plain Node compiled2/2、16.380500秒；当前P2前端361/361及Vite build退出0，旧360为初版历史。MCP真实续验已留空Key编辑/启停、唯一GLM发现并调用工具948与新回执`:2`，4模型调用3353tokens，原保护SHA相同，自有服务soft-delete/SDK正常关闭；只补相应子项，不填满I/E/J。[核心全套](../refactor-evidence/20261012-web-search-alias-final-core-checks/full-execution.json)、[compiled独立](../refactor-evidence/20261012-web-search-alias-final-core-checks/compiled-execution.json)、[前端冻结](../refactor-evidence/20261012-web-search-provider-ui-implementation/freeze.json)、[真实MCP](MCP-REAL-AGENT-BROWSER.md)。

联网搜索真实续验已经终态：自有SearXNG的CRUD/空Key保留/清Key取消确认、默认选择、off/on保存刷新和SEARCH-UI-12新旧结果失效均有真实Orca步骤。唯一GLM回合实际一次web_search返回2来源、35ms，答案37天与哈希/关联记录要求正确；4成功模型调用3846tokens，主任务17.913秒、维护5.660秒（有27ms重叠，不能相加/P95），usage166→170/两任务completed/0active。两条答案链接分别实际打开200/142.9ms与200/167.9ms。另匿名公共DuckDuckGo单次连接200/5结果/1387.3ms只算连接，不是公网Agent质量。四模型/key/gold/Wiki/评估/MCP保护SHA相同，自有两服务取消删除后仅各自确认soft-delete。原P2与工具误点回执保留；禁用后Agent零HTTP、Google/Bing、任意外部服务、正式Windows搜索IPC仍未验。[真实完整续验](WEB-SEARCH-REAL-AGENT-BROWSER.md)、[219份browser证据](../refactor-evidence/20261012-web-search-real-browser/browser/freeze.json)。

GUI最后确实保存off/空默认，raw值为`{"enabled":false,"provider_id":""}`，并非原NULL；随后Root在精确owner正常退出、活动/待确认IPC为零、无未知写者的离线窗口，只对tenant2.web_search_config做精确CAS恢复原NULL。其他tenant字段/受核业务表不变，维护不计GUI reset通过。[实际正常停机及维护](../refactor-evidence/20261012-offline-source-stop/stop-receipt.json)、[冻结后只读补记](../refactor-evidence/20261012-web-search-real-browser/browser/maintenance-followup.json)。此前PID1920563重启不变的证据仍是历史时点；后续实际导出以停机回执为准，不把live目录当静态备份。

原cf2a中止wrapper1/childnull/retained-handle cleanup超时、7项实际Windows失败与反斜杠fixture修复记录保留；最新完整361 Windows门禁属于新的5cab clean prepare，不抹旧失败，也不填满I/E/J。

最新[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)仍为SHA256 `5cabb11adcff22acf3c02f6cb70dce381acc3b19597d662ac95c6e2d471a7bac`，457输入/5额外测试/523编译，core5cc596…/前端5b7b27f8…未变。全新Search Result Final Build的正式prepare session10779已真实exit0、owned tree closed，1806.243694秒，结束02:59:01.514429 UTC；Windows完整前端361/361及正式生产/native门禁通过，prepare receipt SHA `38613d5d78244762b54d4c3b097597ddca3576f4624ae4210dc5c38999abdb0d`。[实际prepare终态](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-execution.json)。随后正式package session79579已真实exit0、owned tree closed，824.2763883秒，结束03:16:15.320527 UTC；[实际package终态](../refactor-evidence/20261012-web-search-result-integrated-windows-build/package-execution.json)SHA `0b0b9a41a780009da7195291814418a9422aecd9f95820437cf876d0eabbd838`，[ASAR审计](../refactor-evidence/20261012-web-search-result-integrated-windows-build/asar-audit.json)SHA `0fc8849d955fdf6e8d74695e1e9f87c9c01ae9e8ff1e788ae5e307b79cb6f31f`。Root提供实际installer401841299字节/SHA `99baabeeb82dd4af6312356810a91d0a2b51ec1c62726a8de3d917305fe5a8f6`，位于独立Search Result Installers。artifact绑定session59599尚在进行，最新升级、pageReady/GUI生命周期未执行；构建和installer产出不算正式安装通过。旧cf2a中止、7项Windowsfixture失败、39f346/347与46a缺pip失败全部保留，Goal active。

Root实际Linux离线导出已exit0：72表、26backup文件、24相对媒体引用、0外部引用，原source完整目录/文件保持，Root再次逐项核26文件。停机时原27文件/62目录/197530706字节与22908chunks是来源基线，不是Windows复制或完整Chromium profile镜像。export-result SHA `ed33ffc2…`；offline-clone-manifest SHA `2ec148969a1274d3ef7ebfb1c1ce1f577758b1592bbe88f4e6cb07de8e845a87`，backup-manifest SHA `23b4b109f54145b483699a76b73b40376e38fee02cc44db13f7d2c6de4acb913`，二者不能混用。8876脚本已按原SHA归档并精确消费删除，原native readonly侧文件失败探针保留。[实际完成回执](../refactor-evidence/20261012-offline-source-stop/export-execution.json)、[结果](../refactor-evidence/20261012-offline-source-stop/export-result.json)、[消费清理](../refactor-evidence/20261012-offline-source-stop/consumed-script-cleanup.json)。Windows restore、原口令正常登录、D02/H IPC仍未执行。

独立Windows restore/launcher已完成review_only准备：主脚本SHA `d79d502ba816332fde4323cbeb2e963cee731870d00c3fc5e6987bf29855860e`，18文件冻结SHA `1aab0f0f1f80df09af52716b3f8029bade6764f4778ed7cd530f5fae8a5b9310`；Python18项假文件/Fake SDK守卫、Node6项纯函数、语法/default检查均通过，15links0bad。这些无实际Windows SDK/复制/restore/GUI/付费调用，不作为安装验收。正式restore保持完整72表合同/2400秒有界Job；visible-clone仅绑定未来实际installer/upgrade后执行，7200秒持有/每5秒进度、同handle30秒reap，保护25268原代次。Node附加审计不重复hydrate全vec shadow，完整shadow摘要仍由正式restore验证；未知原口令不注入token/改密码。[已冻执行准备](OFFLINE-WINDOWS-RESTORE-LAUNCH-HARNESS.md)、[准备freeze](../refactor-evidence/20261012-offline-windows-restore-launch/freeze.json)。6926旧安装harness与所有failed receipt不改写，Root审阅后实际运行并另写收据。

以下46a描述是上一checkpoint的历史，终态与当前待办以上方为准。

当前最新[集成freeze](../refactor-evidence/20261012-integrated-poll-clock-source-freeze.json) SHA256 `46a4ad77664f71d593f6f53a7504ed95e1651c8a806ec80fe5b16af66112007e`，454构建输入/5额外测试/523编译文件。与39feca…相比只改解析记录轮询测试，产品/依赖/编译产物不变。旧39f Windows clean prepare真实346/347、exit1、845.318秒，一项Node2100ms等待断言失败；原失败不覆盖。旧Windows单文件隔离诊断5/5、49.075秒不抹全套失败。测试改用官方Clock、1999/1ms边界、真实response barrier及终态6000ms无新增reads；相关5/5、TAP6084.821ms，原所有行为断言保留。根代理新prepare session41187正在同Chinese Query Final Build目录由正式builder全清staging、重新npm ci与完整前端检查，没有复用失败payload；截至本checkpoint没有新prepare成功收据、package/installer或最新安装版通过。[测试设计与RED/GREEN](PROCESSING-RECORDS-POLLING-TEST.md)、[旧失败收据](../refactor-evidence/20261012-integrated-chinese-query-windows-build/prepare-execution.json)、[旧单文件对照](../refactor-evidence/20261012-processing-poll-windows-diagnostic/execution.json)、[新准备命令](../refactor-evidence/20261012-integrated-poll-clock-windows-build/prepare-attempt.json)。

新五题真实Ragas/报告及免费CJK重验已完成，以下H子项更新为明确部分完成，整组仍未完成；历史422/零分/低分/未知调用不改写。[真实终态与下载](EVALUATION-CHINESE-QUERY-BROWSER.md)。新harness6926已经根审阅与Linux12/24/2守卫，但产物未绑定、未执行Windows；[修订资料](../refactor-evidence/20261012-integrated-install-preparation/reap-revision/README.md)。

本轮服务中断单列为环境事件：旧core1064192/session55312在22:45:26.930Z stopping后exit0、8000无监听，page6 Vite代理GET500；原因尚未查明，不归为auth缺陷。恢复1171965/startTicks16194111/session8225后7表/四模型/vault摘要相同，health真实typescript，本页随后正常refresh200/GET200。它不解释另一页login跳转或完成所有认证条件。[恢复前](../refactor-evidence/20261012-browser-core-recovery/before.json)、[恢复后](../refactor-evidence/20261012-browser-core-recovery/after.json)。

证据记录字段：ID、页面、前置条件、操作步骤、期望、实际、状态、运行数据目录、版本、模型/非秘密配置、起止时间、耗时、截图/日志/JSON路径。状态只用通过、产品失败、环境失败、未执行、缺少配置。

| 用例组 | 最低真实操作及断言 | 链路 | 当前 |
| --- | --- | --- | --- |
| A-01 | 初始化/注册/正常登录/坏密码/退出/重开与会话恢复 | Orca+Electron | 未完成（中文提示修复已合入；Orca真实坏密码401显示“邮箱或密码错误”，当前验收密码登录恢复原库。跨设备及最终安装版剩余项待复核） |
| A-02 | 验收用户密码弹窗与设备撤销，真实用户不变 | Orca+Electron | 未完成（历史401已修复，Orca自然过期后改密/撤销其他/全体退出均正常续期且各提交一次，数据库后置断言通过；中文旧密码错误实际POST400正确显示。过期撤销当前、跨页签迟到refresh及最终安装版仍待复核，见20261010-root-sensitive-natural-expiry-real.json） |
| A-03 | 不同用户、活跃成员、个人空间、越权下载/订阅/写入 | UI+集成 | 未执行 |
| B-01 | 知识库新建/编辑/搜索/置顶/复制/删除、排序统计、刷新重启 | Orca+Electron | 未执行（新建已有证据；最新Orca专用账号置顶/收藏/取消置顶、复制、删除先取消再确认已实际完成，SQLite确认原库保留/空副本软删/关联残留0；编辑/搜索/刷新重启等剩余项未执行） |
| B-02 | 相似名称/空库、关联记录及残留索引清除 | UI+DB | 未执行 |
| C-01 | MD、文本PDF、扫描PDF、DOCX、CSV、XLSX、PPTX、图片及全部既有格式实际上传 | Orca+解析进程 | 未完成（原生3MD/CSV/PNG；Orca十四份正常资料有真实正文或图像结果，坏PDF明确失败。坏PNG修复后实际点击重解析约1.9秒失败、root/stage结束、页面自动更新；SVG/HTML/JSON辅助任务已取消，不计完整链路通过。见551及20261011-root-document-current-status-ui.json） |
| C-02 | 表格/内嵌图、中文空格路径、重复/损坏/空/大文件 | UI+文件 | 未完成（历史发布42440ms/29次health超时及后续24次中3超时保留。阶段3当前PID245516真实2.88MB/四万行重解析168次读取全部200，发布期间56次全部200；全文/11429块完整、0模型调用。后续一轮289次含1正文409、无超时，原因待核实；取消及正式包仍待验。见20261012-root-cancel-live-rounds-analysis.json） |
| C-03 | 解析/分块/向量/摘要/图谱/Wiki结果，进度、取消、重解析、重试、退出恢复 | UI+任务 | 未完成（旧109610ms及后续3请求/7571 tokens审计保留。阶段3业务265/265、runtime46/46、桌面14/14及compiled2/2/类型构建通过；当前Orca重解析完成、发布读取168次全部200。996–999真实键盘发布取消，cancel-parse200/866.1ms、job/root/stage cancelled/running0，正文/完整11429分块/FTS哈希相等，250观察全200/0模型调用。快速重启、外部剩余阶段和正式包仍待验，见20261012-root-cancel-keyboard-live-analysis.json） |
| C-04 | 标签/搜索/筛选/多选/移动/批删；每个attempt记录结束 | Orca+DB | 未完成（标签/recursive256/child256、关键词Enter隐藏选择清除、清筛选已实测；MD类型选项实际过滤正确。两短资料移动先取消再确认，哈希/标签/分块/FTS正确；批删先取消保留再确认清除，原大文件保留。移动后问答、跨权限目标及最终安装仍待验，见20261012-root-owner-move-real.json） |
| D-01 | 分块打开/编辑/启停/删除，父子/图片/页码/定位 | Orca+检索 | 未完成（编辑/启停/删除及第2页200/88ms历史保留。当前11429块真实未保存翻页/关闭抽屉/切类型均保留草稿并阻止切换，正文/完整chunks/10000FTS前后SHA相同、无保存；保存后翻页及最终安装版仍待验，见[三项实际保护](CHUNK-UNSAVED-BROWSER-ACCEPTANCE.md)） |
| D-02 | 实际点击回答引用，打开正确文件和片段 | Orca+Electron | 未完成（Windows候选版图片OCR来源已实际定位；Orca原负责人来源及修复后的联合题手册政策/图片描述两来源均实际点击，doc+chunk、可见正文与原图已核对，见20261011-browser-model-page/185证明和169/184截图。最终安装版仍待复核） |
| E-01 | 全局/库入口、单选/多选/显式空选择、加载时快速发送 | Orca+Electron | 未完成（当前真实库入口预选后显式清空，数学323零检索；两库选择发送负责人/预算，保存范围正确、林青128000及来源正确，刷新恢复两库和四消息。默认未指定、加载快发与最终安装仍待验，见CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| E-02 | 流式/早停/request_id取消/重试/续流/网络中断/切换与重开 | UI+进程 | 未执行 |
| E-03 | 置顶/清空/删/批量、图片附件/上下文/切换模型 | Orca | 未完成（本轮专用会话实际置顶/取消置顶及数据库核对、已有会话128000窗口/482估算/120000阈值已通过；清空删除批量、图片附件、空态错误、切模型仍待验，见CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| E-04 | 真实Agent工具/子任务/轨迹、记忆意图/开关/范围 | Orca+外部服务 | 未完成（原文档工具/跨会话记忆及三时间轴保留；新MCP唯一GLM回合实际发现并调用qa_purchase_total，948及新回执/真实工具Schema正确，4成功模型调用3353tokens，维护图权限warning保留。子任务、记忆开关、其他详情和正式IPC仍待验，见[MCP实际账本](MCP-REAL-AGENT-BROWSER.md)） |
| E-GOLD | 事实、旧版冲突、跨文档、表格计算、图像、缺失事实拒编、相似实体、中文别名、库隔离、权限隔离、删除后、修改后12类标准答案 | 真实模型+引用 | 未执行（相似实体与图片事实/机器引用/来源打开已复测通过；事实/旧版/跨文档/表格/缺失/别名/政策已有实测。隔离/修改/删除独立用例与部分旧答案机器引用仍未完成） |
| F-01 | Wiki生成/打开/搜索/编辑、目录/内部/来源/返回链接 | Orca | 未完成（生成及手动页新增/编辑/刷新/搜索/目录/双链/缺失提示/来源/删除确认已核对；长编辑保存已修复。B来源后返回知识库及内嵌只读入口已实际通过，正式原生链路等剩余项待完成，见407与480–490） |
| F-02 | 重生成/文档变化、表格/代码/公式/图渲染、既有lint修复 | Orca+DB | 未完成（实际重生成45.097秒、8调用成功；真实表格、代码、KaTeX、1000×440图片及脚本不执行已核对。文档修改/删除后的状态与lint等剩余项待完成） |
| G-01 | 图谱生成/查询/节点/关系/筛选/来源、空图/相似/重复/错误 | Orca | 未完成（Wiki实际11节点/26关系、双向箭头、类型过滤/空态、A/B详情、邻域7节点/全库、拖拽、搜索及B来源#6已核对；滚轮没有送达事件，缩放与其他图谱条件项待验证，见451–490） |
| G-02 | 配置存在时Neo4j真实连接/读写；缺少时明确提示不计通过 | UI+Neo4j | 环境失败（旧数据已配置，真实正常service key只读盘点连接失败；WSL/Windows均无默认Bolt服务，原图数量未知；UI连接/读写仍未执行） |
| H-01 | 候选生成/审核/修改/删除/发布/数据集选择/版本/有效题数 | Orca | 未完成（原H真实请求5题仅保留1/5后失败，2调用1648tokens；编辑/删除取消/发布单题v1/新建v2/确认删自有v2已实际完成。原finish_reason未记录，不能断言length。修复后新单组5/5、来源范围/hash/generation准确、5次stop共849tokens；已逐题UI来源审核发布5 approved/0 pending，auto/sample及最终安装待验，见[原失败](EVALUATION-BROWSER-ACCEPTANCE.md)、[本轮复验](EVALUATION-REAL-RECHECK.md)） |
| H-02 | ≥5已批准有证据题真实评测，开始/进度/取消/恢复/失败/历史 | Orca+Ragas | 未完成（新5approved唯一run完成5/5/coverage1，164.721秒、45调用全部成功/39505tokens、无retry/resume；Faithfulness=1、Answer Relevancy≈.9473、Context Precision≈1，Context Recall/Answer Correctness未运行。历史原422/零分/低分及unknown保留；运行中取消恢复/其他策略和最终IPC仍待验，见[真实记录](EVALUATION-CHINESE-QUERY-BROWSER.md)） |
| H-03 | 下载并打开报告核对sample/config/metrics/source；公开数据集、检索/分块评测 | UI+实际文件 | 未完成（旧v1安全仅分块与新5题仅检索均200/Hit-MRR-Recall1/0新增调用，实际下载打开新JSON；Ragas5题报告8275bytes/SHA2d94a554…已打开核5样本/配置/来源/45调用，CR/AC为null。报告删除仅取消保留；公开集/其他模式/404及新版安装待验，见[真实文件](EVALUATION-CHINESE-QUERY-BROWSER.md)） |
| I-01 | 常规名称/记忆、用户资料/偏好/历史/密码/设备保存重启 | Orca+Electron | 未执行 |
| I-02 | Neo4j/Langfuse配置、留空保密、真实连接、错误/trace/autologin | Orca+实际服务 | 未执行 |
| I-03 | 模型增改删/default/四角色/thinking/key写入及清除/真实调用/用量 | Orca+四真实模型 | 未完成（原生与Orca四角色都有实际厂商调用及分类；当前核心用专用空间合成凭据完成自定义默认对话模型创建/名称编辑/空Key保持配置/地址变更无新Key不保存/清Key和删除先取消再确认，真实四模型及key文件哈希不变，0新厂商请求。思考保存、其他厂商/角色CRUD及最终安装等仍待验，见MODEL-CRUD-BROWSER-ACCEPTANCE） |
| I-04 | 检索topk/阈值/rerank/维度/索引重建及切换失败 | Orca+SQLite vec | 未完成（原生及Orca五数值/Rerank实际修改、保存、离页再进入保持，已恢复有效原六参数；各自模型SHA不变、usage126/98，0新调用。维度切换/重建及最终包仍待执行，见20261011-root-browser-retrieval-real.json及native partial） |
| I-05 | 联网搜索真实查询和引用/错误；MCP CRUD/启停/工具发现及真实协议调用 | Orca+实际服务 | 未完成（MCP受控SDK留空Key编辑/启停、GLM工具948/新回执/4调用3353tokens及自有删除/SDK退出已实测。WebSearch受控SearXNG CRUD/Key/default/off-on刷新、唯一GLM4调用3846tokens/2真实来源/35ms与两链接200已实测；公共DDG只一次连接5结果。GUI终态off/blank后Root离线仅CAS还原原NULL，不算GUI reset。禁用后Agent零HTTP/全部厂商/正式Windows搜索IPC仍待验，见[MCP](MCP-REAL-AGENT-BROWSER.md)、[搜索实际终态](WEB-SEARCH-REAL-AGENT-BROWSER.md)） |
| I-06 | 系统版本/路径/生效配置/缓存/诊断/备份全部既有操作 | Orca+实际文件 | 未完成（原生0.7.0/TS/SQLite/向量1024与路径已实际显示，正常滚动展开生效4/30/60/INFO；保存重启/env覆盖、其余既有操作及最终包待验，见20261011-root-native-retrieval-system-partial.json） |
| J-01 | 正式包无Vite/系统Python/Node启动，文件选择/拖入/单实例/缩放/托盘 | Electron安装版 | 未完成（旧350包3231.9168ms只mount/纯背景不计pageReady；新smoke源已修。5cab clean prepare真实exit0/361前端/native门禁，package79579也已exit0/installer产出；artifact绑定/最新安装/pageReady/拖入/单实例/托盘尚未验。46a缺pip、cf2a中止及旧failed收据保留，见[就绪](DESKTOP-SMOKE-READINESS.md)、[真实prepare终态](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-execution.json)） |
| J-02 | close/background/quit与拥有进程清理、崩溃重开 | Electron安装版 | 未完成（历史四模型QA25268退出/重启事实保留；旧27784真实核owner后Quit，原harness exit1/owned_bootstrap_not_reaped保留；独立同代次Win32 Wait0=0/ExitCode0/窗口无，保护25268仍活。仅device_sessions摘要变化、其他11表/key一致，current94files不等于旧90；新修复正式包生命周期/崩溃重开仍待完成，见[原失败](../refactor-evidence/20261012-installed-postvalidation-review/executed-visible-retained.json)、[独立精确核对](../refactor-evidence/20261012-installed-postvalidation-review/exit-exact-readonly-audit.json)） |
| J-03 | 中文空格路径隔离安装/升级保留/卸载保留数据 | Windows x64 | 未完成（旧350升级/12表90文件1凭据保留；39f346/347、46a缺pip、cf2a中止均保留，5cab clean prepare与package均exit0、installer已产出但绑定/升级待验。Root已真Linux72表/26文件/24媒体导出，Windows clone restore/原口令登录、最新升级/正常退出/卸载仍未验；review_only准备不算实际迁移，见[副本执行准备](OFFLINE-WINDOWS-RESTORE-LAUNCH-HARNESS.md)） |
| J-04 | 1440×900/1024×768、可用时125/150%缩放、键盘/IME/遮挡/对比度 | Orca+Windows | 未完成（旧QA/350安装版27784两尺寸/最小化恢复1280×860、DPI96历史保留。最终最新来源包两尺寸/pageReady、125/150%、其他页面/IME待验；旧350子项不替代最新正式包） |
| M-01 | 旧副本导入：31业务表/关键关系/凭据/媒体hash | 集成 | 通过；7源文件哈希及实际workflow重解析通过，外部模型未配置 |
| M-02 | 重复导入无重复、失败不半写/覆盖key、备份恢复 | 集成 | 通过，44表/2446文件独立恢复及失败fixture |
| R-01 | GLM思考辅助调用、库范围、早停、流取消异常 | 集成+真实UI | 未执行 |
| R-02 | 重解析root关闭、并发事件连续无丢失、评测数量/配置、Langfuse主机一致 | 集成+真实UI | 未执行 |
| PERF | 冷/热启动、页面/list/search/save、上传队列阶段总时长、首段/全文/停止、评测等待执行；记录次数和条件 | 实际用户链路 | 未完成（历史2512.984ms及新旧包3231.9168ms没有pageReady断言，后者实际纯背景只mount，不计可交互冷启动。新生成请求5549.8ms/五厂商各790–1131ms为单次观察；历史四角色调用和发布观察分别保留，不是P95。新版就绪计时与完整延迟/重复样本仍待验） |

仅当提供具体操作和实际结果及证据时才修改通过状态。API/DOM/截图/单元测试不能替代 Orca 操作；浏览器成功不能替代正式 IPC 和安装版。少量混合样本不能声明生产 P95。

## 逐项UI操作清单

以下69项来自实际Vue基线；仅有具体完整子项证据才记通过。浏览器/Windows隔离数据与正式安装版分别记录，部分步骤完成不代表整组通过。旧初始化的一次性密码场景在本地新核心改为用户自设密码，远程旧协议仍保留。UI-CHAT-002按已批准Goal明确取消选择执行：未指定用默认范围，显式空数组不检索。

| 编号 | 实际操作 | 断言 | 新架构状态 |
| --- | --- | --- | --- |
| UI-AUTH-001 | 未登录直接打开知识库深链，回 login 后输入有效邮箱密码并点击登录 | 未授权页不展示私有数据；导航到知识库；刷新仍恢复服务端身份 | 未执行 |
| UI-AUTH-002 | 点“创建个人账号”，确认密码先输入不一致，再改为一致点注册 | 不一致不提交；注册后私有空间建立，跨设备同账号可访问 | 未执行（Orca实际密码不一致提示、改为一致正常注册并进入知识库已通过；SQLite确认专用用户/个人空间/owner成员关系。跨设备访问仍待执行） |
| UI-AUTH-003 | 空数据隔离实例，点自动初始化，填专门邮箱及自选密码并确认提交 | 实际建立管理员并进入知识库；密码和凭据不回显、不写报告 | 通过，Orca真实操作及请求139.9ms见evidence/20261010-orca-initialization.json；Electron未执行 |
| UI-AUTH-004 | 已初始化/禁用/忙状态分别点自动初始化；另模拟成功但无 temp_password | 明确错误/成功提示；无密码不造凭据、不自动跳页 | 未执行 |
| UI-AUTH-005 | 同一浏览器同站点两页签登录，在一个账户菜单点退出；另一浏览器作为独立设备观察 | 当前页及共享storage的页签失效，独立设备保持登录；后到旧 refresh 响应不复活 | 未执行 |
| UI-AUTH-006 | 有保存旧 Bearer 登录的兼容场景打开受保护页，再显式 cookie 登录 | 旧会话可按现有契约恢复；新 cookie 登录清旧 token，不回退泄漏 | 未执行 |
| UI-AUTH-007 | 登录后将服务指向不同 service_id，刷新；另在网络中断时恢复 | 服务改变需重登、缓存不混用；网络错误不删除未提交本地内容 | 未执行 |
| UI-NAV-001 | 有历史点主导航“对话”，再点聊天侧栏“新对话”；空历史重试 | 前者最近会话、后者草稿；空历史进入草稿 | 未执行 |
| UI-NAV-002 | 最近访问在两个知识库详情间切换，再浏览器后退/前进 | 页面、API操作、标签/选择/抽屉都属于当前 kbId | 未执行 |
| UI-NAV-003 | 点账户头像、菜单 general/user；general 打开评测，直达 devices/wiki/chat | section/deep link/懒加载/刷新正确，不丢账号状态 | 未执行 |
| UI-KB-001 | 点新建、填名称描述，分别组合混合/Wiki/图谱与 semantic 父子参数 | 保存实际配置，卡片能力标签正确；空名称/无索引/越界不提交 | 未执行 |
| UI-KB-002 | 输入关键词 Enter、切文档/RAG+Wiki、范围全部/收藏/最近/本空间、刷新 | 请求与客户端筛选符合现有含义，数量/空态正确 | 未执行 |
| UI-KB-003 | 卡片置顶、收藏查看、取消，再点复制 | 行为持久化、清单刷新；操作不意外进入详情 | 未执行（最新Orca置顶/收藏/取消/复制真实操作及SQLite保存已确认，留在清单；刷新重启保持待执行） |
| UI-KB-004 | 点卡片进详情；点删除先取消，再确认删除隔离库 | 取消保留，确认删除库/文档/索引/Wiki，清单更新 | 未执行（自己的空副本删除先取消再确认已实际通过，原库保留/关联残留0；详情入口与非空关联清理待执行） |
| UI-KB-005 | 知识库设置修改名称/分块/能力并保存，再刷新 | needs_reindex/生效策略按服务端显示；不暗中触发重解析 | 未执行 |
| UI-DOC-001 | 上传选择多个文件，追加重复、移除，改标签/分块，再开始解析 | 选择阶段零上传；队列去重；确认才提交，最多3并发 | 未完成（Orca十四份选择时0文档/任务/调用，重复选择仍14，真实移除后13、追加恢复14，只确认一次；标签/分块配置及并发上限子项待执行，见502/511/514） |
| UI-DOC-002 | 混合成功/服务端 deduplicated/失败文件点击开始解析，再重试失败 | 各项和总数正确；仅失败留队列，不重复提交已成功文件 | 未执行 |
| UI-DOC-003 | 选择 HEIC/HEIF、音视频与有效 JPEG/文本混合 | 明确拒绝不支持项，有效项仍可确认上传 | 未执行 |
| UI-DOC-004 | 点标签管理新建，按标签/状态/文件类型/关键词筛，再清空 | 数据与计数正确、已选隐藏项剔除，不把过滤结果当全库状态 | 未完成（状态/全库9/2/3历史正确；标签创建/上传关联/筛选、MD类型、关键词Enter隐藏选择剔除、清空均有真实Orca步骤。最终原生链路仍待复核，见20261011-root-chunk-counts-labels-real及20261012-root-owner-move-real） |
| UI-DOC-005 | 对后台解析中文档打开 Chunk/解析记录，取消后再重解析 | 轮询自动启停，展示最新尝试而不是跨 root 混画，状态/error 可见 | 未完成（坏PNG重解析/自动失败及历史失败2/取消3已有真实证据。阶段3Orca发布取消后1002/1004实际打开展开最新记录，已取消/18.2秒与后台attempt6一致，0 running span；1006稳定截图已查看。取消后再重解析、处理中抽屉与最终安装版仍待验） |
| UI-DOC-006 | 打开有>50块文档，编辑正文/启停，未保存翻页/筛选，再保存 | 脏页被阻止；保存持久化后可翻页；父块/容器只读 | 未完成（11429块抽屉真实page2/88ms、父块只读已有证据；本轮未保存翻页/关闭/切类型三项均保留草稿，正文/全部chunk/FTS SHA前后相同、0保存。保存后翻页及最新安装版仍待验，见[实际保护](CHUNK-UNSAVED-BROWSER-ACCEPTANCE.md)） |
| UI-DOC-007 | 打开带图文档，看 OCR/描述/关系字段，图片失败场景重解析 | blob 预览正确、失败有比例提示，图片失败不阻断文本编辑 | 未执行 |
| UI-DOC-008 | 选择两文档移动到返回的目标库，再源/目标清单和问答检索 | 文档、chunk/索引迁移一致；无权限目标不可绕过 API 选择 | 未完成（两自建短资料移动先取消再确认，源/目标清单、哈希/标签/分块序列/FTS命名空间核对正确；问答、跨权限目标界面与最终安装仍待验，见20261012-root-owner-move-real） |
| UI-DOC-009 | 单删/批删先取消再确认；删末页唯一可编辑 chunk | 取消无写；删除数据/索引更新；chunk末页退上一页 | 未完成（单删及最后子块索引清除已有证据；目标两短资料批删取消保留、确认软删及清分块/FTS正确，源大文件完整。多页末块回退与最终安装仍待验，见20261012-root-owner-move-real） |
| UI-DOC-010 | 文档/Wiki/图谱/解析记录切换，关能力；直接 `tab=settings` | query与标签同步，能力禁用回文档，settings开弹窗 | 未执行 |
| UI-WIKI-001 | 独立 Wiki 新建含双链/表格/公式的 Markdown，切页面并选择 | 页面保存/读取/安全渲染，空标题不提交；内嵌不误增入口 | 未完成（Orca实际创建、选择、编辑与版本保存、表格/代码/公式/真实图片/脚本不执行均通过；空标题首次点击位于视口外没有提交，未计校验通过；内嵌只读子项仍待验证，见407综合证明） |
| UI-WIKI-002 | 阅读页搜索并点结果、刷新、点存在/不存在双链 | 本地搜索、选中切换、刷新正确；不存在提示，目录是文本 | 通过（Orca真实搜索只剩目标页、选择、刷新保持正文与再次选择，存在实体双链跳转及缺失双链明确“Wiki 页面不存在”，目录正常跳转；344–375实际操作和407只读核对，版本0.7.0/browser-qa；不计正式原生安装链路） |
| UI-WIKI-003 | 图谱搜索页、单击节点、双击、抽屉展开邻域、全库概览 | getPage/ego/overview与中心正确，内容回退和邻居高亮 | 未完成（Orca搜索/无结果、节点A/B与来源、邻域7节点和全库11节点实际生效；双击及内容回退剩余项未执行，见408–490） |
| UI-WIKI-004 | 节点类型/图例开关、箭头、适应屏幕、滚轮/拖画布/拖节点 | 类型过滤/空态、双向箭头与视口可用，无重复监听 | 未完成（过滤/空态恢复、26关系及6双向、适应屏幕、trusted画布/节点拖拽已验证；wheel未送达，滚轮与重复监听等剩余项待验证，见451–465） |
| UI-WIKI-005 | >500节点图显示 truncation，换 kbId 后继续搜索/开详情 | 部分展示有说明；不得读上个库页面或图数据 | 未执行 |
| UI-CHAT-001 | 新对话点快捷问题，选模型/库/MCP/联网后发首消息 | 快捷只填；只创建1会话并发送1请求，首消息及设置保存 | 未执行 |
| UI-CHAT-002 | 知识库草稿清空预选，再多选发送；删库后打开旧会话 | 未指定采用默认范围；显式空数组不检索；多选保留；幽灵库无chip/计数/payload | 未完成（真实预选清空发送：323、零引用/检索；两库发送和刷新保存正确。空选择提示已修复并1172–1190实际复测，无新调用；默认未指定、删库幽灵剩余项待验，见CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| UI-CHAT-003 | 添加/删除图片与附件，每类超过5；输入文本后发送 | 限制5，预览/大小/base64正确；未输入query不可发；URL释放 | 未执行 |
| UI-CHAT-004 | 回答期间刷新/断网重连，再重开会话 | 按相同request_id恢复已有assistant/continue-stream，不重复模型请求 | 未执行 |
| UI-CHAT-005 | 请求刚发送、assistant ID尚未返回时点停止；工具/actor运行时再测 | 精确停止当前请求，后到消息不续生成，spinner收敛，按钮状态恢复 | 未执行 |
| UI-CHAT-006 | 慢历史请求中点另一会话；返回上一会话 | 旧请求取消/忽略，消息及last_request_state不串台 | 未执行 |
| UI-CHAT-007 | 展开工具/子Agent/引用，复制完整答案，看 Markdown/数学/错误结果 | 多工具ID/actor独立，失败输出不重复，复制正文，不启用禁用加入知识库 | 未完成（Orca联合题实际展开5条引用并打开手册政策与图片描述来源；事实、表格和原图已核对。复制、子Agent及其余渲染子项待完成，见20261011-browser-model-page/185证明） |
| UI-CHAT-008 | 侧栏置顶、清空消息、单删、批删、清空全部，先取消再确认 | 分组/当前会话/导航正确；全部仅当前授权空间 | 未完成（本轮专用会话置顶/取消置顶实际分组和is_pinned正确；当前会话保留用于正式安装复核。清空、单删、批删和清空全部仍待验，见CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| UI-CHAT-009 | 超20历史点加载更早/滚动顶端，流期间停留旧消息，点回底 | history/has_more、滚动位置正确；不强拉底 | 未执行 |
| UI-CHAT-010 | 点上下文窗口；新会话、已有记录、失败三状态 | context_window/used/percent/compact_threshold一致，有空态/错误提示 | 未完成（实际已有会话显示128000/482估算/0%/120000阈值；新会话和失败状态仍待验，见1142真实页面及CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| UI-CHAT-011 | 切轨迹，按过滤、展开长内容/schema、切三种时间轴 | turns数据对应当前会话；零时长记录不消失，actor/压缩/维护保留 | 未完成（真实工具过滤、两同名工具分别显示、Schema展开、全部过滤和序列/时长/时钟通过。原维护字段丢失/未知误标完成及object Object已修复并重启原轨迹复测；长内容展开、子Agent/压缩及最终安装仍待验，见CHAT-SCOPE-BROWSER-ACCEPTANCE） |
| UI-SET-001 | general有/无Neo4j两场景点记忆开关，刷新 | 不可用禁用；可用保存用户偏好，失败恢复开关 | 未执行 |
| UI-SET-002 | models点添加各类型和可用厂商、本地、自定义，填测试key并保存 | 预设/维度/类型筛正确、默认持久化，必填/厂商key校验 | 未完成（当前Orca自定义默认对话模型真实创建、加密合成凭据、空Key表单保持、长表单PageDown滚动和可见按钮点击均完成；全部厂商/角色与本地剩余项待验，见MODEL-CRUD-BROWSER-ACCEPTANCE） |
| UI-SET-003 | 编辑已有key模型留空保存，再改端点不填key；填新key保存 | 不回显key，空保留；新端点需新key，厂商切换不带旧key | 未完成（当前Orca密钥为空且不回显，名称保存仍显示已配置；更换地址无新Key表单不关闭、数据库地址与凭据均保持。新Key换地址/厂商切换剩余项待验，见MODEL-CRUD-BROWSER-ACCEPTANCE） |
| UI-SET-004 | 清密钥/删除模型先取消再确认；内置模型点删除 | 明确清除与删除差异，内置禁用，调用状态更新 | 未完成（当前Orca清Key先取消保留再确认移除/按钮禁用、删除先取消保留再确认软删/列表0，原四模型和key文件SHA不变；临时对象已清理。内置模型及最终安装版仍待验，见MODEL-CRUD-BROWSER-ACCEPTANCE） |
| UI-SET-005 | 思考弹窗换角色，选default/off/on和允许effort，保存；只读/旧revision | 只改当前角色、下轮生效、capability门控，冲突/readonly不覆盖 | 未执行 |
| UI-SET-006 | 模型用量切日/小时/15分，刷新有/无数据 | 7日统计、缓存率与模型点不混淆，无数据有提示 | 未完成（原生正常重启后排行完整，小时与15分均实际选择、图表和时间轴切换；Orca有/无数据及粒度子项已有证据。原生无数据和最终安装版待复核，见20261011-native-model-page/root-980264e8-d7d4-4afb-81f6-3ac5a148c673.png） |
| UI-SET-007 | 检索改五个数值/Rerank开关并保存；websearch启用notes保存 | KV持久化、刷新回填；UI文案与相对排名阈值一致 | 未完成（原检索保存/恢复保留；新增搜索Provider CRUD/Keyclear/default/off-on保存刷新/P2实际旧结果失效与唯一SearXNG Agent2来源真实点击200已通过相应子项。GUI终态off/blank与原NULL不同，Root正常停机后单字段CAS恢复不算GUI reset；notes/关闭后Agent零HTTP及正式安装仍待验，见[实际搜索](WEB-SEARCH-REAL-AGENT-BROWSER.md)） |
| UI-SET-008 | MCP添加/编辑留空key/禁用/删除，聊天选服务发送 | 配置持久化、不回显密钥、留空沿用；可用服务遵从服务端契约 | 未完成（原configuredKey编辑400已修；实际留空Key改名/禁用/启用后唯一GLM Agent握手、工具发现与调用948、新回执`:2`正确，4成功模型调用3353tokens，0active/原保护SHA相同，自有服务取消删再确认soft-delete、SDK退出。禁用后Agent零调用/全部外部MCP/正式IPC仍待验，见[MCP实际验收](MCP-REAL-AGENT-BROWSER.md)） |
| UI-SET-009 | user改聊天历史；密码弹窗空/不一致/显隐/取消，再成功改密码 | 校验聚焦/取消清字段；成功所有设备退出，新密码可登录 | 未完成（已有历史开关与弹窗各子项；补丁已集成，Orca错旧密码中文POST400及自然过期改密续期200均通过，旧密码拒绝/当前密码正常登录恢复原库/全部旧设备撤销已核对。最终包待复核，见20261010-root-sensitive-natural-expiry-real.json） |
| UI-SET-010 | 管理设备刷新，撤销其他设备再撤销当前；另一轮退出所有设备 | 他设备token失效、其他保持；当前/全体退出，旧refresh不复活 | 未完成（已有未过期撤销当前200返回login；补丁后自然过期撤销其他/全体退出均续期后只提交一次，独立他设备me/refresh401与数据库断言通过。过期撤销当前及跨页签迟到refresh仍待执行，见20261010-root-sensitive-natural-expiry-real.json） |
| UI-SET-011 | 管理员改应用名、Neo4j连接/secret，留空重存、测试与清除 | configured不泄漏值；测试已保存，清除停用，非管理员不能写 | 未执行 |
| UI-SET-012 | 管理员改startup后保存、展开active、重启；有env override场景 | restart_required/data目录/env优先正确，秘密不落startup | 未完成（原生准确数据路径、正常滚动和disclosure展开已显示active4/30/60/INFO；startup改保存、重启/env覆盖及最终包待执行，见settings-ec143bae-38fb-49ac-8616-0aff2337d84a原始树/截图） |
| UI-SET-013 | Langfuse API key保存留空/清除；追踪选项和本地配置保存 | 凭据不回显，采样/内容/trace开关持久化；clear停上报 | 未执行 |
| UI-SET-014 | 打开Langfuse：自动登录开/关/失败；轨迹授权链接点击 | 先验证再开，无失败空窗口；人工登录fallback，同origin/project约束 | 未执行 |
| UI-SET-015 | 故意使一个设置加载API失败，点重新加载 | 其他设置仍可用，错误明确可重试，不用失败空对象覆盖保存值 | 未执行 |
| UI-EVAL-001 | 公开180题选择准备，ready后刷新状态；准备失败再重试 | 后台准备/进度/失败真实，未ready不能运行 | 未执行 |
| UI-EVAL-002 | 知识库生成题，auto/manual/sample分别审核发布 | 已发布子集数量准确、拒绝与批准一致，未发布不可运行 | 未完成（原manual5题仅1/5失败，编辑/取消删/发布1题v1/创建删除v2已真实验证；新manual/simple5/5、5stop/849tokens、当前来源准确，已逐题UI来源审核发布5 approved/0 pending。auto/sample及最新版待验，见[EVALUATION-REAL-RECHECK](EVALUATION-REAL-RECHECK.md)） |
| UI-EVAL-003 | 设置主/对比分块、retrieval/Rerank/Answer/Judge，点运行 | 配置快照/实际pipeline可核对，主不重复入对比，运行锁表单 | 未完成（历史422保留；修复后v1仅分块recursive和新5题仅检索stored均真实200/0新增调用。唯一Ragas新5题recursive/no comparison/keyword/rerankfalse/原GLM Answer-Judge运行时锁表单、完成解锁，报告实际配置正确；其他配置及新版安装待验，见[EVALUATION-CHINESE-QUERY-BROWSER](EVALUATION-CHINESE-QUERY-BROWSER.md)） |
| UI-EVAL-004 | 全集3045点运行，先取消估算confirm再确认 | 取消零run创建，确认后后台严格全量；估算信息显示 | 未执行 |
| UI-EVAL-005 | 创建尚未返回run_id点停止、运行后点取消；失败/取消后继续 | 意图保留、run状态准确、已有完成项恢复，任务非页内假进度 | 未执行 |
| UI-EVAL-006 | 运行中离页/刷新再打开；完成后改表单 | active恢复轮询；结果配置/验证/新鲜度独立，变表单有提示 | 未执行 |
| UI-EVAL-007 | 下载统一报告/历史报告，再删除先取消再确认；报告404 | 私有范围/Blob JSON/文件名正确，404刷新提示，删除禁止跨空间 | 未完成（两份确定性与新5题Ragas历史均实际download并打开fresh JSON核sample/config/source/metrics；Ragas报告删除只取消、原行SHA保持。首次confirm阻塞工具失败与错误dialog命令保留；确认删除/404/跨空间及最终安装待验，见[EVALUATION-CHINESE-QUERY-BROWSER](EVALUATION-CHINESE-QUERY-BROWSER.md)） |
| UI-EVAL-008 | history加载失败点重试，查看缺指标、degraded/stale/partial | 缺值--而非0，状态与freshness/覆盖率/error不混淆 | 未执行 |
| UI-MOB-001 | 窄屏底部收集选目标，再主动拍照/选图，先取消后确认上传 | 未点击不访相机、未确认不上传；目标一致，卡片操作可触达 | 未执行 |
| UI-MOB-002 | 手机输入中文IME/Enter/Shift换行，软键盘开关，点显式发送 | IME不发送、手机Enter换行、输入/发送不被底栏遮住 | 未执行 |
| UI-MOB-003 | 手机点会话开关、打开旧会话、管理菜单与表单滚动 | 抽屉导航/触控/弹窗按钮可达，长内容不溢出屏幕 | 未执行 |
| UI-MOB-004 | 设置安装按钮：支持prompt与无prompt的Safari说明两种 | 用户主动安装，已安装隐藏，文案不承诺完整离线 | 未完成（Orca无prompt时实际展开Android/iPhone说明；遮挡缺陷经真实组件四尺寸与Orca分类点击修复。实际安装prompt及Safari/手机环境仍未验证） |
| UI-MOB-005 | PWA下载新壳时保留未提交输入/在途上传，断网再进深链 | 仅提示可延后、无自动reload/skipWaiting；离线壳不缓存私有API/SSE/报告 | 未执行 |

本checkpoint补充：CJK免费两报告/唯一45调用五题Ragas、真实MCP4/3353及WebSearch4/3846与两来源点击均只计具体子项；693核心/plain2/361前端与5cab Windows prepare0不替代GUI或最新安装。Root已实际导出72表/26文件/24媒体且原source不变，Windows restore/登录/D02/H与最新版artifact绑定/升级/安装生命周期仍待验；18+6守卫仅准备。38稳定组和A–J剩余用例/外部条件/最终清理未全PASS，Goal保持active，旧846/Hfreeze与所有失败不改写。
