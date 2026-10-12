# 中文问句检索修复后的真实评测验收

2026-10-12，Goal active。原[复验失败阶段](EVALUATION-REAL-RECHECK.md)和43d239ec…证据freeze不变。根代理独占实现CJK query terms并完成真实SQLite回归、相关检查及同目录核心有序切换；本段只拥有说明与`20261012-chinese-query-browser`新证据，不改任何产品、模型配置或原资料。

根代理正式授权：新核心PID1464221/startTicks16570927/session71148；独立Orca page6 `22e0e212-30aa-4945-8a3d-7176cdfffdff`，GUI继续由本代理独占。先对旧单题v1执行一次recursive/keyword/无比较/Rerank关闭的仅分块，再对新5题published执行一次keyword/Rerank关闭的仅检索，均应0厂商调用；实际history下载、打开文件核sample/配置/来源/每题指标，不能复用旧0分报告。只有对应来源检索有效后，才对新5题运行一次正式Ragas，recursive/无比较/keyword/Rerank关闭，已有GLM Answer/Judge，不改思考或Key；最多65新增usage行、最长30分钟，超过边界用实际GUI停止，失败/unknown绝不重试、恢复或另建run。

所有业务须实际Orca typed操作并固定GUID，DOM/ResourceTiming/SQLite readonly仅作后置断言。私有5题页面没有费用估算入口或费用确认弹窗；根已明确授权单次直接运行，正常45–65上界是源码推导，不是页面估算或厂商账单。不调用embedding重建、生成新题、仅检索/分块的其他付费配置，不修改原v1/v2、新5发布题或gold来源。

[新核心审计](../refactor-evidence/20261012-retrieval-chinese-query-live/live-after.json)记录16表跨重启一致、四模型/key及usage117保持，health TypeScript同service；[本段前置只读](../refactor-evidence/20261012-chinese-query-browser/001-cjk-before-real-runs-readonly.json)再次绑定三个评估集、四模型/key、已有失败/零分报告与评测usage7。自建空库仅属于另一段[页面补验](GENERAL-PAGE-BROWSER-ACCEPTANCE.md)，没有改变gold/评估集。

当前进入真实执行，未预填召回、Ragas评分或安装版通过。少量样本只报告n及条件，不声明P95。

## 两次无模型的真实召回与报告

[12旧v1安全配置](../refactor-evidence/20261012-chinese-query-browser/012-cjk-original-exact-safe-config-dom.json)为recursive、无比较、keyword、Rerank关闭、可见按钮；[13仅点击一次仅分块](../refactor-evidence/20261012-chinese-query-browser/013-cjk-original-only-chunking-unique-click.json)后，[14实际DOM/Timing](../refactor-evidence/20261012-chinese-query-browser/014-cjk-original-only-chunking-result-dom.json)为200/471.5ms（n=1），Hit/MRR/Recall各100%、verified/current。access到期期间正常refresh成功，没有手动登录或重复评测。[15只读](../refactor-evidence/20261012-chinese-query-browser/015-cjk-original-only-chunking-after-readonly.json)评测usage仍7。实际历史[下载click](../refactor-evidence/20261012-chinese-query-browser/018-cjk-original-history-download-click.json)后打开fresh文件，[19原JSON与核对](../refactor-evidence/20261012-chinese-query-browser/019-cjk-original-actual-report-opened.json)4825bytes、SHA `0cd65b394fe2ab208b0793502edbfc28b69462b5c7d2455572f8835ee8296094`，report f2e1603f…绑定旧v1/hash/1样本、手册与PNG两文档、recursive与真实per_question1；未运行Ragas指标不伪填。旧0分/422报告仍保留。

实际选择并载入新5题published，[25安全配置](../refactor-evidence/20261012-chinese-query-browser/025-cjk-new-five-exact-safe-retrieval-dom.json)确认5 approved、keyword/Rerank关闭、无比较；[26仅点击一次仅检索](../refactor-evidence/20261012-chinese-query-browser/026-cjk-new-five-only-retrieval-unique-click.json)。[27真实页面](../refactor-evidence/20261012-chinese-query-browser/027-cjk-new-five-only-retrieval-result-dom.json)200/586.3ms（n=1）、5/5 completed/verified/current，Hit/MRR/Recall均100%；[28只读](../refactor-evidence/20261012-chinese-query-browser/028-cjk-new-five-only-retrieval-after-readonly.json)0新增usage、四模型/key与三个评估集SHA相同。

通过[32历史download实际click](../refactor-evidence/20261012-chinese-query-browser/032-cjk-five-history-download-click.json)，[33直接打开下载JSON](../refactor-evidence/20261012-chinese-query-browser/033-cjk-five-actual-report-opened.json)3972bytes、SHA `cead3ab4f85914f5e615e7d8fc3efbd33546c8752bc37b9bcccd6dd2b09b4e96`，report 6a06439f…/新dataset6c630…/hash c0c8bf1c…/v1/5样本、full corpus两个原来源均正确。effective策略为stored，不能把表单requested recursive误称仅检索时实际重分块。每题Hit/MRR/Recall各1，检索source overlap precision依次1、1/3、.2、.5、1，均值.6067；有正确首位来源但仍有额外候选，不宣称所有上下文精准。[34当前五题来源重新核对](../refactor-evidence/20261012-chinese-query-browser/034-current-five-source-verification.json)Unicode quote/范围、tenant/KB、active chunks、file_hash及generation全一致、approved5/distinct5，无修改或补造题目。

## 唯一正式Ragas已启动

实际把Answer/Judge各选为原有GLM model-0a6835cb-ae1c-48b1-8331-27729e42acd3；[38运行前DOM](../refactor-evidence/20261012-chinese-query-browser/038-real-ragas-exact-before-config-dom.json)为新published5、recursive、comparison=[]、keyword、Rerankfalse，run enabled且可见，无费用弹窗。[39只读基线](../refactor-evidence/20261012-chinese-query-browser/039-real-ragas-before-baseline-readonly.json)评测usage7（总usage117）、四模型/key和三个评估集SHA保持。[40实际截图](../refactor-evidence/20261012-chinese-query-browser/040-real-ragas-before-visible-screen.png)已打开查看，UI明确当前表单改了Answer/Judge、旧结果属于上一次配置，未混用旧分数。

[41唯一实际运行click](../refactor-evidence/20261012-chinese-query-browser/041-real-ragas-one-and-only-run-click.json)后，[42页面](../refactor-evidence/20261012-chinese-query-browser/042-real-ragas-start-progress-dom.json)排队、停止可用、分块/检索/Answer/Judge全部锁定，POST200、没有费用弹窗。43首SQL采样尚无本run，未因此重放点击；[44后续持久化](../refactor-evidence/20261012-chinese-query-browser/044-ragas-initial-persistence-readonly.json)确认新run `9a8de0eb-a2bf-48cc-8883-7474b1cd037d`、job running/attempt1、started_at `2026-10-12T00:17:52.336Z`、5 Answer用量。以核心started_at计30分钟截止00:47:52Z，不跨WSL/Windows时钟推导首SQL与页面回执的因果失败。

[45真实progress snapshot](../refactor-evidence/20261012-chinese-query-browser/045-real-ragas-progress-snapshot.json)为running/ragas_scoring/24秒、取消可用，未执行继续或恢复。[46精确job_id只读预算](../refactor-evidence/20261012-chinese-query-browser/046-real-ragas-precise-budget-progress-readonly.json)95.4秒/progress.56，23行实际用量（Answer5、Judge14、Embedding4），均success1、attempt1，无unknown/failed；未超过65行/1800秒。当前仍等待真实终态、评分与报告，不把候选或受控测试替代此次厂商评测。

## 真实终态、评分与原文件

[47终态实际账本](../refactor-evidence/20261012-chinese-query-browser/047-real-ragas-budget-progress-readonly.json)job completed/progress1/attempt1，finished_at `2026-10-12T00:20:37.057Z`，164.721秒（n=1，Windows构建在后台）。45条实际调用全部成功且invocation ledger completed，无unknown/failed、重试或恢复：Answer5、Judge30、Embedding10；总prompt27025、completion12480、tokens39505、cached5632、reasoning10117。低于65行和30分钟边界；以metadata.job_id精确归因，不仅凭全局差额。

[48实际DOM](../refactor-evidence/20261012-chinese-query-browser/048-real-ragas-progress-current-dom.json)与[49终态snapshot](../refactor-evidence/20261012-chinese-query-browser/049-real-ragas-completed-current-snapshot.json)为已完成5/5、Ragas实际评分5题、coverage100%、2分45秒，停止/取消按钮消失、表单解锁；最近8条状态轮询全部200、12–326.3ms，仅为这次观察范围，不是P95。阶段保留实际ragas_scoring，status独立为completed，不推断重新评分。

| 实际指标 | 值 | 范围 |
| --- | --- | --- |
| Hit@10 / MRR@10 / Recall@20 | 各1 | 此5题真实recursive检索 |
| Faithfulness | 1 | Ragas0.4.3，此5题 |
| Answer Relevancy | 0.9472539593197356 | Ragas0.4.3，此5题 |
| Context Precision | 0.9999999999 | Ragas0.4.3，此5题 |
| Context Recall / Answer Correctness | null | unavailable，未运行 |

实际history首行rag/5题/recursive/verified/current，经[52历史下载click](../refactor-evidence/20261012-chinese-query-browser/052-real-ragas-history-download-click.json)保存fresh文件`C:\Users\lxd\Downloads\rag-eval-8abf3a76-3c10-476f-bade-bf6ff7609504.json`。[53直接打开核对](../refactor-evidence/20261012-chinese-query-browser/053-real-ragas-actual-report-opened.json)为8275bytes、SHA `2d94a554c2f9ae468c1dc853a4e14140c5aafc52de985547d1dd5d7778b8e0c2`，另保存[原字节JSON](../refactor-evidence/20261012-chinese-query-browser/053-real-ragas-actual-report-opened-downloaded.json)。requested/effective准确为source新dataset/v1、sample_size5、recursive、comparisons空、keyword、Rerankfalse，实际GLM Answer/Judge与既有Embedding模型ID，Ragas版本0.4.3、max contexts5/单上下文2000/总6000 codepoints、keyword80/vector0/rerank0/top20；PNG与手册两来源及file_hash/generation、dataset_hash c0c8bf1c…均绑定当前输入。

报告metrics.samples5、usage.calls45与真实账本一致，null未测项未伪造。正式Ragas导出聚合结果及source fingerprint，没有每题Answer文本/独立Ragas分布；不能凭该文件宣称逐条人工核验了厂商Answer，也不把5道单一虚构手册事实题外推成生产整体质量。5个输入题/来源的逐条检查由34及已冻结原H的真实UI审核证明，本文分别列明。

[54页面及ResourceTiming](../refactor-evidence/20261012-chinese-query-browser/054-real-ragas-completed-metrics-dom.json)下载时access到期，报告GET401 325.1ms后正常刷新再GET200 265.5ms，未改密/登录/重复评测；实际文件成功保存。

## 历史删除取消与保护边界

只对自己此次新报告点击删除后取消，保留所有真实run/报告。[56 click回执](../refactor-evidence/20261012-chinese-query-browser/056-real-ragas-history-delete-dialog-click.json)因原生confirm阻塞Orca31599ms返回runtime_unavailable，原失败保留，不以其当成功，也没有重放click。57首次助手使用未带子命令的dialog返回unknown command，是工具调用错误；58读取实际CLI help后，[59实际`dialog dismiss`](../refactor-evidence/20261012-chinese-query-browser/059-real-ragas-delete-dialog-dismiss.json)返回accepted=false，后续[61正常DOM](../refactor-evidence/20261012-chinese-query-browser/061-real-ragas-report-delete-cancel-dom.json)仍显示新报告且无阻塞。[62前后精确比较](../refactor-evidence/20261012-chinese-query-browser/062-real-report-delete-cancel-comparison.json)报告完整行SHA `97b4d1f8a65ff4a1d4c0f9c0412e6e63abeb70084f92cc87848a6f78592300df`相同、deleted_at=null、usage52（原7+此次45）保持、模型与vault不变；未执行确认删除。

[63全保护后置只读](../refactor-evidence/20261012-chinese-query-browser/063-protected-originals-after-ragas-readonly.json)与general阶段原基线比较：原2知识库、gold2文档/13块、13条原Wiki、3评估集、4模型与vault摘要完全相同；仅当前授权新run/报告/45用量及此前自有空库增加，没有活动任务。所有临时CJK助手最终归档/hash/删除，见[最终检查](../refactor-evidence/20261012-chinese-query-browser/final-check.json)；[本段冻结](../refactor-evidence/20261012-chinese-query-browser/freeze.json)保留失败/终态/原文件与命令证据。

本段只完成这些明确的browser子项。auto/sample、公开/3045全集、运行中取消/恢复/断网、其他策略与最终Windows安装评测仍未执行；没有以成功5题自动填满H或Goal，主进度由根代理更新。GUI尚由本代理持有，另一个general阶段的自有空库编辑/搜索/清理仍待执行，原H两次失败freeze不改。
