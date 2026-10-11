# 当前进度

更新时间：2026-10-11 19:39（北京时间）。Goal active，无显式 token 预算。未提交、未推送、未发布。

最新事实：纯分块Worker、Workflow接入及初次发布批量写入已实现，分别有36项、4项及139项相关通过；全局序号读取最小优化61项通过。当前源码完整核心542/542、类型检查及构建全部退出0，前端333/333及构建退出0，检查前后源码一致。当前四万行无模型流程通过，最新采样处理根14.220秒、发布6.609秒；独立SQL计时确认FTS插入为主要热点，仍须复测真实响应。

Orca已实际验证取消/完成筛选、坏PNG重解析失败及自动刷新到9完成/2失败/3取消；解析记录修复后失败筛选2条、取消3条，错误中文且历史轨迹保留。阶段中文“阶段处理失败”和取消耗时深色文字也已通过真实点击、DOM及稳定截图复测。Orca五数值与Rerank已保存、离页再进入并恢复有效原值，模型SHA不变、usage98；原生相应子项及系统生效值展开也已验证。

371项源码Windows历史候选已经正式准备、打包及隔离升级，12表/数据/凭据保留；它不含本轮新修复。当前源码已正常重启浏览器核心PID3033028，旧Python worker与新源码不同，因此新的正式Windows准备在全新专用目录执行。全部页面、评测GUI历史下载及最终安装版交付仍未完成；原五题低分与未知请求保留。以下日期章节为各阶段历史，未执行项以最新矩阵和本段为准。

## 已完成事实

- 已完整读取用户 Goal 和开发规则；主业务迁移方案已授权。
- 已核查原 Electron 实际仍启动 Django，前端通过 HTTP/SSE；原工作区大量脏改动已记录，不能回退或从 HEAD 覆盖。
- 原源码 452 文件、差异、数据库/媒体/配置/解密材料已私有备份：`/home/liuxuedeng/.local/share/marlin-refactor/20261010-baseline`。
- 原数据库副本：4用户、2空间、2知识库、7文档、1400分块、46会话；有效模型配置为0。
- `python manage.py check` 在副本上通过；`frontend npm run test:unit` 140/140通过。这些是旧实现基线，不算新 TS 功能通过。
- Windows PowerShell、原生 Node/Python 可调用；Orca 客户端在线，runtime `1fd142ca-0664-4cfb-b5ea-4a8ca32de0c4`。当时尚未测试Electron安装版；最新安装事实见后续记录。
- UI/DATA/PARSER 三份基线已形成；105个前端API、2条SSE和69个UI用例已识别，尚未逐页点击。
- 新核心已采用精确锁定的 better-sqlite3 13.0.3 / Drizzle 0.45.4 / sqlite-vec 0.1.9 / MCP SDK 1.32.1。WSL GLIBC2.31与预编译库不匹配，已用本机C++20构建并实测SQLite/vec可用。
- 31表470列新SQL/Drizzle定义、同步写入、FK/事务/60位ID、兼容AES-GCM凭据已实现；非法JSON不会静默变为null或丢字段。
- 认证11项真实SQLite测试（含两个子进程刷新竞争）、模型16项本地HTTP协议测试已通过；独立解析器在无Django venv中22项Python、8项TS进程桥接测试通过。不是厂商/GUI/安装版通过。
- 旧数据库副本实际导入成功：4用户、2空间、2库、7文档、421图像、1400块、46会话、232消息、65Wiki页、11189用量记录、120任务；原始凭据只在核心解密验证。摘要见evidence/20261010-legacy-import.json。
- 隔离fixture的首次/重复导入、坏密钥/缺文件/错hash/未知版本拒绝、备份恢复均通过；实际完整副本的重复导入、44表备份与独立恢复也已通过。

## 后续完成的事实

- 队列27项、检索30项、设置18项与模型16项、知识域22项分别通过对应真实SQLite/进程/本地HTTP测试。知识域与检索联合52/52通过；不是厂商或UI通过。
- 开发入口直连 TypeScript 核心；最新实际 HTTP 组合18/18通过，包含认证、知识、文档、会话流、Wiki、Agent和外部集成。不是全部页面验收。
- 解析桥12/12通过，包括取消后等待实际supervisor退出、子进程继承管道、结果后的损坏尾帧拒绝；前端最新145/145通过。
- 业务缓存完整副本已纳入实际导入：2445文件、约1.071GB，耗时30647.723ms；重复导入4653.567ms，返回repeated=true。备份44表/2446文件，8517.988ms；独立恢复后核对所有表、文件和FK，备份后的验收修改不存在。详见MIGRATION及evidence。
- Orca 首次初始化实际重跑通过，创建专门验收管理员，初始化请求139.9ms；知识库创建实际提交319.8ms。其他按钮仍有工具报告点击但未触发DOM/API的情况，不计通过。
- 迁移副本7个文档的受控源文件读取及哈希核对通过。实际重解析完成，355分块，5954.621ms，其中本地发布3004ms；外部模型阶段因没有配置而跳过，不计模型通过。发现并修复索引单条更新扫描全语料的性能问题，最新检索36项通过。
- 对话/Agent/记忆与附件域最新39/39真实SQLite与受控HTTP测试通过，含独立子任务寿命、实际取消、进程退出、owner围栏、真实PDF/DOCX及视觉附件。当前没有真实厂商证据。
- 正式私有IPC设备模式与流传输5/5通过；独立TypeScript桌面子进程初始化/重启1/1通过；Electron运行时、来源边界及静态资源协议9/9通过。实际Electron窗口、托盘与安装版尚未通过。
- 前端连接同一核心的原生上传/流/二进制适配已接入，最新149/149单元测试及Vite构建通过；构建仍提示主包较大，待真实页面性能核查。
- Windows携带Node22.23.2已核对官方archive/executable SHA并保留许可证；实际WindowsSQLite3.53.4/sqlite-vec0.1.9可加载。
- 真实Windows对照确认Electron V8 15.2与Node22的advanced序列化不兼容，已替换JSON私有wire及严格字节DTO；真实进程3/3、运行时5/5通过。
- Windows Electron44.7.0修复后smoke实际退出0、页面挂载、正式IPC与TS核心响应正常，无HTTP监听。单次冷启动2512.984ms；可见窗口真实初始化后进入知识库，并点击用户资料和模型管理，核心持续运行。安装版、上传/下载/流及生命周期仍需验收。[启动记录](../refactor-evidence/20261010-windows-electron-json-smoke.json)。
- 已接入Graph/Evaluation/附件/Actor路由及文档hooks，实际应用HTTP/IPC限定组合22/22、typecheck通过；不等于各页面通过。
- 文档/Wiki/Graph/检索限定组合130/130通过，生产parser超时未改；继承管道/损坏尾帧测试以真实进度握手区分Python启动耗时，controlled clock不计产品延迟。
- 独立Windows Python3.13.16携带110项SHA锁定依赖，直接worker实际11格式、28边界及带空格目录搬迁通过，Django不可导入。裸环境SVG的Cairo DLL搜索目录缺失已修复；正式Windows Node→编译TS→Python链路25/25、进程边界7/7通过。[构建证据](../evidence/20261010-windows-python-build.json)、[TS桥](../evidence/20261010-windows-ts-python-bridge.json)、[取消与清理](../evidence/20261010-windows-ts-python-bridge-boundaries.json)。
- 评测核心16/16、Python边界6/6通过；共享隔离环境后真实Ragas与进程2/2通过。前端评测15/15、全单元162/162及构建通过。修复未知付费请求确认、新恢复ID、延迟轮询覆盖、有效题数、发布和重启恢复；受控HTTP计算不能替代真实厂商五题评测。
- Windows Ragas 的 asyncio 初始化与文件访问隔离冲突已修复；真实两题受控HTTP计算通过，仍不是厂商五题验收。[诊断与复测](../evidence/20261010-windows-ts-python-bridge-ragas-diagnostic.json)。
- 用户已在Windows桌面配置四模型，正常退出并重开后配置及会话仍保留。真实点击发送的GLM计算回复为391；对话调用6279ms、855 tokens，维护调用4977ms、873 tokens。Embedding/ReRank/视觉尚待真实调用。[无秘密用量记录](../refactor-evidence/20261010-windows-model-initial-call.json)、[实际回复](../refactor-evidence/20261010-windows-glm-live-answer.png)。
- 已在桌面真实新建隔离验收知识库，准备五份自编资料（中文空格路径、旧版冲突、表格与图像），尚未上传成功。[文件哈希及标准答案](../refactor-evidence/20261010-model-fixtures.json)。上传入口已改为原生button；实际Chromium键盘filechooser回归由RED转GREEN，前端163/163及构建通过，桌面最新资源已部署，仍需重开复核。
- 检索发现NULL seq_id的未索引分块被FTS误召回，已以真实SQLite回归RED→GREEN，相关39/39通过。Chat已接入Graph检索，实际应用缺Neo4j提示及空范围、评测路由和FTS限定组合5/5通过；均不是厂商或图谱服务通过。
- Orca控制页改用ThreadingHTTPServer后，真实点击和送达证据已确认；此前单线程服务器预连接造成的诊断不算工具故障。新产品页真实退出与登录完成（登录737ms），其余页面由实际业务结果逐项核对。[控制及产品操作记录](../evidence/20261010-orca-browser-parser-worker.json)。
- 最新Windows原生窗口实际选择五份资料并点击开始解析，五文档完成、向量模型五次成功（359–699ms），视觉OCR2473ms/描述3901ms且验证码、数量、日期与标准答案一致。真实问答的ReRank200ms、query embedding228ms；现行负责人/预算/代号回答正确，保留三条来源。四模型实际调用均已确认。[厂商与上传证据](../refactor-evidence/20261010-windows-live-upload-models.json)。
- 实际链路发现四份摘要失败、一次Wiki生成60014ms超时，Agent列文档误用不存在的is_enabled。辅助thinking及用量成功判定修复62/62，前端真实失败状态与完整单元164/164；文档工具真实SQLite20/20，类型/构建通过。已同步Windows可见QA的318 core与85 frontend文件并逐个核对SHA，后续厂商重解析及工具续答均已实际复核，详见最新记录。
- 首个实际NSIS构建成功，401698049 bytes，SHA256 adab54f7d5bdb3625a91eba75887cd633c79f333985d2635e8f0b1e6da27ff23；9项ASAR白名单、无Django/用户数据/Key审计通过。这是首次构建证明，尚不是最终源码或安装验收。[构建证据](../evidence/20261010-windows-nsis-build.json)。
- 引用定位和评测遗漏已完成源码修复及真实组件/HTTP/IPC回归，等待最终原生部署；Agent部分文档工具未收集实际引用，正在补齐。

## 最新实际结果（2026-10-10 15:45）

- 第二个实际Windows NSIS基线安装包401698923 bytes，SHA256 `1d431f64f9d9de54a2e3c169fc12d774ef2a439786ecec852e5ba84052b52ee7`，Windows164单元、构建、SQLite/FTS/vec/IPC及Python gate通过。它包含辅助thinking与Agent工具SQL修复，不含后续引用、评测、统计和媒体摘要修复，不能当作最终交付。
- 基线包已在专用中文空格目录 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用` 安装成功，installer exit0，应用及卸载器存在。安装170301.9354ms为单次观察。[安装记录](../refactor-evidence/20261010-windows-nsis-installation.json)。
- 安装版排除系统Node/Python的PATH后，正式协议smoke退出0，mounted=true/nodeExposed=false/nativeTransport=ipc/http_listener=false；单次启动1450.8846ms，11716.0315ms为含截图与退出的命令总时长。[安装版smoke](../refactor-evidence/20261010-windows-installed-smoke.json)。已实际打开并初始化独立验收账号，未改当前用户管理员密码；升级/卸载数据保留还未执行。
- Windows实际重解析《晨星A 交付计划.md》后，summary/questions/metadata和两Wiki页面均成功，root关闭36673ms；摘要2165ms、关键词问题4960ms、元数据7005ms，真实字段正确，不将厂商单次样本汇总成P95。[辅助回归](../refactor-evidence/20261010-windows-auxiliary-vendor-regression.json)。
- 修复后实际Agent列文档13ms、grep12–13ms成功，跨文档32/24/24批次、日期和地址正确。追加六题中表格、图像、缺失事实拒编、中文别名和政策事实正确；图像等仅有口头来源没有机器引用，不能计作完整通过。相似实体问答在记忆关键词阶段失败，主问答未开始。[六题记录](../refactor-evidence/20261010-windows-native-gold-extra.json)、[记忆失败](../refactor-evidence/20261010-windows-memory-failure.json)。
- 知识库处理中统计已按真实当前workflow job计数，保留本地FTS已发布状态，24/24、typecheck/build通过；媒体后处理改用真实OCR/caption且避免空输入付费和旧自动描述保留，四项专项通过。等待部署后的实际UI/厂商复测。
- 引用按钮/精确doc+chunk定位、实际可见抽屉焦点已修复；评测专用API、保存集复用/版本/题目编辑删除、逐题持久化和重启未知状态已修复。最终联合前端187/187、core类型/构建及实际HTTP/IPC专项通过。[评测证据](../evidence/20261010-evaluation-retention-parser-worker.json)。安装版和厂商五题仍待验收。

## 正在执行

- 根代理：当前核心完整回归、真实联合问答和剩余页面；完成当前修复批次后重新正式Windows绑定、打包及安装版GUI验收。已完成366源码包的升级核验，旧源码冻结解除。
- 浏览器四模型配置已通过正常认证与可信核心转移到专用空间；已真实上传MD/PNG、四角色调用及原问答来源定位。密钥未进入renderer或报告。
- 原生托盘退出与正常重启已经核对，小时与15分钟图表实际可见；尺寸、崩溃恢复及最终安装版剩余项继续执行。
- 原五题完成结果、旧未知调用和新的质量缺陷证据均保留，不重放已消费评测请求。

## 当前候选版的真实回归（2026-10-10）

- 已将当前前端、核心与桌面固定资源共435项同步到独立Windows QA目录并逐文件核对SHA，补带评测MT19937许可证；未复制或删除用户数据库、配置或解密材料。这是可见候选版更新，尚不是最终NSIS。[资源清单](../refactor-evidence/20261010-windows-candidate-refresh.json)。更新前维护停止有一次AccessDenied，后续精确路径只读检查确认原QA进程已全部结束；不将强制维护停止当作正常退出验收。
- 更新后实际进入知识库并恢复原有验收账户和五份资料；真实点击重解析此前有问题的图片、现行手册、失效旧版和CSV。四份文档及原交付计划现在均为completed摘要、pending=0，全部最新root结束，图像摘要正确包含ORCA-QA-7421/32/2026-10-20。新四次root分别30856/46427/33062/19373ms，不把工具观察时间计作产品延迟。[GUI及只读阶段/用量](../refactor-evidence/20261010-windows-document-vendor-regression.json)。
- 独立安装版专用验收账户已实际完成密码空值/不一致/取消/有效修改；修改后的新密码经只读哈希验证有效，旧设备已撤销，新设备在后续登录时创建。密码输入后已实际进入认证页面，但未捕获显式登录按钮点击，因此不假报此动作。[实际密码验收](../refactor-evidence/20261010-windows-installed-password.json)。设备管理入口和刷新已点击，当前与已撤销设备可见；主动撤销和退出所有设备仍待执行。[设备页面](../refactor-evidence/20261010-windows-installed-devices.json)。
- 独立正式Electron Langfuse链路已测试真实preload/IPC/私有子进程、受控NextAuth分片Cookie及窗口隔离、取消、配置变化、退出与导航边界。真实外部Langfuse尚未验收；本地受控服务不能计作厂商可用。[独立Windows gate](../evidence/20261010-windows-nsis-build.json)。
- 旧数据启用了Neo4j。已用迁移保留的真实空间service key正常认证，只读盘点失败为integration_connection_failed；WSL与Windows的默认Bolt端口均无监听，也无可控既有Neo4j实例。原图数量未知，不能写成空图或已迁移。保留受限只读归档与需正常用户认证的发布工具，不修改原库、原凭据或外部图数据。
- 共享核心已接原有空间/成员/密钥轮换/审计及固定embed协议；仅允许HTTP并保留Host/Origin/CSRF检查。冻结后根代理独立18/18通过，core typecheck/build exit0；不计作远程监听或GUI验收。[独立证据](../refactor-evidence/20261010-root-frozen-legacy-channel.json)。
- 相似实体问答已真实重跑成功：A/B公司、负责人及128000/12800元预算全部正确，有1条机器引用。图片问答有5条实际工具引用；展开后点击图片OCR“查看来源”，打开正确doc+chunk和预览。[事实及来源操作](../refactor-evidence/20261010-windows-model-vendor-regression.json)。十二类全部标准题仍未完成。
- 真实关键词读取没有相关度分数，UI却显示0.00；已改为只显示有效有限分数，保留真实0及有效数字字符串。实际Vue/Chromium回归RED→GREEN，前端199/199及构建通过；最终原生显示复核待执行。
- 此前Windows锁屏造成截图和键盘聚焦失败，历史失败完整保留。用户随后回复窗口在前台，19:47后实际恢复1280×860应用窗口；已点击打开密码弹窗、空值提交看到三条错误，再取消返回资料页。未输入密码、未提交密码修改或改设备/Key；这四个步骤只算候选版子项，不代表完整账户用例或最终安装版通过。Orca点击注册入口后也出现注册标题、按钮和确认密码输入。[历史锁屏](../refactor-evidence/20261010-root-unlocked-tool-state.json)、[新可见操作与截图](../refactor-evidence/20261010-windows-user-dialog-visible-recheck.json)。

## 核心集成审查与自动化检查

- 根代理完整核心测试430/430通过、0失败/跳过，382250.110953ms；桌面运行时12/12通过，11032.493201ms。核心全套完成时尚未包含下述Graph来源修复，不能作为修复后的全套证据。[原始TAP与范围](../refactor-evidence/20261010-root-full-checks.json)。
- 独立审查通过实际API复现：只改分块来源metadata，旧图先失效，但重复迁移仍恢复旧实体并绑定新来源。已对原归档和当前metadata作一致投影比较，只排除两个Graph派生关联字段；普通来源变更现在在外部读取前返回409 `legacy_graph_source_changed`。真实API回归先RED，修复后迁移13/13、相关Graph/Chat/Application组合53/53通过，typecheck/build exit0。[修复证据](../refactor-evidence/20261010-graph-metadata-regression.json)、[独立审查](../refactor-evidence/20261010-final-core-review.md)。
- Windows C核心198项源码快照、24/24与Runtime6/6、真实SQLite/FTS/vector/IPC和Python verify-only均通过，独立Langfuse Electron进程已正常结束。该C快照早于Graph来源修复，且未同步新Wiki/Markdown/引用显示，最终打包必须刷新；锁屏期间的边界集成不能代替可见窗口点击。[C记录](../evidence/20261010-windows-nsis-build.json)。
- Orca复用页的按钮点击和键盘工具虽返回送达，知识库/设置DOM仍未发生预期业务变化，另有runtime连接关闭。已保存未通过事实；没有创建假验收记录，也没有将此归因成已确认产品缺陷。[知识库送达](../refactor-evidence/20261010-orca-kb-input-delivery-root.json)、[设置操作](../refactor-evidence/20261010-orca-settings-parser-worker.json)、[Wiki入口](../refactor-evidence/20261010-orca-wiki-parser-baseline.json)。

## 前端与启动入口的后续复核

- Wiki独立页/图谱抽屉的编辑删除、目录和受控来源跳转已完成；内嵌只读语义保留。Markdown标准图片已支持合法URL和安全属性，真实Chromium图片加载/数学与代码隔离回归通过。此前冻结前端全套232/232、Vite构建exit0。[Wiki程序验证](../refactor-evidence/20261010-wiki-page-program-verification.json)、[图片回归](../evidence/20261010-markdown-image-parser-worker.json)。
- 独立实际组件审查发现三个加载状态残留：取消引用读取、清空pending Wiki搜索、取消唯一pending图谱类型。均保留旧响应围栏并明确复位loading；根代理正式RED→GREEN，引用组合37/37，追加Wiki两处后关联58/58，最新前端全套238/238、0失败/跳过及构建exit0。生产dist/index SHA `3e9e05e679066b0a361f6dd93e359dc17517b31ced5e745f268e0cf7e68bcba7` 已冻结。[引用回归](../refactor-evidence/20261010-citation-loading-regression.json)、[Wiki回归及最终前端](../refactor-evidence/20261010-wiki-loading-regression.json)、[独立复核及三处复测](../refactor-evidence/20261010-final-ui-review.md)。
- 根 `start:local` 已直连compiled TypeScript dev-server，`start:desktop` 使用严格Node launcher；核心/前端/桌面/startup检查分开。原startup专项44/44及真实npm参数转发通过，但独立复核发现报告只核hash未核正式语义、Electron执行分发漏hash和受控POSIX取消后代残留，正在修复，不能用原44项宣布最终入口完成。[启动计划](STARTUP-PLAN.md)、[复核](../refactor-evidence/20261010-final-startup-review.md)。Windows后代清理必须实际原生复核。
- 根代理已用真正 `npm run start:local` 启动当前编译核心和新隔离SQLite，4条实际HTTP请求确认runtime=typescript、版本0.7.0、service identity一致及未认证接口401；信号结束所属npm进程组后实际监听关闭、临时数据删除。2114.52844ms是该命令到绑定端口的单次耗时，不是Electron冷启动或页面延迟。[真实启动入口记录](../refactor-evidence/20261010-root-start-local-compiled.json)。
- 已为后续实际上传准备14份无用户数据资料，包含TXT、文本/扫描PDF、DOCX内嵌图片、XLSX公式、PPTX、XLS、SVG、HTML/JSON、坏文件/空文件及2.88MB文本；全部源与目标SHA一致、保留许可证。当前只是准备，没有计作上传或厂商通过。[文件与预期](../refactor-evidence/20261010-format-fixtures-prepared.json)。此前五文档厂商请求没有重复执行。
- README、桌面/Windows说明与开发验证规则已调整为当前TS链路；文档索引保留历史跨设备设计并标明当前桌面主线。README链接及本轮文档相对链接检查通过，最终报告仍明确未达到完整交付。
- 启动器修复后，Linux专项90项中85通过、5项仅Windows测试跳过，0失败；独立原生Windows5/5通过、0跳过。实际验证private JobObject取消/父提前退出时清理抗TERM后代、无关进程保留、stdout/stderr/退出码和原文参数，以及创建/分配失败不执行挂起子进程。该Node夹具结果不计Electron页面或产品延迟。launcher SHA `ee576cb58d9385fadb1600f183164f8e541b9284d8a3aed17ff4c6cc919c7078`，supervisor SHA `f647757e1310962feb1a89879433989a1ba03cf03ee7c88e5490169c49f0084e`；4份源码和6份原始日志SHA/size已再次核对。[最终稳定证据](../refactor-evidence/20261010-startup-review-fix-summary.json)、[独立4项最小复测及原生证据核对](../refactor-evidence/20261010-final-startup-fixes-recheck-parser-worker.md)。
- 正式构建入口相关单测Linux35项中33通过、2项Windows专用跳过；Windows35项中31通过、4项POSIX专用跳过，0失败，实际Job/junction/SQLite/FTS/vec/IPC/ASAR均运行。独立复核17项Linux及2项原生Windows通过，真实ASAR10资产/18worker和5个篡改负例通过，冻结源码未变化。不是新NSIS、安装、GUI或厂商验收。[Windows原始结果](../refactor-evidence/20261010-windows-repository-windows-unit.json)、[独立复核](../refactor-evidence/20261010-final-windows-builder-review.md)。
- 18:24再次只读查看实际QA窗口，辅助访问树存在但捕获像素仍为Windows锁屏，未发送输入；本次截图和临时树已删除，0项产品通过。解锁请求仍待回复，继续不依赖窗口的构建工作。[环境观察](../refactor-evidence/20261010-root-lock-screen-status.json)。
- 最终安装升级前已只读检查专用基线安装的数据：预期验收用户和知识库仍在，2设备、0模型，desktop_jobs/task_records均0、FK错误0、schema v1 checksum已保存；未读取密码/API Key或停止进程，未执行升级或卸载。当前用户配置4模型的可见QA是另一个数据目录，没有触碰。[安装专用数据预检](../refactor-evidence/20261010-installed-upgrade-readonly-preflight.json)。
- 新正式Windows `--refresh --prepare-only` exit0，360项实际源码及73项Electron分发一致；根代理独立核对当时全部360个源码SHA无差异。Windows前端238/238、0失败/跳过，228907.4419ms；正式Core24/24、12616.2785ms，生产Runtime6/6、4163.0318ms，SQLite/FTS/vec/IPC、Python11格式/110依赖及独立Electron NextAuth均通过。前端index仍为最终3e9e05...，Graph编译文件为5bbd57...；这些是构建与受控集成结果，不计手工GUI、厂商或安装通过。[正式准备](../refactor-evidence/20261010-windows-repository-prepared-build.json)、[完整gate](../refactor-evidence/20261010-windows-repository-gates.json)。
- 根代理用实际Windows固定Node启动源码CLI，正式目录marker为官方Python产生的CRLF，launcher此前仅接受LF，实际exit1并在Electron启动前拒绝有效构建；没有创建smoke数据、没有模型调用或用户数据改动。初次脚本SystemRoot大小写错误另存为fixture失败。已只增加严格LF/CRLF两种完整值，10种非法marker仍拒绝；对应受控回归先RED后20/20通过、0跳过。新launcher SHA `f4409c66da6a78ab721c790bb9e595c12671f80fd53752c5538ae586c2a49d8a`；真实Windows CLI须等新正式来源绑定后重跑，尚未计通过。[真实失败](../refactor-evidence/20261010-root-source-desktop-smoke-marker-failure.json)、[换行回归](../refactor-evidence/20261010-startup-marker-summary.json)。
- Python生产器漏加 `-B`，实际导入zstandard写出单个pyc，正式资源过滤排除它后导致完整runtime清单不同；旧NSIS内部构建exit0、总打包exit1，不能发布。修复仅加该参数，Linux36项34通过/2Windows专用跳过，原生Windows36项32通过/4POSIX专用跳过、0失败；真实解释器、installed FileMatcher、ASAR及模块/许可证/额外缓存负例通过。资源过滤、锁与审计断言保持原样，新的110轮子完整干净生产仍在执行。[真实打包失败](../refactor-evidence/20261010-windows-repository-nsis-red.json)、[两平台生产器回归](../refactor-evidence/20261010-windows-repository-python-producer.json)。
- 独立安装版的升级前备份已完成：只读SQLite在线备份先写入专用Windows本地目录，关闭连接后复制到工作区外0700私有目录，核对12表计数、验收用户/知识库、integrity=ok、FK=0及解密材料副本哈希。root在Linux再次独立核对；文件0600，未停应用或改原数据。首个直接向WSL共享目录写SQLite的脚本挂起、目标0字节，已核身份及创建时间后只停止该私有脚本并记录失败；不是产品失败。成功备份77.5538ms为单次脚本时长，不是产品备份按钮性能。升级/卸载仍未执行，完成的3份临时脚本已删除。[有效私有备份摘要](../refactor-evidence/20261010-installed-upgrade-private-backup.json)、[脚本首次失败](../refactor-evidence/20261010-installed-private-backup-first-attempt.json)。

## 已知风险与依赖

- 最新正式源码CLI实际exit0，内部启动1604.8697ms；mounted/private IPC/TS Core0.7.0正常。隐藏smoke PNG仅捕获背景，不能计作可见登录页；实际Windows GUI与安装生命周期仍需复核。[根代理实际启动](../refactor-evidence/20261010-root-source-desktop-smoke.json)。
- Final候选已在专用中文空格目录实际升级，NSIS exit0、单次installer命令349204.3079ms；安装后25279个runtime实体SHA及ASAR匹配、12表所有行和解密材料完整保留。第三次验收中的正式smoke/正常saved IPC认证实际成功，但后置进程检查拒绝，原原因未证实；恢复工具原字节绑定既有探针，零新API调用核对，仅正常refresh更新device_sessions，其余业务及密钥保留。随后实际卸载exit0、owned tree=0，40720.154ms为单次卸载命令时长，完整数据文件/12表/解密材料与新基线一致、protected四模型QA存活。重装正在执行，normal quit与可见GUI仍未计通过。[升级](../refactor-evidence/20261010-installed-code-upgrade.json)、[原失败保留](../refactor-evidence/20261010-root-installed-post-upgrade-third-failed.json)、[恢复核对](../refactor-evidence/20261010-root-installed-recovery-recover-post-upgrade.json)、[实际卸载保留](../refactor-evidence/20261010-root-installed-recovery-uninstall-retain.json)。
- SQLite必需文件路径已按锁定13.0.3真实prebuild布局修复，相关Linux26/26、Windows14/14与root独立5/5通过。随后正式refresh exit0、当前prepared44272/gates860d/manifest008229绑定361源码、73 Electron分发、25279 payload文件；Final NSIS候选exit0，SHA `1a9f6ccec8d154d9ed7019ab8b05416dc038e4c51ee23f4d816ca541268950bc`。升级、卸载和最终可见GUI尚未计通过。[路径修复](../refactor-evidence/20261010-startup-sqlite-prebuild-fix.md)、[正式候选包](../refactor-evidence/20261010-windows-repository-final-nsis-proof.json)。
- 五题gold在正常IPC认证的私有数据副本中创建、人工批准并发布，零付费准备usage126→126。实际仅POST一次run `def03505-f77e-453f-b847-80d29ee9acc8`；5Embedding、5ReRank、5回答和前三次judge成功，第四judge在60005ms超时，任务interrupted/result_unknown，未完成题0/5，没有指标或可下载报告。未知账本保留且没有自动重发。只读诊断确认不是用户取消、lease到期或Ragas worker总预算到期；默认model_timeout=60秒，合法配置变更后原run的模型签名将不再匹配，不能绕过该围栏。[真实准备](../refactor-evidence/20261010-five-gold-final-preparation.json)、[唯一厂商运行原始结果](../refactor-evidence/20261010-five-gold-final-paid.json)。
- MCP受控本地服务已通过真实Core/官方SDK的23/23协议检查，工具发现、20+22=42、中文回显与会话关闭有实际结果；Orca自有服务添加、编辑、禁用、启用、刷新保持、取消删除和确认删除均已观察，SQLite确认仅该资源软删。该服务无Key，不能证明既有Key留空保留；GUI Agent调用仍待执行。[真实协议](../refactor-evidence/20261010-local-mcp-real-core-parser-baseline.json)、[实际页面CRUD](../refactor-evidence/20261010-root-orca-mcp-crud-real.json)。
- Orca专用账户历史开关关闭→保存→刷新仍关闭→开启保存经页面与SQLite核对；密码空值/不一致/错误旧密码/显隐/取消清空已实际操作。重新登录后改密POST200，新密码有效、旧密码无效，旧两设备password_changed；旧密码登录401、新密码点击登录恢复原库。首次改密和撤销其他设备的失败现在均有实际401与access到期证据，不能计成功；重新登录立即撤销其他/当前设备均200，第二设备access与refresh均401。两处英文提示及续期缺口待正式修复与复测；真实用户密码和设备未触碰。[账户子项](../refactor-evidence/20261010-root-orca-account-history-password-real.json)、[续期审查](../refactor-evidence/20261010-sensitive-session-readonly-review.md)、[第二设备失效](../refactor-evidence/20261010-root-orca-other-device-check-revoked.json)。
- 最新Orca注册包含密码不一致校验和正常提交，个人空间/owner关联与新库均经只读SQLite核对；置顶、复制、取消删除、确认仅删除自己的空副本已逐步观察，原库保留、关联残留0/FK0。跨设备、重启和非空关联清理仍未验证。[注册与新建](../refactor-evidence/20261010-root-orca-registration-kb-create.json)、[实际库操作](../refactor-evidence/20261010-root-orca-kb-pin-copy-delete.json)。

- 根代理已制作四模型QA的另一份私有静态副本：Windows父目录ACL仅当前用户/SYSTEM/Admin，在线SQLite快照和7份业务文件哈希、12表计数、integrity/FK独立核对通过；5资料/19分块/28Wiki、四有效模型，另有1条软删模型记录。原QA只读，未复制Chromium profile、未输出Key、未调用模型；下一步通过正常保存IPC登录/refresh权限链核验五题机器来源。准备不算厂商评测或GUI通过。[副本准备](../refactor-evidence/20261010-real-vendor-evaluation-private-copy.json)。
- root实际Windows Node/编译Core预检exit0，正常IPC `auth/me`401后通过保留refresh完成200，未取出token或输入密码；5doc/5gold机器证据及四角色/index ready，fetch=0、usage126→126，私有Job正常清理。五参考答案已按当前6份canonical/codepoint原文切片人工核对；尚未创建、发布或运行数据集，1330.3969ms只是预检命令时长。[正常认证与gold预检](../refactor-evidence/20261010-real-vendor-evaluation-preflight.json)、[实际执行](../refactor-evidence/20261010-real-vendor-evaluation-preflight-execution.json)。

上述“尚未创建数据集”等条目记录此前准备阶段；最新五题创建、发布及唯一失败运行以上方真实运行记录为准。已消费的18份临时脚本分两批精确清理，活动恢复工具及私有认证材料仍保留到验收完成，不据此声称最终清理已完成。[第一批](../refactor-evidence/20261010-root-consumed-temporary-script-cleanup-1.json)、[第二批](../refactor-evidence/20261010-root-consumed-temporary-script-cleanup-2.json)。

最新安装恢复：同一Final安装器实际重装exit0、156414.643ms为单命令时长；25354安装文件及25279 runtime库存一致，12表所有行、全部数据文件及解密材料精确保留，四模型QA仍活。当前最后的post-reinstall正式smoke/正常认证正在执行，仍保留源码冻结。[重装收据](../refactor-evidence/20261010-root-installed-recovery-reinstall.json)。

最新设备操作：Orca全体退出先因access自然过期401，重新正常登录后实际POST200并返回login，独立只读核本账号所有设备已撤销；原知识库完整、0模型调用。迟到refresh跨页签复活及修复后的过期操作仍待验收，整组不计通过。[设备真实操作与只读核对](../refactor-evidence/20261010-root-orca-device-management-real.json)。四文件中文提示补丁与RED/63相关/244完整单测日志已原字节归档，尚未应用。[隔离文案交付](../refactor-evidence/20261010-password-error-ui-isolated/REVIEW.md)。
- Ragas运行期字节码缺陷已只增加CLI `-B` 修复；新真实import回归Linux先RED后GREEN，实际Windows当前编译Bridge和独立copied helper也GREEN，完整路径/SHA库存不变、0 pyc。相关评测32、队列27、桌面进程3及parser5通过，core类型/构建通过；root独立新增回归1/1及源码/编译哈希核对通过。不是厂商指标或GUI通过；Python环境变量在该Windows版本实测也能禁缓存，历史推断已纠正。[两平台正式修复与原始证据](../refactor-evidence/20261010-ragas-bytecode-fix-verification.json)。
- 新干净Windows准备首次失败：锁定Electron44.7.0包没有postinstall，`npm ci`成功却没有shell。正式builder已增加固定官方install.js步骤，Linux37项35通过/2跳过、Windows37项33通过/4跳过，root两个相关pipeline回归通过；锁及桌面资源白名单未改。之后正式refresh实际exit0，前端238/238、Core24/24、Runtime6/6、SQLite/IPC、Python11格式/110依赖及owned Electron gate全部通过、0缓存。其原始日志/报告已保存，不能以prepare成功代替实际启动。[干净准备失败](../refactor-evidence/20261010-windows-repository-final-clean-red.json)、[官方installer修复](../refactor-evidence/20261010-windows-repository-electron-install.json)。
- 此前正式stage的真实源码CLI exit1，唯一缺项为硬编码的`better-sqlite3/build/Release`路径；历史失败及3564.7806ms失败命令时长保留。当前锁定13.0.3实际prebuild路径已修复并重新正式绑定，真实CLI exit0见本节最新证据；没有手改payload或manifest。[历史失败](../refactor-evidence/20261010-root-source-desktop-smoke-native-layout-failure.json)、[精确缺项](../refactor-evidence/20261010-root-source-launcher-payload-diagnostic.json)。
- Orca开发核心旧owned进程已按精确PID/argv/exe核验，以pidfd只停止该进程并确认退出；最新源码Core已重新运行，正常health/capabilities均200、runtime=typescript。四模型WindowsQA未触碰，0模型调用；停止541.288ms是命令观察时长。[刷新证据](../refactor-evidence/20261010-root-browser-core-refresh.json)。
- 安装登记已只读核对HKCU/HKLM两种视图：注册路径和卸载器仅指向专用中文空格安装目录、没有相同GUID机器安装；所有当前Marlin及安装目录内Node进程都在该目录树中，PowerShell/CIM可用。首个脚本将“目录内”误写成“直接父目录”，没有执行安装或停进程；按实际bundled Node子目录修正后通过。实际升级前仍会再次检查这些边界。[登记和进程预检](../refactor-evidence/20261010-installed-registry-preflight.json)。

- 四模型已由用户在Windows桌面重新配置；密钥仅由核心管理。四角色、摘要/Wiki及Agent文档工具已有实际修复回归，五题厂商Ragas、其余标准问答及最终页面复核仍待完成。
- 已纠正此前“46条session为空owner”的错误记录：源与导入副本46/46精确关联原用户，40条本来软删、6条未删。独立副本实际Auth→Chat核验6条历史可读、22条可见消息，同空间其他账户6/6被404拒绝；未重分配会话，未修改原密码或凭据。
- Electron首次失败已修复并实际复测；基线安装与正式smoke已通过；最终包、完整生命周期及逐页操作尚未完成。
- 旧 Django 历史迁移含不可逆全量删除，导入不能重放旧迁移。
- 向量 seq_id 使用60位，TS不得转为不精确 number。
- SVG字节/MIME规范化、Windows直接worker/Cairo及正式TS bridge已实际回归。
- 扫描 PDF 当前通过 VLM 后处理，没有本地 OCR 实现证据；不能误报已有 OCR 能力。
- 无 LibreOffice/soffice 的 Linux 环境下旧 doc/ppt 格式转换未验证。

## 下一步

继续实际大文档响应/快速重启恢复及新的正式Windows绑定。继续文档分块/标签/移动、系统设置、评测历史与实际下载、安装版GUI及生命周期；已成功的三个辅助请求和原五题不无必要重跑。当前371包是已验证的历史候选，不能代替新修复交付。剩余阶段见 [PLAN.md](PLAN.md)、[分块接入](CHUNKING-WORKER-INTEGRATION.md)、[批量初次发布](INITIAL-PUBLICATION-BATCHING.md)、[解析记录状态](PROCESSING-RECORD-STATUS.md)、[关键词召回](KEYWORD-RECALL-PERFORMANCE.md)。

## 当前源码最终自动化检查与真实显示（2026-10-11 19:39）

- 核心完整542/542，0失败/取消/跳过，TAP442169.349ms；类型检查15980.499ms、构建19961.792ms均退出0。前端333/333，0失败/取消/跳过，TAP98635.946ms；构建46453.607ms退出0。全部阶段源码SHA前后一致，以上是检查命令时间，不能替代页面延迟。[核心原始结果](../refactor-evidence/20261011-root-current-core-checks/checks.json)、[前端原始结果](../refactor-evidence/20261011-root-current-frontend-checks/checks.json)。
- Orca真实失败过滤、展开坏PNG后显示“文件读取: 阶段处理失败”且无LIVE；取消JSON的条内耗时已显示深色。两张稳定截图实际检查，usage98和模型SHA不变。[681–690实际步骤](../refactor-evidence/20261011-root-trace-error-display-real.json)、[显示设计](TRACE-ERROR-DISPLAY.md)。
- 正常停止旧专属Core且确认无运行任务，再启动当前源码PID3033028；health正常、源码与542检查一致。service_id来自保留的数据目录，进程重启并不会改变它。[精确停止](../refactor-evidence/20261011-root-browser-final-source-graceful-stop.json)、[当前实际运行](../refactor-evidence/20261011-root-browser-current-source-running.json)、[已用检查脚本清理](../refactor-evidence/20261011-root-current-checks-helper-cleanup.json)。
- 正式Windows旧worker与当前registry.py不同，按构建规则不可refresh复用；新专用目录执行完整干净prepare，尚未计通过。[当前来源冻结](../refactor-evidence/20261011-root-current-worker-windows-build/source-snapshot.json)、[唯一prepare](../refactor-evidence/20261011-root-current-worker-windows-build/prepare-attempt.json)。

## Worker集成与Orca实际回归（2026-10-11 19:20）

- 非语义纯分块由Workflow拥有并在close/cancel时等待线程退出；语义/自定义token计数保留核心原路径。真实Worker/queue/SQLite专项先4项RED，再4/4通过；源与编译Windows纯Worker也已独立核对。没有宣称算法Worker承担数据库写入。[集成证据](../refactor-evidence/20261011-root-worker-bulk-local-integration.json)、[Worker边界](CHUNKING-WORKER.md)。
- 当前完整四万行fixture3.2MB、1600父/11200子、末行FTS事实正确，0模型。单次CPU诊断subtest15627.976ms、根14220ms/发布6609ms；主线程加权采样与ESM loader线程分开。额外分SQL诊断175次清理138.735ms、插入3221.971ms，不将采样或测试总时长作为页面延迟，不为清理的小份额改变写入语义。[当前原始流程](../refactor-evidence/20261011-root-pub-current-profile/command.json)、[只读分析](../refactor-evidence/20261011-root-pub-current-profile/profile-analysis.md)、[SQL计时](../refactor-evidence/20261011-root-fts-sql-timing/command.json)。
- 坏PNG实际重解析docreader/root在约1.9秒失败并结束，0running span；页面自动变为9/2/3，实际失败筛选显示两坏文件。原已发布数据保留，usage98/模型SHA不变。[真实步骤与结果](../refactor-evidence/20261011-root-document-current-status-ui.json)。
- 解析记录真正点击过滤和展开，当前失败/取消优先于旧parse completed；两失败、三取消及原历史轨迹确认。发现阶段仍显示stage_failed，补充中文文案和取消时长对比度；最终该提示及安装版复测尚未计通过。[真实状态复测](../refactor-evidence/20261011-root-processing-record-status-ui.json)、[组件回归](PROCESSING-RECORD-STATUS.md)。
- Orca检索五参数10/.15/.3/5/.3→11/.2/.35/6/.35保存并离页再进入保持；Rerank关闭保存再进入仍关闭。恢复原有效六参数、只读SQLite核对、模型SHA不变，零付费。正常GUI保存把原空JSON写成显式默认字段，不声称原始字节相同。维度/重建、websearch及最终安装版仍待执行。[完整真实操作与SHA](../refactor-evidence/20261011-root-browser-retrieval-real.json)、[已用临时脚本清理](../refactor-evidence/20261011-root-browser-roundtrip-script-cleanup.json)。

## 当前状态与原生设置复测（2026-10-11 18:15）

- 前端当前状态、代际围栏和单在途轮询23项通过；完整326/326、0失败/取消/跳过，82278.648ms，构建退出0。首次全套中的Wiki测试夹具拆分UTF-8失败有独立RED/GREEN，未放宽产品断言。[完整原始检查](../refactor-evidence/20261011-document-status-review.json)。
- 当前工作流状态与筛选/计数统一，真实SQLite认证空间RED后32/32、类型检查通过；原始已发布正文、parse_status与FTS保留。Orca实际DOM已显示10完成/1失败/3取消及空源提示，但点击筛选、坏PNG重新解析和自动刷新仍待核对。[状态设计](DOCUMENT-STATUS-FILTER.md)、[32项证据](../refactor-evidence/20261011-root-document-status-filter-regression.json)。
- 原生QA五个检索数值保存后重新进入页面保持；Rerank关闭/保存/重新进入仍关闭，随后开启/保存恢复。原生只读SQLite核原六参数恢复、全部模型SHA不变、usage126且active0。系统页实际正常滚动到disclosure并展开4/30/60/INFO；startup保存/重启/env覆盖与最终包仍未验。[实际步骤与完整SHA](../refactor-evidence/20261011-root-native-retrieval-system-partial.json)。
- 当前浏览器独立核心PID2882072/session83748/data-root为20261010-browser-qa；旧PID2822897仅精确SIGTERM且确认退出、任务均0、usage98。Orca普通snapshot有连接关闭；有界`exec snapshot -i -d 3`已成功，但业务操作仍以实际请求和数据核对为准，不把click回执计通过。[精确停止](../refactor-evidence/20261011-root-browser-status-filter-recall-stage-stop.json)、[最新原始快照](../refactor-evidence/20261011-browser-model-page/583-root-browser-bounded-interactive-snapshot.json)。

## 最新集成与安装后置核对（2026-10-10 23:10）

- 续期与中文提示补丁已集成，12个目标文件的新SHA全部匹配；原字节私有备份保留，未覆盖无关工作区改动。根代理前端全套300/300通过、0失败/跳过，53534.859489ms。安装包和可见原生QA仍为此前候选，不能将源码单测计作正式包通过。[集成收据](../refactor-evidence/20261010-root-sensitive-ui-integration.json)、[实际完整TAP](../refactor-evidence/20261010-root-sensitive-ui-full-unit.tap)。
- 重装后原smoke和saved IPC认证均成功（me/知识库200），随后进程计数1触发严格检查失败，失败收据保留；未重放认证、模型或生命周期操作。新的独立只读核对确认前后进程计数0、25354安装文件/25279 runtime库存一致，11张其他业务表和解密材料精确保留；device_sessions正常refresh发生变化，不能称全部12表或所有数据文件仍与认证前逐字节一致。核对期间数据未变、integrity/FK正常、四模型QA存活。原失败原因仍未证实，不计正常托盘退出或可见GUI通过；旧产物的源码冻结已解除。[严格只读后置核对](../refactor-evidence/20261010-root-installed-post-reinstall-postconditions/readonly-postconditions.json)、[原失败](../refactor-evidence/20261010-root-installed-post-reinstall-postconditions/post-reinstall.json)。
- Orca已通过正常界面验证错误旧密码登录401及中文提示，再用当前验收密码正常登录恢复原库；等待access自然到期后复测敏感操作，不调整系统时间或数据库到期字段。[真实中文错误提示](../refactor-evidence/20261010-root-orca-owned-field-8fee931c-4fe8-42af-a0c6-716d651cbf32.json)。
- 可见四模型QA的模型页裁切已复现；UI-011浏览器回归在1280×860测得排行右边1279、内容右边1207而失败，正在修复。自动化使用真实Settings组件与CSS、确定性API替身，不能替代原生或厂商验收。[实际原生观察](../refactor-evidence/20261010-root-native-model-settings-observe.json)、[布局RED](../refactor-evidence/20261010-model-settings-layout-red.tap)。

## 最新真实回归与正式准备（2026-10-11 00:05）

- 自然access到期后，Orca改密、撤销其他设备、退出全部设备均出现真实 `me401 → refresh200 → me200 → mutation200`，成功业务请求各一次。只读前置确认refresh仍有效，后置确认全部旧设备撤销/其他设备失效/原库保留；未修改系统或数据库时间，未触碰真实用户。操作网络跨度单次1612.2/644.9/653.6ms，含浏览器调度与认证请求，不计工具等待或P95。全体退出第一次click零请求保留为未提交，随后焦点确认按钮Enter才提交。[三项实际回归](../refactor-evidence/20261010-root-sensitive-natural-expiry-real.json)。跨页签迟到refresh和过期撤销当前设备仍待执行。
- 布局修复的真实组件四尺寸回归及前端全套301/301、构建通过；可见QA已复制最新85个前端资源，窗口尚需正常重启后复核。原生截图证实模型缓存图已切到小时，旧排行裁切仍为历史已加载资源。[小时实际画面](../refactor-evidence/20261010-root-native-model-ui-caefd18e-159d-4802-ac3f-3a85efccfaa4.png)。
- 评分预算补丁主仓库typecheck/build exit0、相关26/26通过；新Windows9/9通过、0失败/跳过，使用正式携带Python、真实HTTP/SQLite/取消与恢复夹具，限制loopback且零厂商请求。模型60秒超时、thinking、指标、签名及旧未知账本未变，五题run仍0/5。
- 最新正式 `--refresh --prepare-only` exit0、760.7469514秒；366项当前源码与prepared/gates/payload一致。Windows前端301/301（219858.5348ms）、Core24/24、Runtime6/6，SQLite/FTS/vec/私有IPC、Python11格式/110依赖及受控Electron NextAuth均通过；原始10文件已按字节与SHA归档。这些检查不代替厂商或手工页面。[正式准备与新增Windows测试](../refactor-evidence/20261010-root-formal-integrated-prepare/archive.json)。首个准备失败因构建Node归档尚未解压完整，未运行前端测试；完整官方2032文件核验后成功，原失败保留。[环境诊断](../refactor-evidence/20261010-root-formal-refresh-incomplete-build-host/diagnosis-and-complete-host-verification.json)。
- 标题栏关闭后QA主窗口实际hidden、5个所属进程仍活、无运行任务、模型记录哈希不变；只算关闭后后台状态。托盘箭头正常UIA Invoke后，初次观察因PowerShell把null窗口标题封送为空字符串而未找到overflow；独立只读已找到可见真实overflow，仍需实际Marlin菜单退出及退出后进程/数据断言。[关闭后实际状态](../refactor-evidence/20261010-root-visible-native-lifecycle-after-title-close.json)。

## 真实质量缺陷与页面修复（2026-10-11 13:20）

- 原五题实际5/5、coverage1；faithfulness约0.956但relevancy约0.387、context precision约0.2，前四题缺手册证据。10个可检索分块只有3个旧指纹有效。保留实际低分及未知请求，不将运行完成视作质量通过。[真实五题归档](../refactor-evidence/20261011-root-five-gold-integrated/archive.json)。
- 指纹限定嵌入输入及来源身份，来源变更仍拒绝，已知失效在query embedding前明确降级。两轮真实SQLite RED后53项相关通过；Orca重解析后7/7有效，辅助状态更新后仍ready。[设计与真实复测](RETRIEVAL-REPAIR.md)、[检查原始日志](../refactor-evidence/20261011-root-retrieval-pwa-repairs/checks.json)。
- 真实问题生成1022/1024 completion用于reasoning、model_output_invalid。对三个短辅助任务采用现有low策略后实际生成5题，4次模型调用成功，完整任务8446ms；问题生成1750ms、447 tokens。普通对话设置未改。[设计](AUXILIARY-POLICY.md)、[实际调用](../refactor-evidence/20261011-browser-model-page/146-root-short-auxiliary-retest-db.json)、[索引保持](../refactor-evidence/20261011-browser-model-page/147-root-index-after-short-auxiliary-fix.json)。
- 安装提示按正常布局占据空间，四尺寸点击回归及前端302/302通过；Orca ReRank/Embedding/视觉实际分类切换，安装说明展开后shell与账户入口仍在视口内。[设计](PWA-LAYOUT.md)、[实际布局](../refactor-evidence/20261011-browser-model-page/142-root-pwa-real-layout-readonly.json)。
- QA真实托盘退出后全所属进程0，正常重启恢复原账户四模型；小时与15分钟选择都有实际原生画面、排行完整。[正常重启](../refactor-evidence/20261011-native-model-page/restart-proof.json)、[15分钟原生画面](../refactor-evidence/20261011-native-model-page/root-980264e8-d7d4-4afb-81f6-3ac5a148c673.png)。
- 366源码包实际NSIS升级exit0，单次installer命令388258.982ms，25355安装文件/25280 runtime完整匹配，12表、数据文件、解密材料精确保留、integrity/FK正常。它早于本轮新修复，不是最终交付包。[实际升级](../refactor-evidence/20261011-root-integrated-installed-code-upgrade.json)。

## 当前完整检查与实际页面复测（2026-10-11 13:44）

- 当前源码核心完整445/445、0失败/取消/跳过，409134.884962ms；日志原字节、9份修复源码SHA已绑定。该命令时长不是页面或厂商延迟。[完整检查](../refactor-evidence/20261011-root-retrieval-pwa-repairs/current-core-full-results.json)。
- Orca知识库入口只发送一次联合题，实际后台回答24380ms、7次模型请求全部成功，4511 tokens；四事实正确、5机器引用。正常点击分别打开手册政策分块和图片描述分块，原图1000×440已加载并可见。[事实与来源核验](../refactor-evidence/20261011-browser-model-page/185-root-policy-image-live-answer-proof.json)、[图片来源画面](../refactor-evidence/20261011-browser-model-page/184-root-image-source-final-visible-screen.png)。
- 原生QA 1440×900排行完整；1024×768排行换行、正常滚动、ReRank实际分类生效，密码弹窗字段及按钮均可见并实际取消。窗口恢复1280×860，4有效模型及历史软删行SHA不变；Windows DPI96，125%/150%未验证。这些不是最终安装包验收。[尺寸记录](../refactor-evidence/20261011-native-model-page/resize-1440.json)、[弹窗](../refactor-evidence/20261011-native-model-page/root-9e27bcd4-0dd5-481a-a062-fd4d2e1cedb4.png)、[恢复后数据核对](../refactor-evidence/20261011-root-current-native-054049069302.json)。
- 正式刷新/打包使用官方Node22.23.2和既有完整校验的依赖，368项源码冻结；prepare已开始，尚未把它记为通过。[来源快照](../refactor-evidence/20261011-root-repaired-windows-build/source-snapshot.json)、[唯一准备尝试](../refactor-evidence/20261011-root-repaired-windows-build/prepare-attempt.json)。

## Wiki及记忆最新真实验收（2026-10-11 15:33）

- Wiki编辑框无上限自动增长，1289×659中保存按钮bottom834.8，正常滚动仍无法到达；按实际TDesign API限制12行后bottom592.8，正文内部滚动且完整保存。真实组件两尺寸先RED后2/2，前端308/308、86293.037ms及构建exit0。[布局设计](WIKI-EDITOR-LAYOUT.md)、[原始检查](../refactor-evidence/20261011-root-memory-context-wiki-checks-v2/checks.json)。
- Orca手动页面创建版本1、编辑版本2、刷新后正文保持；搜索、目录、缺失链接警告、表格/代码/公式/真实1000×440图片与脚本不执行均核对。删除先取消保留，再确认仅该页软删版本3；原12个生成页面的正文与来源未变。来源按钮实际定位手册服务政策分块，最新解析记录完整结束。[综合只读断言及真实步骤](../refactor-evidence/20261011-browser-model-page/407-root-memory-wiki-real-verification.json)、[真实图片](../refactor-evidence/20261011-browser-model-page/366-root-wiki-real-image-visible-screen.png)。
- 结构化契约修复后六次调用成功但新会话答“不知道”；能力与主题匹配修复后能召回却误认旧代号最新。两种失败保留。新增原始用户发言/时间依据后，同一问题在新会话真实回答最新MX-MEM-CONTRACT-9653并识别错误转述；后台stored，三调用2027/21972/4110ms，回答24220ms，3588 tokens。远程图状态forbidden，不计Neo4j通过。[设计](MEMORY-AUXILIARY-POLICY.md)、[62项相关检查](../refactor-evidence/20261011-root-memory-chronology-checks/checks.json)、[真实事实及用量](../refactor-evidence/20261011-browser-model-page/407-root-memory-wiki-real-verification.json)。
- 371源码已由官方构建入口开始刷新，尚未计Windows准备或安装通过。打包前必须核对当前459项完整结果与源码SHA。[新源码冻结](../refactor-evidence/20261011-root-memory-wiki-windows-build/source-snapshot.json)、[唯一prepare尝试](../refactor-evidence/20261011-root-memory-wiki-windows-build/prepare-attempt.json)。
- 最新完整核心459/459、0失败/取消/跳过、410196.753ms已实际exit0并按原字节/SHA归档，解锁正式打包的核心门禁；不是Windows安装或页面延迟。[最新完整检查](../refactor-evidence/20261011-root-memory-chronology-full/checks.json)。
