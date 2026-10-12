# 评测工作台修复后真实复验

2026-10-12。Goal仍active。本说明记录独立Orca评测页的真实复验，不覆盖原失败或主进度。当前已完成旧单题门槛、一次真实5题生成、逐题来源审核与发布。合法纯图片造成的仅分块422已修复并在新核心实际复验200/0新增模型调用，真实历史JSON下载后已打开核对。但旧单题及新五题的完整中文问句均0关键词候选，根代理已暂停尚未启动的付费Ragas，待召回问题解决后继续，不能将流程completed当质量通过。

## 范围与安全边界

使用既有独立Orca页签`22e0e212-30aa-4945-8a3d-7176cdfffdff`，每条typed业务命令固定GUID，不操作根代理page0或正式Windows窗口。首个PID1064192已正常停止，根代理恢复为PID1171965、service_id `dc927b55-ca0f-491f-9fa5-6ffea5936298`；本次源码修复须再由根代理有序切换，不能把此PID当新修复已加载。专用验收账号`orca-page-qa-20261010`，空间2。必要时只能正常GUI登录，私有凭据经stdin传递，不记录密码、token、请求headers或模型Key；本轮未读取或输入登录秘密。

授权仅一次5题、人工审核、事实问答生成，来源知识库`86f94109-c3f2-4cba-819e-d7bfdea42709`。这一次已消耗5次成功调用，禁止再次生成；既有单题版本1和空草稿版本2保留。根代理随后明确授权新5题发布集的一次正式Ragas：recursive、无比较、keyword、Rerank关闭、既有GLM Answer/Judge，最多65新增用量行、最长30分钟，超限GUI停止，失败或unknown不得重试、恢复或另建run。正常45–65请求上界来自根代理对executor/index/worker的源码推导，不是页面估算或厂商账单；实际私有5题页面没有费用估算入口或确认弹窗，根代理已明确允许核对配置后仅点击一次运行。仅检索及其他付费按钮仍禁止。

另可对原单题已发布版本1执行一次仅分块，先实际核对表单：主策略recursive、对比策略空、检索keyword、Rerank关闭。`evaluation/deterministic.ts`只在非keyword、包含semantic_parent_child/auto_parent_child时配置embedding，只有启用Rerank才配置reranker；该精确组合不创建厂商绑定，`isolated-index.ts`也不会重建向量。不能把默认自适应父子块/混合检索的仅分块称免费。执行后应核对真实历史、报告下载JSON、来源/config及未运行的RAG指标；不将确定性报告当Ragas质量通过。

## 只读准备

[GUI前公开认证与数据快照](../refactor-evidence/20261012-evaluation-real-recheck/001-before-gui-public-auth-and-data.json)通过SQLite `mode=ro`、query_only和同一读事务取得，不包含认证token/digest。最新设备access在`2026-10-11T22:47:59.963Z`到期，但设备未撤销，idle/absolute期限尚未到，最新refresh未消费且仍有效。因此根页1246回到login不能直接解释为整段会话自然到期；待GUI释放后读取原页面ResourceTiming、公开mode和CSRF时间戳，区分正常access轮换与实际失败。暂不修改认证、不重启核心。

当前四模型完整行摘要SHA `13479f65d09d6fe411e46e403e7bccd134970d48f8a67a41d14ca7f24a0946f4`，vault Key文件SHA `1dfc55e984d6f848395d93ac327ce9c6f5fbcfd997bcf89b9fd2d96c9d2238f5`，仅输出hash。旧published版本1 `2f99f534-5d8a-45b8-ba67-3ddd87f740d5`的完整行SHA `309c7d2ad33670d23fe470220987042af2bbe835f38eb7f9a22c1021a11e26a3`；旧空草稿版本2 `24e9e43f-742d-4de1-99d5-fb33e7835dc8`为`463e194b7aa1ba248d49db2a5d432fe97181bc999134cc46f2725445b960a34c`。末次须用相同序列化算法比较，不能混用其他记录的hash算法。

完整读当前generation、thinking、usage-audit、deterministic、isolated-index、Evaluation组件、前端认证transport/store/router及HTTP认证桥。最新生成按已核厂商endpoint采用auxiliary thinking on/low、maxTokens4096；其他不需强制思考的路径保留1024。循环单题一次，不自动重试；finish_reason按实际返回值枚举写入用量审计。旧失败记录没有厂商原finish_reason，不能倒推其已被证明length。

## 待执行

- [x] 根代理明确释放GUI后，只读诊断认证与服务中断；核心恢复后该页正常401→refresh200→me200→数据200，无需手动登录。
- [x] 真实载入旧published单题v1，核对RAG禁用/至少5理由、immutable partial指引及单题确定性可用。
- [x] 实际核对manual/simple/count5后只点击一次生成，5/5成功，按invocation记录finish_reason与tokens。
- [x] 对成功候选逐题核对当前Unicode来源quote/范围/hash/generation、问题和标准答案；5题均事实正确无需修改，经真实页面审核发布。
- [x] 对旧v1按无模型配置执行一次仅分块；真实422及0用量保留，未产生可下载报告。
- [x] 新核心/GUI交接后执行根代理明确授权的一次修复后仅分块复验，核对真实历史、下载及JSON；流程通过、检索质量得分0。
- [ ] 新5题正式Ragas单次有界执行，真实进度/终态/用量和历史报告JSON核对，不将受控测试当实际评测。
- [ ] 后置只读核对四模型、vault及旧版本完整行hash未变，归档/hash/删除临时脚本，检查链接与限定差异。

此前[真实失败验收](EVALUATION-BROWSER-ACCEPTANCE.md)及[UI门槛修复测试](EVALUATION-MINIMUM-SAMPLES.md)仍是各自证据，不能替代本轮真实浏览器复验或正式安装器GUI。

## 首个真实载入阻断

根代理释放GUI后，[本页公开只读诊断](../refactor-evidence/20261012-evaluation-real-recheck/002-own-public-auth-diagnostics.json)确认页签仍在evaluation，显示QA账号，auth_mode=cookie；该页既有两次access401→refresh200→me200记录，CSRF公开时间戳`1791694082178`距观察未满24小时。没有读取HttpOnly认证cookie、nonce/signature或请求header；记录未能解释根页1246那次跳转的具体失败，不能混用不同页的历史。

[实际选旧v1](../refactor-evidence/20261012-evaluation-real-recheck/004-select-old-v1.json)、[滚动可见](../refactor-evidence/20261012-evaluation-real-recheck/005-load-old-v1-visible.json)、[真实点击载入](../refactor-evidence/20261012-evaluation-real-recheck/006-load-old-v1-click.json)后，[ResourceTiming/DOM](../refactor-evidence/20261012-evaluation-real-recheck/007-old-v1-after-load-public-dom.json)显示GET `/api/v1/rag-eval/datasets/2f99f534-5d8a-45b8-ba67-3ddd87f740d5`返回500、单次324.2ms；页面仍为公开默认配置，toast为`Request failed with status code 500`，没有refresh新请求。[真实snapshot](../refactor-evidence/20261012-evaluation-real-recheck/009-load-failure-snapshot.json)也捕获该错误，不把click receipt当载入成功。此阶段尚未核对到单题门槛/不可编辑提示。

[错误后只读数据](../refactor-evidence/20261012-evaluation-real-recheck/008-after-load-500-public-auth-data.json)证明仍只有旧两条generation用量，四模型、vault和原v1/v2完整行hash不变；refresh仍未消费。浏览器API同源5173，经Vite `/api` proxy到127.0.0.1:8000，核心断开可能由代理返回500；此时根代理报告原core会话55312轮询exit0，正在只读核查PID/监听。尚未确认确切原因，不能将500称认证权限错误或自然会话到期。按根代理指令暂停登录、reload和付费生成，保留现页，不重启核心。

## 服务恢复、门槛与真实生成

随后根代理独立确认旧PID不存在、8000无监听、Vite仍在线，原核心日志22:45:26为正常stopping。[根代理恢复前后凭证](../refactor-evidence/20261012-browser-core-recovery/after.json)核对7表、四模型和vault SHA完全一致、0活动任务；不是通过改密或绕过认证恢复。[该页实际重试](../refactor-evidence/20261012-evaluation-real-recheck/011-load-old-v1-after-core-recovery.json)与[公开DOM/ResourceTiming](../refactor-evidence/20261012-evaluation-real-recheck/015-recovered-v1-auth-and-gate-dom.json)记录dataset401 316.7ms、me401 320.9ms、refresh200 261.1ms、me200 15.4ms、dataset200 323.5ms。只证明本页会话恢复成功，不能解释根代理另一页1246跳login的精确网络原因。

[旧v1实际snapshot](../refactor-evidence/20261012-evaluation-real-recheck/014-recovered-v1-gate-snapshot.json)确认单题发布集RAG disabled、明确至少5个有效已审核不同问题；仅检索/仅分块可用，未点击仅检索。partial文案正确为“已发布版本不可修改，请创建新版本后编辑审核”，候选不可编辑或删除。

[生成前可见配置](../refactor-evidence/20261012-evaluation-real-recheck/019-generation-before-confirmed-dom.json)为目标库、count5、manual、simple，reasoning/multi-context关闭，生成按钮在1289×659视口内。[只点击一次](../refactor-evidence/20261012-evaluation-real-recheck/021-generation-unique-five-click.json)后，[持久化完成](../refactor-evidence/20261012-evaluation-real-recheck/024-generation-second-readonly-observation.json)为新草稿`6c630a4d-309d-4dfd-8bac-b31bfdd20bec`、requested/completed5、result_unknown=false；实际POST200的ResourceTiming为5549.8ms（n=1，不是P95）。中途[Orca snapshot超时](../refactor-evidence/20261012-evaluation-real-recheck/023-generation-live-snapshot.json)仅工具异常，没有重放生成。

5条新GLM用量均success1、finish_reason=stop、cached0，分别155/149/163/201/181 tokens；总prompt674、completion175、total849、reasoning17。实际provider调用耗时分别1022/968/1131/1021/790ms。用具体5条invocation和创建时间绑定生成，不能仅以全局usage差额归因。原2条失败批次用量仍保留，未改写其无finish_reason的旧事实。

## 五题真实来源审核与发布

[逐题当前来源核验](../refactor-evidence/20261012-evaluation-real-recheck/026-current-source-and-five-review.json)使用native readonly SQLite作为后置断言，逐项tenant/KB、active文档/块、Unicode范围与quote、content、file_hash和source_generation全部一致，distinct questions5。实际业务仍通过Orca：逐个focus候选复选框后Tab/Enter展开原生来源details，[五个来源均打开的DOM](../refactor-evidence/20261012-evaluation-real-recheck/044-all-five-ui-sources-open-dom.json)与[发布前snapshot](../refactor-evidence/20261012-evaluation-real-recheck/045-five-before-publication-snapshot.json)记录5题已选。

| 题目要点 | 核实答案 | Unicode来源范围 |
| --- | --- | --- |
| P1首次响应 | 15分钟 | 251–349 |
| 晨星A交付总量 | 80套，未误用首批32 | 514–590 |
| 现行手册 | v3.2、2026-09-30生效 | 0–89 |
| 晨星A/曙光计划负责人 | 林青，未混淆晨星B周宁 | 89–251 |
| 测试传感器小计 | 948元=12×79，未误用903/1851 | 349–514 |

均来自现行手册`e1b8ada2-c9af-4c3e-a437-a0ec37972c44`，hash `5553d07a4ad244add76b2a3fa0a0d43c89d129f60ace6ea24720a3dba697524f`、generation `8710c42b-5394-409e-b60e-d3282353d228`。5题事实均正确无需修改，不虚构一次编辑动作。[实际可见发布click](../refactor-evidence/20261012-evaluation-real-recheck/047-five-reviewed-publish-click.json)后，[真实published UI](../refactor-evidence/20261012-evaluation-real-recheck/048-published-five-snapshot.json)为5 approved且不可修改、RAG可运行。[后置记录](../refactor-evidence/20261012-evaluation-real-recheck/049-after-five-publish-readonly.json)核对version1、approved5/pending0/rejected0/validation_errors均空，dataset_hash `c0c8bf1c01152169c2a5361be11e2009a3b8e4b7067cf15f06ff7bc4940fdc95`、完整行SHA `09965a1e58b17c8d0178799b0d6fe592b1a80480d675b969a28d0a1e7dc4b907`。

## 仅分块真实失败与独立修复

重新实际载入旧单题v1，[运行前DOM](../refactor-evidence/20261012-evaluation-real-recheck/060-free-chunking-exact-config-dom.json)确认recursive、comparisons=[]、keyword、Rerank=false、按钮可见；[仅点击一次](../refactor-evidence/20261012-evaluation-real-recheck/061-original-v1-only-chunking-unique-click.json)。[真实结果](../refactor-evidence/20261012-evaluation-real-recheck/062-original-v1-only-chunking-result-dom.json)为422 `Persisted image barrier indices are invalid`、473.9ms，页面failed且没有下载报告，不计通过。[后置只读记录](../refactor-evidence/20261012-evaluation-real-recheck/063-after-zero-provider-only-chunking-readonly.json)保留failed deterministic run、0新增评测用量，四模型/vault/旧v1/v2均完全相同。

[实际PNG字段](../refactor-evidence/20261012-evaluation-real-recheck/065-actual-parser-image-barriers-readonly.json)为合法canonical空、parser_blocks=[]、parser_image_block_indices=[0]。64记录的allowlist曾误用image_barrier_indices，遗漏真实字段；原日志保留，65纠正，不能把64解释成没有image barrier。评测来源还原误造text0撞真实image0，根代理授权单独修复。详见[真实SQLite RED→GREEN、empty semantic边界及最终src/dist冻结](EVALUATION-IMAGE-ONLY-SOURCE.md)：focused8/8、相关39/39、小Worker8/8、typecheck/build退出0、0厂商/GUI/live写。尚未加载新版核心或执行正式Ragas，等待明确GUI交接后继续。

## 修复后真实仅分块与下载

根代理有序切换到PID1368229/startTicks16454258，[live-after](../refactor-evidence/20261012-evaluation-image-source-live/live-after.json)核对16表与切换前完全相同、四模型/key相同、health TypeScript同service_id，绑定本修复src/dist SHA。根代理明确释放全部GUI后，本页[新snapshot](../refactor-evidence/20261012-evaluation-real-recheck/067-fixed-core-current-snapshot.json)确认仍旧单题v1。实际载入后再次正常access401→refresh200→me200→dataset200，未手动登录。

[运行前配置](../refactor-evidence/20261012-evaluation-real-recheck/071-fixed-v1-config-before-retest-dom.json)仍recursive/无比较/keyword/Rerank关闭/旧单题v1；[可见按钮](../refactor-evidence/20261012-evaluation-real-recheck/073-fixed-v1-visible-before-retest-dom.json)在视口内。[只点击一次复验](../refactor-evidence/20261012-evaluation-real-recheck/074-fixed-v1-only-chunking-unique-retest-click.json)后，[真实DOM与ResourceTiming](../refactor-evidence/20261012-evaluation-real-recheck/075-fixed-only-chunking-result-dom.json)为POST200、249.3ms（n=1）、completed/history verified+current，旧422仍在历史且下载不可用。[76只读](../refactor-evidence/20261012-evaluation-real-recheck/076-after-fixed-only-chunking-readonly.json)证明评测用量仍7，0新增；四模型、vault、旧v1/v2和新5题发布集完整行hash相同。

[当前full corpus报告断言](../refactor-evidence/20261012-evaluation-real-recheck/078-fixed-only-chunking-full-corpus-report-readonly.json)确认两文档包含原PNG（enabled、parser_image_block_indices=[0]不变）与手册，full_corpus=true、2child/1parent、真实recursive、0厂商调用。报告`1dceec1c-a39c-44cd-b908-746b91b2f755`绑定原v1/hash/version1，未跳过PNG避免错误。

通过[真实历史下载按钮click](../refactor-evidence/20261012-evaluation-real-recheck/081-chunking-history-download-click.json)，实际产生此前不存在的`C:\Users\lxd\Downloads\rag-eval-1dceec1c-a39c-44cd-b908-746b91b2f755.json`；[直接打开并核对](../refactor-evidence/20261012-evaluation-real-recheck/082-actual-chunking-downloaded-report-opened.json)为4827bytes、SHA `e88c3d855909eaa06498bdafbf2cdb731e4d560e96e33a6c04303be7d731bb96`，原字节[归档](../refactor-evidence/20261012-evaluation-real-recheck/082-downloaded-chunking-report.json)。配置、来源两文档、dataset/hash、samples1一致；metrics_scope仅retrieval_and_resources_only，未运行Ragas指标的字段没有伪造为分数，页面仍--/unverified。实际Hit/MRR/Recall均0，verified只表示证据/过程验证，不能写成质量通过。

68首条scroll助手误用不存在的`--ref`，返回invalid_argument且未执行业务；69已改为实际`--element @e12`成功，保留错误回执。这是测试调用语法错误，不是产品故障或额外评测。

## 完整中文问句的真实零召回

根代理看到0分后暂停未点击的正式Ragas，并授权最多1–2道免费GUI关键词检索检查。当前产品没有独立关键词检索测试页面，因此只对旧单题v1 exact keyword/Rerank关闭做一次“仅检索评测”（1题，source `deterministic.ts`的该组合不创建模型绑定）。[84运行前DOM](../refactor-evidence/20261012-evaluation-real-recheck/084-free-stored-retrieval-config-dom.json)、[85唯一click](../refactor-evidence/20261012-evaluation-real-recheck/085-free-stored-keyword-one-question-click.json)、[86真实结果](../refactor-evidence/20261012-evaluation-real-recheck/086-free-stored-retrieval-result-dom.json)为200/360.4ms（n=1），stored生产索引仍Hit/MRR/Recall0；[87后置记录](../refactor-evidence/20261012-evaluation-real-recheck/087-after-free-stored-retrieval-readonly.json)评测usage仍7、四模型/vault/三个dataset SHA不变。

[88真实native ReadDatabase同快照只读诊断](../refactor-evidence/20261012-evaluation-real-recheck/088-keyword-query-readonly-diagnostic.json)复用当前scope/active/searchable和SearchIndex的同一SQL及JavaScript Unicode regex，原v1和新5题均candidate_count0、hits=[]。每题gold来源仍有active、同范围、可检索块，控制literal LIKE `P1`/`林青`/`传感器`各可命中现有资料；这些控制是只读SQL，未冒充GUI检索。

实际FTS schema为trigram。`SearchIndex.keyword`将`/[\p{L}\p{N}_]+/gu`得到的连续中文/字母数字串（≥3 codepoints）包成完整quoted phrase OR。原v1变成`"按照晨星项目现行手册" OR "P1故障首次响应应在多少分钟内"`，新5题各变成一整段问句；这些完整短语不在答案正文，0召回发生在候选阶段，不是gold source overlap失配。保存的keyword/vector/rerank阈值分别.3/.15/.3、embedding_top_k10/rerank_top_k5/rerank_enabled=true；此次确定性评测代码明确topK20/keyword80/vector0/rerank0，threshold默认0，不能把空候选归因设置阈值。

原派生临时DB运行finally已删除，现有报告不含raw contexts，88只读查询是生产stored索引的实际候选，不能声称恢复了旧derived结果对象。正式五题Ragas尚未点击，禁止为了测质量改变评估题或重放付费；当前核心/Windows源码冻结保持，本轮只报告根因，待根代理决定修复与重新交接。

本段H执行至此冻结，[冻结记录](../refactor-evidence/20261012-evaluation-real-recheck/freeze.json)与[链接、差异及临时助手清理](../refactor-evidence/20261012-evaluation-real-recheck/final-check.json)绑定原始事实。H-01只覆盖manual/simple这一组；H-03只覆盖原单题recursive/keyword/no-rerank及其真实报告，未替代公开数据集、其他模式或正式安装。H-02新5题Ragas因已实证的CJK候选0暂缓，后续修复/运行须另写新阶段证据，不修改本段冻结失败或假填质量通过。Goal仍active，其他A–J真实页面及新版Windows交付仍有待验子项。
