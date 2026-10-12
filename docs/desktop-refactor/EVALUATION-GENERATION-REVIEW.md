# 评测候选生成 thinking 修复只读审查

本次当前源码审查未发现新增阻断问题。完整阅读 generation.ts、usage-audit.ts、providers.ts、thinking.ts、runtime.ts、新四项回归及生成计划，另核对 common.ts、datasets.ts 与配置/调用类型依赖。审查没有改产品源码、运行测试、调用模型、GUI 或读取实时数据库；仅复核 root 已保留的测试日志和命令结果。

已确认的行为：

- [generation.ts](../../packages/core/src/evaluation/generation.ts) 第42–43、64行使用 resolved provider 的辅助策略，只有辅助 mode=on 设置单题4096，其余1024。单次 request options 覆盖 [runtime.ts](../../packages/core/src/models/runtime.ts) 第160行的保存配置；没有 models update 写入，模型快照签名仍在调用前后核对。
- [thinking.ts](../../packages/core/src/models/thinking.ts) 第12–24、43–47行的精确匹配是 hostname 相等与完整模型 ID 相等，不按 source 名、模型子串或相似域名猜测。此处复用既有策略，并不是对 scheme/port/path 的完整 URL 白名单验证；未知 profile 不注入 GLM 辅助参数。4096是每题响应上限，不保证供应商会遵守 low 或一定输出有效 JSON。
- generation 第64–69行先接收 ModelCompletion.usage，再处理 JSON/length；length 即使包含可解析 JSON也拒绝，失败审计保留已返回的真实计数。finish_reason 限 stop/length/tool_calls/content_filter/other，未知值映射 other；[usage-audit.ts](../../packages/core/src/settings/usage-audit.ts) 第16–32行再次枚举投影，原始正文和思考文本不会进入 metadata。
- 逐题调用没有 retry；失败由第78行收尾，先前 append 的候选保留。datasets 的单题 publication 是同步 scoped transaction，模型 HTTP 期间不持有该事务；finishGeneration 只针对同租户、同 owner、仍 running 的草稿更新终态。默认 manual 候选仍待审核，不改变原审核/发布功能。

既有审计边界需保留：runtime 第229–237行在提取 modelUsage 前验证 finish_reason/message。若合法 HTTP JSON含有效 usage，但缺 finish_reason 或 message 非法，complete 会提前抛错；generation 的默认计数保持0，result_unknown=true。本次新四项回归覆盖的是 complete 已返回之后的正文 JSON/length 失败，不能宣称所有 envelope 失效仍保留 vendor 报告计数。该边界不是本次新增回归，root 已接受本次不扩修复，只将“保留真实用量”限定为已返回 ModelCompletion 的 usage。

原始 [最终 RED](../refactor-evidence/20261012-evaluation-generation-thinking-final-red.tap) 为4/4预期失败，[GREEN](../refactor-evidence/20261012-evaluation-generation-thinking-green.tap) 为4/4、[相关回归](../refactor-evidence/20261012-evaluation-generation-thinking-related.tap) 为55/55，均无 skip/cancel。审查读过 [typecheck](../refactor-evidence/20261012-evaluation-generation-thinking-typecheck.log) 与 [build](../refactor-evidence/20261012-evaluation-generation-thinking-build.log) 的无诊断日志；退出0由 root 原执行结果确认。没有在此审查中重跑或把本地 HTTP 替身说成真实供应商验证。

生成计划中上述实现/回归/静态检查步骤已按实际证据勾选，真实 Orca 生成与审核复验、最终 Windows 包仍未完成。真实原失败没有供应商 finish_reason，不因这次 length 替身回归而改称已观察到 length。源码与证据 SHA 见独立 review 目录，供 root 最终集成和真实复验使用。
