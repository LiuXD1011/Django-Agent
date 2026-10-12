# 评测纯图片来源边界修复设计与执行计划

2026-10-12，Goal II.3–5授权常规错误修复。按已读systematic-debugging、brainstorming、writing-plans、TDD和verification执行；根代理已批准独占范围及继续实现，不重复请求用户批准、不提交。归属仅`packages/core/src/evaluation/isolated-index.ts`、后续明确授权的`packages/core/src/documents/chunker.ts`、新`packages/core/test/evaluation-image-only-source.test.ts`、本说明及独立`20261012-evaluation-image-only-source`证据。根代理持有GUI/live核心/Windows交付。

## 根因和最小方案

真实Orca在标准资料库按recursive、无比较、keyword、Rerank关闭，仅点击一次仅分块，返回422 `Persisted image barrier indices are invalid`，0新增厂商用量，正式Ragas尚未启动。[实际复验记录](EVALUATION-REAL-RECHECK.md)的62/63保留失败；[实际字段](../refactor-evidence/20261012-evaluation-real-recheck/065-actual-parser-image-barriers-readonly.json)确认合法PNG来源为canonical空字符串、parser_blocks空数组、parser_image_block_indices=[0]。

`parsedSource`把空parser_blocks误当缺失，fallback造一个block_index0的空text；随后真实image0与假text0碰撞。正确方案是在canonical为空时保留真实空text集合，按实际image indices重建barriers，不虚构空正文。非空canonical的现有legacy fallback保持。派生索引仍纳入空文本的图片文档并计入full corpus，只是不生成不存在的text块；生产文档、图片块和向量不变。

另核查现有image数组map没有去重，非法[2,2]目前可绕过拒绝；按根任务要求加入本次解析局部Set，保留原负数/非整数/text collision的同一422错误。禁止通过跳过整份图片、清空barriers或接受非法索引来修复。

不采用删除图片来源：它会改变full corpus和权限/来源指纹。不改模型/配置或另加OCR流程：实际故障位于评测的持久化来源还原，当前知识库原始图片解析是合法的。

根代理随后明确授权生产`splitDocument`的空semantic边界：保留正常chunking配置验证与signal检查，canonical为空或仅空白时无需调用semanticEmbed，0块且requested/selected仍为semantic，诊断明确`semantic_embedding_skipped='empty_text_source'`；非空semantic及其原fallback保持。先前向根代理称实际ModelRuntime会拒绝空数组不准确，亲读runtime.ts:240–242及validateTexts后已纠正：它返回空vectors/0usage，不发厂商请求。实际问题是空源仍进入callback及其invocation/audit路径，以及没有callback时误报降级；不能将本回归写成厂商拒空或真实付费失败。

## 接口与验证

没有新增公开接口。继续使用实际`IsolatedEvaluationIndex.build(CoreDatabase, AuthContext, kbId, strategy, options)`、native SQLite/FTS/vec和真实`splitDocument`；不mock核心，不访问实时数据库、不发API/GUI/厂商请求。测试使用中文/emoji来源、合法standalone图片metadata，临时SQLite目录finally关闭删除。

- [x] 先新增真实full corpus回归，观察旧源码因假text0与image0碰撞而RED；重复image索引拒绝用例也先RED，原始日志保留。
- [x] 仅修改上述空text还原和局部image去重。
- [x] GREEN核对纯图片仍在derived corpus、无空text块、真实手册FTS可命中，生产行及FTS结果不变、0模型用量。
- [x] 控制覆盖正常空TXT、nonempty legacy fallback、Unicode text0/image1/text2真实分界，以及负数/小数/重复/text collision的明确拒绝和派生目录清理。
- [x] 补空TXT+纯图full corpus及非空真实deterministic-vector callback的合理RED→GREEN，空semantic无callback/降级且配置/取消仍有效。
- [x] 执行新测试、相关evaluation/isolated和小型chunking测试，core typecheck与build；不跑40K/full core，不把受控模型fixture称厂商验收。
- [x] 审查限定diff/链接/source/dist SHA，归档hash并删除本次临时命令/检查脚本。
- [ ] 根代理最终有序切换live core并交接GUI后，继续已明确授权的一次仅分块真实重验和有界五题正式Ragas；不得自行重启或提前宣称真实评测通过。

Windows正在基于旧freeze后台构建；根代理已确认其core构建在Windows本地staging，不并发写Linux `packages/core/dist`，本修复须新freeze/正式交付绑定，不能预称安装版通过。

## 原始执行证据

首次[5项RED](../refactor-evidence/20261012-evaluation-image-only-source/focused-red.json)3PASS/2FAIL，2933.928ms：合法image0与假text0碰撞；非法重复[2,2]缺预期拒绝。没有导入/fixture启动错误。自审发现重复测试意外成功时须关闭派生连接，补finally清理后[再次RED](../refactor-evidence/20261012-evaluation-image-only-source/focused-red-cleanup.json)仍同两项真实失败、3475.068ms；原日志未覆盖。隔离源码SHA两次前后均为`2af19381e9fbad40a0634e6bc761e81280eab2f1fd7526d38b4a0259af5653b4`。

[最小5/5 GREEN](../refactor-evidence/20261012-evaluation-image-only-source/focused-green.json)2654.519ms。其后中间基线[相关evaluation50/50](../refactor-evidence/20261012-evaluation-image-only-source/related-evaluation-green.json)退出0、195471.534ms，[typecheck](../refactor-evidence/20261012-evaluation-image-only-source/typecheck.json)退出0、19457.896ms；这批精确对应isolated c09ea054…与原chunker6407f25e…，还未包含后来空semantic改动。控制HTTP及真实Ragas算法是隔离测试，不计实际厂商调用或Orca正式评测通过。

新增[semantic RED](../refactor-evidence/20261012-evaluation-image-only-source/semantic-red.json)5PASS/3FAIL、3790.258ms：两个空文档均实际dispatch([])；非空文档+纯图共2次callback而预期只有非空1次；无callback空源误报missing_embedding_callable并fallback。callback正常返回有效2维vectors或空数组，没有人为throw冒充厂商失败。[最终focused8/8 GREEN](../refactor-evidence/20261012-evaluation-image-only-source/semantic-green.json)3795.620ms；完整corpus保留两文档，纯空源0callback/0块，非空源实际向量参与semantic算法，正常配置/取消检查保留。最终新源码相关验证仍单独记录，不能复用中间基线冒称其已覆盖新增条件。

最终相同源码基线的[相关评测39/39](../refactor-evidence/20261012-evaluation-image-only-source/final-related-evaluation-green.json)退出0、194402.871ms，执行新来源回归、evaluation及retention三个文件。包括真实SQLite、HTTP/IPC、来源及报告契约、取消和受控Ragas算法；0真实厂商调用。没有重新执行无关大输入或整个核心套件。[小型真实分块Worker8/8](../refactor-evidence/20261012-evaluation-image-only-source/small-chunker-related-green.json)5856.86ms，覆盖正常Unicode/父子/空输入、真实fallback及非空semantic/custom counter路径。[最终typecheck](../refactor-evidence/20261012-evaluation-image-only-source/final-typecheck.json)退出0、18946.272ms，[core build](../refactor-evidence/20261012-evaluation-image-only-source/build.json)退出0、21124.519ms。每条命令原始stdout/stderr和精确参数保留，三源SHA before/after完全一致。

[冻结凭证](../refactor-evidence/20261012-evaluation-image-only-source/freeze.json)绑定三份源码、对应Linux dist产物、本说明和所有原始执行证据。[最终检查](../refactor-evidence/20261012-evaluation-image-only-source/final-check.json)记录限定差异、文档相对链接及本次临时脚本归档/删除。另一个尚未完成的真实页面复验所用三个独立临时助手暂保留，待该任务结束清理，不能将其误称已删除。

本轮没有GUI、实时库写入或厂商调用；Windows旧freeze包与当前新来源修复存在源码差异。核心已在Linux重新编译，但实际页面、最终Windows打包/安装及真实Ragas仍由根代理协调后续验证，Goal保持active。
