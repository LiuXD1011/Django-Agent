# 评测候选题生成的辅助思考参数

本次基于 Orca 真实生成失败：5 题请求保存 1 题后失败，第二个调用 completion_tokens=1024、reasoning_tokens=964，错误为 evaluation_generation_invalid。原记录没有供应商 finish_reason，不能据此断言已经观测到 length。生成器固定 1024 额度，并继承了对话模型的默认思考参数；其他摘要、Wiki 辅助任务已经使用按端点精确匹配的 auxiliaryThinking。

采用现有辅助参数策略：已验证 GLM 5.3 端点使用 on/low，给包含推理与 JSON 答案的单题响应设置 4096 上限；已验证 DeepSeek 使用既有 off 策略，其他端点保持供应商默认与原 1024 上限。不会修改模型保存的对话思考配置。生成仍每题最多一次模型请求；失败保留已保存候选，以及 complete 已返回的 usage，不自动重试或重放。缺 finish_reason/非法 message 等现有 Runtime envelope 审计边界见 [只读审查](EVALUATION-GENERATION-REVIEW.md)。

备选方案为仅提高所有模型预算或增加失败重试。前者扩大无关端点的额度，后者可能重复付费且不能解决错误参数。复用已有端点策略使本次修改限定在候选题生成器。记录供应商 finish_reason 的有界公开枚举，帮助区别截断和 JSON 格式错误，继续使用原错误码。

按 Goal 第二节已批准的普通修复和自主计划继续执行，不提交。

- [x] 完整阅读 generation.ts、thinking.ts、providers.ts 与相关运行代码，核对真实失败和已有辅助调用模式。
- [x] 在 `packages/core/test/evaluation-generation-thinking.test.ts` 使用真实 SQLite 和明确标注的本地 HTTP 模型替身，复现 GLM 参数遗漏导致生成失败；校验保存的对话参数不变。
- [x] 验证未知端点不冒用 GLM 参数、DeepSeek 使用既有辅助参数；截断失败保留候选和用量且不重试。
- [x] 运行 RED；修改 `packages/core/src/evaluation/generation.ts` 的辅助参数、受限预算及 finish_reason 审计，在已完整阅读的 `packages/core/src/settings/usage-audit.ts` 中加入有界公开枚举，拒绝原始模型内容。
- [x] 运行相关评测、模型回归，core typecheck/build；保存命令与原始结果。
- [ ] 协调没有运行任务后更新真实 core，再通过 Orca 小规模生成与审核复验。原失败证据保持不变。
- [ ] 将修改纳入后续最终 Windows 冻结包，另行真实验证。
