# 评测工作台 RAG 最少样本前置条件

2026-10-12。根代理依已授权Goal确认本最小设计，可继续执行，不重复用户批准，不提交。使用已读brainstorming、systematic-debugging、writing-plans、TDD与verification流程；该文档位置按项目及任务指定。原[真实浏览器验收](EVALUATION-BROWSER-ACCEPTANCE.md)及其证据保持冻结。

## 根因与方案

真实Orca发布partial评估集1题后，“运行评测”enabled。`Evaluation.vue`的datasetReady只判断已发布问题非空，完整RAG按钮及handler复用它；核心`evaluation/index.ts`实际要求5–100题、至少5个trim/lowercase后不同的问题、所有题approved且当前来源验证通过。另一个真实问题是已发布partial版本仍提示“候选题仍可编辑审核”，与实际immutable入口冲突。

推荐新增RAG专用前置条件，保留datasetReady与确定性功能。禁止全局把datasetReady变成>=5：`evaluation/deterministic.ts`明确允许>=1有效已审核题，仅检索/仅分块现有单题行为需要保留。只在点击后依赖server422仍会保留误导性的可运行按钮，因此不用此方案。

客户端只使用实际DTO的approved状态、非空question、validation_errors空数组和trim/lowercase去重计算有效审核题数；不在浏览器复制SQL/来源权限验证，不宣称该数已实时验证最新语料。来源、模型、schema、最大数量及所有记录的最终检查仍由核心preflight负责。公开数据集继续使用已准备状态，原active任务停止/取消/恢复语义不改变。

完整RAG按钮和runEvaluation handler使用专用gate，低于5时disabled并显示中文条件/当前有效不同题数。通过后的执行流程、指标、实际模型及用量没有变化。partial失败文案仍显示完成数/错误码/未知付费结果；draft保留编辑指引，published明确不可修改并指引创建新版本。

## 文件与验证计划

归属仅`frontend/src/views/Evaluation.vue`、其直接Evaluation测试、本说明及独立`20261012-evaluation-minimum-samples`证据；不编辑core/desktop/依赖/主进度，不再操作GUI/liveDB或发厂商请求。测试使用已安装Vue3.5、compiler-sfc、esbuild0.28.2、Playwright1.61的实际API，挂载真实Vue组件；fixture只提供公开DTO/记录客户端API请求，隔离headless测试不计实际Orca验收。

- [x] 给真实Vue DOM/现有行为测试加入回归：已发布1题阻止RAG、至少5不同且有效审核题通过、重复/已知validation错误不凑数；确定性单题按钮仍enabled。
- [x] 给partial published/draft文案加入真实组件回归，保留计数与错误。
- [x] 先执行相关测试，亲读合理RED（enabled与错误文案），保留原始输出，不能用导入/fixture错误冒充RED。
- [x] 仅实现上述RAG gate/中文原因/状态分支，再相关GREEN。
- [x] 运行`frontend npm run test:unit`完整套件及`npm run build`；保留真实失败及修正证据，不以这些结果替代正式安装版GUI。
- [x] 审查限定diff、链接及SHA，删除临时命令脚本并冻结交付；根代理负责后续真实Orca/新安装包验收。

## 执行记录

原H浏览器记录完整生成未完成1/5、2次厂商请求1648tokens；本源码阶段无厂商调用、没有再操作GUI。

[定向RED](../refactor-evidence/20261012-evaluation-minimum-samples/focused-red.json)4/4真实失败：单题按钮仍enabled、5条含trim/lowercase重复仍enabled、published仍出现可编辑指引、handler实际发出不应发送的fixture API。Vue源码SHA前后未变，失败是目标行为断言，不是导入或fixture启动错误。定向[4/4 GREEN](../refactor-evidence/20261012-evaluation-minimum-samples/focused-green.json)后补保留行为控制，全部[Evaluation相关28/28](../refactor-evidence/20261012-evaluation-minimum-samples/evaluation-related-green.json)退出0：实际headless Vue DOM验证单题确定性功能、5题RAG实际click及停止按钮、重复/已知invalid/pending4题门槛、published新版本后draft指引；公开prepared原执行路径及既有恢复/报告指标测试保留。

RED浏览器fixture的quote实际16个code point，初写source_end18在GREEN前纠正为16；该隔离fixture没有调用核心来源校验，4个RED均是上述产品行为断言，未将此夹具边界误当根因。测试API只模拟公开DTO及记录请求，不调用真实Core/SQLite/provider，不能代替后续真实RAG/正式Windows页面验收。

仅修改RAG专用计算、handler guard、完整RAG按钮disabled/原因和partial published指引，datasetReady、确定性handler/按钮、取消/恢复/指标/后端规则未变。计数只接受显式空validation_errors数组；未报告验证字段不会被当成已知有效来源。最新语料仍由核心preflight重新验证。

首次[完整frontend单测](../refactor-evidence/20261012-evaluation-minimum-samples/frontend-all-green.json)347/347退出0，98397.383ms。最后自审发现重复fixture原P1再toUpperCase不会产生大小写差异，只覆盖trim；仅把该fixture改成toLowerCase形成真实p1/P1+空格边界。因新测试关注点再执行[最终完整frontend单测](../refactor-evidence/20261012-evaluation-minimum-samples/frontend-all-case-green.json)347/347退出0，100279.461ms；TAP总时长99849.293531ms，0failed/cancelled/skipped，两个修改源码测试前后SHA相等。[frontend构建](../refactor-evidence/20261012-evaluation-minimum-samples/frontend-build.json)退出0，44777.204ms；Vite保留单chunk超过500kB的提示，未调整依赖或构建配置。最后只有测试fixture变化，产品SHA与这次构建保持相同，因此没有重复构建。

本轮产品源码SHA：Evaluation.vue `1027b3984298ffb1856b082ad72d381ef9a6e05f4139e67fde9332f6aaf6e299`；直接behavior测试 `431cd3384a86e54c83a9b18b6be516db4b5b7e8155d1540a4a91d229f1633bfb`。本轮只测隔离headless组件与构建，没有声称最新正式Windows安装器/GUI或5题生成已通过；根代理仍独占真实窗口并继续Goal。

限定diff、链接、原H证据保持不变及临时脚本归档/SHA/删除记录见[交付检查](../refactor-evidence/20261012-evaluation-minimum-samples/final-check.json)与本证据目录freeze.json。
