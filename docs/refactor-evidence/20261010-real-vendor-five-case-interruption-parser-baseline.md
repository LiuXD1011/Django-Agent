# 五题真实厂商评测中断：只读诊断（2026-10-10）

本次 run `def03505-f77e-453f-b847-80d29ee9acc8` 的直接触发原因已经确定：**第四次 Ragas judge 请求触及 ModelRuntime 的 60 秒本地 HTTP completion 截止时间**。其 model_usage 与 paid invocation ledger 均记录 `model_timeout`；实测调用耗时 60,005 ms，账本变为 unknown，manual job 随后变为 interrupted / result_unknown。没有证据说明这是厂商 HTTP 408/504，也无法由安全审计区分厂商计算、网络或响应传输在哪一段延迟。

本轮没有启动 Core、执行 API、访问厂商、重试或恢复 paid run，也没有 GUI 操作、产品/stage 修改、真实数据写入、解密材料/Key/密文/检查点读取。复现方案仅为设计，尚未执行。

原生 Windows `C:\Python313\python.exe -I -B`（审计主机 Python 3.13.3 / SQLite 3.49.1）通过 SQLite URI `mode=ro`、`PRAGMA query_only=ON`，仅查询 root 指定的已关闭私有副本和这个 run。SQL 明确选择状态、时间、固定错误码、调用 ID 的 SHA 和 token/duration 等白名单；不 SELECT 原始 payload、checkpoint、秘密参数或厂商 error message。DB、WAL、SHM 原字节 SHA 查询前后完全相等。原始安全采集为 [readonly.json](20261010-real-vendor-five-case-interruption-readonly.json)，SHA256 `4fd6d219c644a1cbe107982755b4cd721cc4cbff7f8c6320bd55dc8d54a71049`；分析与精确用量为 [parser-baseline.json](20261010-real-vendor-five-case-interruption-parser-baseline.json)。此主机版本不冒充正式 bundled Python 3.13.16。

## 直接证据与时间线

| 事件 | UTC 时间或耗时 | 记录事实 |
| --- | --- | --- |
| Job 开始 | 12:27:42.282 | attempt 1 / manual |
| 检索与回答完成，进入评分 | 12:28:08.947 | progress 0.3；5 embedding + 5 rerank + 5 answer 全成功 |
| 第一次 judge ledger 创建 | 12:28:24.978 | 距评分 stage 16,031 ms；该间隔包含 worker 准备及首次 RPC，不能单独归因于 Python import |
| Judge 1 | 7,130 ms | 成功；completion 525 / reasoning 423 |
| Judge 2 | 39,003 ms | 成功；completion 2,358 / reasoning 1,974 |
| Judge 3 | 26,060 ms | 成功；completion 1,407 / reasoning 1,379 |
| Judge 4 ledger 创建 | 12:29:37.222 | pending |
| Judge 4 用量记录 | 12:30:37.227 | success false / model_timeout / result_unknown true / duration 60,005 ms |
| Judge 4 ledger 保存 | 12:30:37.231 | unknown / model_timeout；与用量记录是同一个 invocation |
| Job 结束 | 12:30:37.255 | interrupted；没有 cancel_requested_at |
| 当时持有的租约截止 | 12:31:57.392 | Job 结束时仍余 80,137 ms；租约未过期 |

全部 19 条用量和 19 条 ledger invocation 的 ID SHA 精确一一匹配。`model_usage.id` 才是实际 invocation UUID（见 `settings/usage-audit.ts`），不是空的 request_id；没有以时间近似拼接。同一个模型用于 answer 和 judge，但按实际 scenario 区分。

| Scenario | 调用数 | 成功 / 失败 / unknown | prompt | completion | reasoning | duration 总和（ms） |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| evaluation_embedding | 5 | 5 / 0 / 0 | 77 | 0 | 0 | 1,080 |
| evaluation_rerank | 5 | 5 / 0 / 0 | 1,421 | 0 | 0 | 1,045 |
| evaluation_answer | 5 | 5 / 0 / 0 | 1,405 | 1,286 | 758 | 24,075 |
| evaluation_judge | 4 | 3 / 1 / 1 | 2,343 | 4,290 | 3,776 | 132,198 |

这些 duration 是实际调用记录的加总，不能当作产品端到端延迟。实际 job 墙钟 174,973 ms、评分 stage 墙钟 148,308 ms；root 提供 outer 227,640 ms，后者本轮没有重新执行测量。第四次请求的零 tokens 表示没有收到可审计的供应商 usage，**不表示没有消耗或没有计费**。

## 冻结代码如何得到这个结果

- `settings/model-configuration.ts:127`：模型没有 timeoutMs/timeout 时，用 StartupConfiguration.active.model_timeout。该私有副本相关模型的两字段均无显式值，`.settings/startup.json` 不存在；`settings/startup.ts:8` 的默认值为 60 秒。未读取环境中的秘密；实际 60,005 ms 与模型错误码亦确认本次截止预算为 60 秒。
- `models/runtime.ts:89` / `:94`：每次模型请求的 timer abort 后返回 `model_timeout`、resultUnknown=true；`:192`–`:194` 的计时覆盖 fetch 和完整 response.text()。这次是客户端截止，不是已知厂商 HTTP 错误响应。
- `evaluation/executor.ts:114`：judge 使用非流 complete，temperature=0、maxTokens=4096，没有专用 thinking override，也没有独立更长 timeout override。`:49`–`:52` 保存同一次 unknown paid ledger 与实际失败用量。
- `evaluation/ragas.ts:49`–`:62`：RPC 模型失败时保存原错误并取消 owned worker；子进程取消的后续错误不会替代已保存的 model_timeout。
- `jobs/queue.ts:157`–`:162`：manual paid work 的 resultUnknown=true 映射为 interrupted，并保留未知结果事实；没有自动重放。
- RagasBridge 默认 worker 总预算为 300,000 ms（`evaluation/ragas.ts:25`）。本次评分阶段 148,308 ms 就结束，排除这个总超时作为触发。任务租约有效、cancel_requested_at 空、日志无 cancel_requested，而且 paid 脚本 900,000 ms 外层截止也没有达到。
- Worker 在每一行的全部 metric 完成后才发送 progress（`workers/evaluation/worker.py:144`–`:145`）；executor 在完整批次返回后才保存 scores（`:119`–`:120`）。`EvaluationStore.dto` 的 completed_questions 来自完整 scores 行。因此 5 个答案成功而 completed_questions=0 并不矛盾；本次无完整分数报告，不计五题评测 PASS。未打开加密 checkpoint 验证任何答案正文或 metric 私有数据。

公开配置显示 judge 为 glm-5.3-flash，没有显式 thinking mode/effort；前三次实际 usage 均有 reasoning。冻结 thinking adapter 对已验证 GLM 端点/model 对的 default policy 开启 thinking，不指定 effort；已有 auxiliaryThinking 则提供 on/low，但本执行器没有调用它。**这些事实不足以证明 thinking 是第四次延迟的原因**。本轮没有读取保存的 endpoint 或记录请求 body，也没有把默认适配器行为当作厂商线缆实录。

JSON/schema 错误路径与本次不同：worker 的 `response_model.model_validate_json` 失败会输出固定 `ragas_scoring_failed`，协议问题会得到 `ragas_protocol_invalid`；本次实际 paid ledger 和用量错误均为 model_timeout。没有证据将这次终止归因于 JSON、Django、worker bootstrap 或 lease；这也不承诺所有后续 judge JSON 都会有效。

## 代码与正式构建身份

19 个相关源码文件 SHA 与正式 source manifest 相等；12 个实际编译模块/worker SHA 与 payload manifest 相等。它们覆盖 executor、Ragas/store/service、ModelRuntime/provider/thinking、model configuration/startup、JobQueue/owned process、独立 worker，以及补充检查的 settings/API 路由和 startup 页面字段。正式构建身份同时匹配已关闭 paid receipt：

- prepared SHA `44272b04f54ff0a03f56bbe5ebca502f6267086ac1b862f0e413ff6b45cc1629`。
- gates SHA `860dba721dd62e74ad76a236c5db5585b43b8d5d89e1de168a52efac7832b8aa`。
- payload manifest SHA `0082290f3a4dcd9b6c0d8c067914a05e7b853b26f4f81464198eec24a656d559`。
- 原 preparation JSON SHA `ba14809907788a47aa097a30a69649172c52366bea14e2681ec9e338cc24c56a`。
- 原 paid JSON SHA `d1ea5ef8f8a21b325ec0b3dc3a05366c08b1b2a9d39c5b30322a3d0f97bed76c`；原安全 log SHA `46c7d569d9563f7e53e194cc1d1007ec297a6d430e680a6796d2bf0056615d1b`。

本轮只核对与故障相关的已冻结文件和身份，未重新扫描全部 25,279 个 payload 文件，不重新宣称完整打包/GUI/厂商验收。

## 已有合法配置入口与专属预算边界（只读检查）

全局模型 timeout 已有正常入口，不需要篡改 DB：GET / PUT `/api/v1/system/config/startup`，写入 `model_timeout` 整数 1–600 秒。`SettingsService.administrator` 会向真实 AuthService 核对当前用户 is_system_admin，不能仅依靠调用者声称管理员。页面现有启动配置表单包含模型超时字段，保存提示重启后生效；这里只核对源码，不计 GUI 实测。保存文件为 `.settings/startup.json`，active 是各服务构造时的快照，需正常重启 Core。`MARLIN_MODEL_TIMEOUT` / `LLM_CHAT_MODEL_TIMEOUT` 是已存在的启动环境覆盖，GET projection 返回 saved、active、restart_required 和覆盖字段名；本轮没有读取秘密环境变量或调用这些 API。

另有租户 admin 的 `PUT /api/v1/models/:id`，正常 parameters 可指定 timeoutMs（毫秒）或 timeout（秒）；有效值按 timeoutMs → timeout → startup fallback 顺序取用，最终必须为支持 timer 范围内的正整数。它影响所有使用该模型的场景，不能当成仅评测配置。

现有评测 run 的 normalized input 没有专属 timeout（`evaluation/index.ts:105`），额外传入 timeoutMs 不会进入生效配置。executor judge 没有传 `ModelCallOptions.timeoutMs`；该 trusted 底层选项虽然存在，但专属评测覆盖需要另行审阅的产品修改，当前没有实施。standalone RagasBridge 的 `RagasCallOptions.timeoutMs` 控制 worker 总预算，不控制单次模型 HTTP；当前 Core `EvaluationOptions` 也没有此 worker timeout 配置字段。不能向现有 endpoint 塞字段后声称预算已改变。

## Manual resume、签名与评分 checkpoint（只读检查）

`POST /api/v1/rag-eval/runs/:id/resume` 经当前 eval.write 与本人 job 权限核对。存在 pending/unknown paid ledger 时，只接受 `acknowledge_unknown_paid_request === true`；缺少明确承认会返回 409 / paid_result_unknown。随后仍先核对源 fingerprint 与完整有效 ModelConfiguration 的签名，匹配才 acknowledged pending/unknown/failed ledger；completed ledger 保持。**提高有效 timeout 或改变 thinking 后，再 resume 原 run，会先得到 409 / checkpoint_mismatch**：签名包含这些有效参数，manualack 不绕过配置/来源围栏。改参数并新建 run 是新的可能付费动作，本轮没有做。

保持原配置、显式 manualack 的情况下，interrupted/failed 原 job 被排回 queued，执行时 attempt 增加；cancelled 情况才建立新 run 并共享原 ledger_id/已保存 answers。本次是 interrupted。executor 对已保存的答案跳过检索、rerank 和回答；评分 worker 仍从整行、整批次重新走 metric 流程，但 `invoke` 对相同 key/hash 的 completed RPC 直接返回加密保存结果，不再发模型 HTTP，不重复写 usage。unknown 的第四次请求在人工 ack 后允许用新 invocation UUID 再发一次，存在重复厂商计费风险。

这不是“从未完成的 metric 接着跑”：scores 只按完整 worker 批次保存，当前 executor 不从单 metric checkpoint 恢复。若 prompt/hash 或配置不同，会被现有检查拒绝，不能默认完成调用都可重用。本轮只读确认 18 completed + 1 unknown ledger 和公开 completed_questions=0；没有打开加密 answers/scores/请求内容，也没有执行 resume。

旧的失败/unknown model_usage receipt 保留；后续实际请求另有新 UUID/attempt 的账实记录。最终 `metrics.usage.calls` 统计的是完成的逻辑 ledger，不等于跨 attempt 所有已发送请求或实际供应商账单；手工重放后的费用审阅必须包含旧 unknown 与新请求，不能沿用本次冻结的 19 条统计或“所有调用成功”的脚本断言。本轮原五题脚本本身没有 resume 模式，不能把其一次 POST 控制当作已经审阅的重放入口。

## 最小安全复现设计（未执行）

使用全新独占 SQLite，通过正常 CoreIpcAdapter 注册/登录自己的测试账户；只配置自己的 loopback HTTP fixture。沿正式 EvaluationExecutor → 实际 Ragas 0.4.3 RPC worker → ModelRuntime 链路，前三次 judge 返回真正符合当前 schema 的 JSON；第四次 HTTP completion 保持未返回，跨越显式设置的短模型截止。fixture 只能接受自己的地址，未授权外域访问立即失败。

断言第四次仅一个请求；产生 model_timeout、恰好一个 unknown ledger 与失败 usage，并用 actual invocation ID 精确关联；manual job interrupted / result_unknown=true、progress 0.3、无报告、无自动重放；owned helper 真正退出且无关进程存活。另分开设计 malformed JSON 与 helper 截止对照，验证其独立错误分类，不把所有失败归为模型超时。resume 另作隔离对照：无 ack 零请求拒绝；显式 ack 后只重发 unknown/新工作并复用 completed 回应；变更 timeout/thinking 则在 ack 前因 checkpoint_mismatch 拒绝；记录跨 attempt 全部真实 usage。这些受控结果将只能证明本地控制链路，不能证明供应商速度或五题真实完成。

若后续决定调整辅助 judge thinking，应先捕获受控请求，验证 default 与已支持 on/low policy 的实际线缆参数及现有 JSON/指标语义；不修改用户 chat policy，不对不支持的模型强加参数。单独提高模型 timeout 也不能证明五题能进入同一批次独立的 300 秒 worker 预算。是否变更预算或进行新的 paid run，需要 root 根据真实 unknown receipt 与费用风险作决定；本轮没有实施或发起。

本次 Linux/NTFS 临时 Python/PowerShell 和其临时安全输出已按精确路径删除，独立持久证据保留。原私有副本、formal stage、paid attempt marker、原日志及未知结果均保持原样。
