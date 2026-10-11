# 固定五题 manual resume 私有工具计划（2026-10-10）

本工具只准备给 root 审阅。本轮禁止启动 Core、执行 API、模型请求、GUI、安装、改源码/stage/私有业务 DB。原 unknown 请求可能已计费；同配置人工恢复仍可能重复计费，也不保证能在模型 60 秒、Ragas worker 300 秒内完成。原五题工具和本工具不能相互替代或自动重试。

目标仅为 run `def03505-f77e-453f-b847-80d29ee9acc8`、dataset `65e6892b-aa68-4961-bf6e-cb9f32fd0b65`、KB `589830ad-4289-46b7-8e67-18d3089b674e`。固定私有副本及父 `.marlin-vendor-eval-owned` 沿原 [preflight](20261010-real-vendor-evaluation-preflight.md)。正式 stage 为 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010`，不得指向 visible-data、其他账户/副本或旧 Formal stage。

## 分阶段边界

临时脚本为 `/tmp/marlin-real-vendor-five-case-resume-20261010.cjs`，本轮仅该 handoff、本计划及独立静态证据。默认 `review-only`：输出固定 scope/预算/风险，不加载 Core 或数据库；未知参数/缺值/混合 phase 拒绝。`--prepare-zero-paid`：在 root 后续明确执行时才做完整 stage/payload/Electron/正式 facts/源绑定，以及正常 saved IPC auth、固定 gold、dataset、完整 corpus、原19个 usage / 18 completed + 1 unknown ledger 校验。内部 fetch guard 拒绝零付费阶段的意外 fetch；不调用 Ragas capabilities、estimate 之外的评分或生成方法。

`--execute-reviewed-resume` 必须绑定新 preparation 原字节 SHA 与 root 独立制作的 review receipt 原字节 SHA。Receipt 包含本脚本 SHA、固定 run/dataset/build 身份、source/model 签名摘要、原 unknown invocation SHA、exact boolean unknown/可能重复计费确认，以及唯一一次 POST 和固定预算。工具不能替 root 生成批准文件。此前任何恢复 marker 都拒绝；独占 wx + fsync marker 在释放 fetch guard、实际 POST 之前完成。

所有执行 phase 由正式编译的 `OwnedProcessRegistry` 把同一冻结脚本的固定 child 包入真实 Windows private Job；不提供任意命令接口。15 分钟 outer deadline；正常取消最多 POST 固定 run/cancel 一次并等待关闭。Crash/未知结果保留 marker/账本，不自动重放。前置私有临时 lock 防并行 Core，只有正常关闭后才删除自己的 lock；异常遗留需要人工审查。构造 Core 前还用 readonly SQLite 核全副本 desktop_jobs、agent_actors、task_records 和 dataset generation 无非终态，防启动恢复旧任务。

## 正常身份与签名检查

使用正式 `CoreApplication(...,{allowAutoSetup:false,evaluation:{ragas:{...}}})` 和 `CoreIpcAdapter` 保存会话。401 时至多一次正常 refresh；不提取 token/密码、不生成 AuthContext、不借管理员。身份必须等于原 gold approval/preparation/paid receipt。

内部一次性只读 handler 不监听 HTTP，只有这个 helper 的正常已认证 IPC 可调用。它通过 `EvaluationStore.row/checkpoint`、`models.configuration` 和正式 `corpusFingerprint` 在内存比较加密 checkpoint 的源/完整有效配置签名；只返回相等布尔、5个保存答案计数、逐题已保存 contexts.length 安全整数（固定 gold 顺序、每题1..5）与摘要，不输出 checkpoint、正文、配置、endpoint、Key 或密文。真实 `eval.write` 与 `jobs.get` owner 检查仍执行。全部模型有效 timeout 必须保持60000ms；不设置 ModelCallOptions 超时/thinking，不覆盖 worker 默认300000ms。

## 跨 attempt 账实核验

旧19个 usage 的 actual UUID（输出 SHA）和全部白名单计数必须原样保留，其中 attempt1 的 `evaluation_judge` 原 unknown receipt 必须仍为失败、unknown、`model_timeout`、60005ms；不是要求所有历史请求成功。准备阶段没有新 usage/invocation。完成时从真实 ledger logical ID/hash/UUID 与全部 attempt usage 一一核对：原18个 completed 均保留同一 hash/UUID，不新增重复 usage；原 unknown logical slot 被新 UUID 重试时明确关联旧 receipt，新调用按 attempt/scenario 另列。旧 embedding/rerank/answer 每种5个全部成功，但新 attempt 不应重做已保存的检索回答。

`metrics.usage.calls` 仅作为完成逻辑 ledger 计数核对，不当跨 attempt 请求数或厂商账单。未知请求 token0 表示没有收到 usage，不表示无费用。若最终失败/中断/取消，保存当前安全账本和实际已发 usage；不生成成功报告或自动 resume。

成功才通过正常 IPC 获取真实 binary，保存新独占报告文件并重开：核字节 SHA、canonical metrics SHA、固定run/source/dataset/current配置、5samples/valid_coverage1、3项真实有限指标、未实现指标null及完整语料。GUI verified 永远 false；低分保留，不替换、不减少 distractor。

## 实施与本轮验证

- [x] 先写离线 parser/白名单/原账本/跨attempt核验测试；确认缺实现的 RED。
- [x] 实现临时脚本，只复用已审原五题工具的身份/源/gold/report校验，不修改原工具。
- [x] 只运行 `node --check`、默认 review-only、非法参数拒绝与纯函数静态 fixture 测试。不运行 prepare/execute、Windows或 Core/API。
- [x] 检查计划相对链接、本脚本/测试/日志 SHA，冻结交 root 全文审阅。清理本轮测试 runner；handoff 脚本待 root 用后删除。

这是审阅和静态准备，不是实际恢复通过、厂商请求通过或 GUI 验收。

## 冻结与本轮证据

工具已冻结：471 lines、78024 bytes，SHA256 `40b33233eba3f49ea6bf35958c89075ab298c4439af28abddc648357bc4c033d`。未修改原五题 utility、任何产品源码、stage 或私有副本。`node --check` exit0；[最终原始 TAP](20261010-five-gold-manual-resume-static-green.tap) 14/14、0 failed/skipped/cancelled/todo，231.91735ms。[CLI 静态证据](20261010-five-gold-manual-resume-cli-static.json) 含默认、review-only 与8项非法输入，10/10符合预期。它们实际没有加载 Core、打开 SQLite、调用 API 或 Windows helper。

[静态测试源](20261010-five-gold-manual-resume-static-test.cjs) 只读取此前脱敏 readonly JSON、构造人工 attempt2 账实 fixture、验证纯函数，以及在独立临时目录验证真实 wx/fsync 文件拒绝覆盖。[安全函数 RED](20261010-five-gold-manual-resume-static-safety-red.tap) 与[非终态围栏 RED](20261010-five-gold-manual-resume-static-active-red.tap) 是尚未实现本临时工具函数的静态失败；不计生产缺陷复现、真实 SQLite、Windows 进程或厂商通过。[验证汇总](20261010-five-gold-manual-resume-static-verification.json) 保存全部原字节 SHA/范围和源码位置。本轮禁止运行有效 prepare/execute，故 saved context 逐题整数尚未获取，不能伪造实际计数。

## 当前串行评分与预算事实

正式代码走 `workers/evaluation/worker.py` 的集合指标 `ascore`，没有调用 `ragas.evaluate`、Ragas Executor 或设置 max_workers。Python 第129–139行顺序循环每题/每个指标；第74–86行每个 RPC 发出后同步读回一条结果。`packages/core/src/evaluation/ragas.ts` 第44–52行在 `processing` 期间拒绝第二个未完成 model_call，因此实际评分并发为1；`packages/core/src/evaluation/executor.ts` 第108–120行 await 单个5题 batch。默认 worker deadline 是 ragas.ts 第25行300000ms，包含实际进程启动、依赖导入、缓存结果往返/解析和全部评分。

原18个 completed 请求含5 embedding +5 rerank +5 answer +3 judge。3个 judge 的真实 vendor duration 为7130、39003、26060ms，合计72193ms；resume 只有重放到完全相同 logical key/hash 后才能读回缓存并省去这些网络等待。另15检索/回答合计26200ms，保存的5个 answers/contexts 让 executor 第84–85行跳过这一段。缓存不会把整个 Python batch 的 CPU/启动/解析时间清零，也不代表整题完成：当前完成评分行0，5题都要重新走评分逻辑。

随包 Ragas0.4.3 `metrics/collections` 实际源码：Faithfulness 每题2个 judge（若 statements 空会产生非有限分并停止）；AnswerRelevancy strictness3 顺序3个 judge，之后原问题/生成问题批量各1 embedding；ContextPrecisionWithReference 每个实际 context 1 judge。正常生成非空问题路径的全五题评分为25个 judge +10 embedding +Σcontexts；已有3个 judge 缓存，新增为 **22+Σcontexts judge、10 embedding，共32+Σcontexts**。受控 prepare 会投影真正已保存5题的 context 整数，不打印文本；每题1..5时正常路径需37..57个新请求，包含原 unknown slot 的明确人工重试。若某题三次 generated question 均为空，会跳过该题2 embedding；异常可提早停止，因此这不是实际请求保证或厂商账单。public estimate 原55..75总逻辑请求减18个缓存得到同一正常预算，仍保留其估算性质。

串行新请求若各接近60s，37..57个需要2220..3420s（37..57分钟），超过 renewed300s worker。要在300s内完成，仅算网络的平均每请求需约8.108..5.263s，还须留启动/缓存/CPU时间；已观察成功 judge 39.003s和26.060s，第四个60005ms未知，所以一次恢复仍很可能再次超时/中断，不能承诺完成。15分钟 outer只是独立 owned wrapper 的最终清理预算，不扩模型60s或 worker300s。本工具保留 thinking、maxTokens、timeout 和完整配置签名，任何变化拒绝；本轮不为通过改配置/调并发或重发。

## root 审阅后的分阶段命令（本轮没有执行）

root 必须先完整读取冻结脚本；自行原字节复制到固定私有父目录，核上述 SHA，再决定仅执行 prepare。固定父目录为 `C:\Users\lxd\AppData\Local\Temp\Marlin 评测验收 20261010`。原输入文件实际名为 `five-gold-approved-preflight.json`、`five-gold-final-preparation.json`、`five-gold-final-paid.json`，输入原字节 SHA 均固定在脚本；原 paid attempt marker 保留。以下只是给 root 的未来手工命令，不是批准回执或本轮执行记录。

```powershell
$stage = 'C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010'
$qaParent = 'C:\Users\lxd\AppData\Local\Temp\Marlin 评测验收 20261010'
$node = Join-Path $stage 'app\payload\node\node.exe'
$tool = Join-Path $qaParent 'five-gold-resume.cjs'
$sharedArgs = @('--stage-root', $stage,
  '--data-root', (Join-Path $qaParent '四模型私有数据副本'),
  '--gold-approval', (Join-Path $qaParent 'five-gold-approved-preflight.json'),
  '--original-preparation', (Join-Path $qaParent 'five-gold-final-preparation.json'),
  '--original-paid', (Join-Path $qaParent 'five-gold-final-paid.json'))
# 仅 root 独立审阅后决定运行；会正常启动/关闭私有 Core，但模型请求必须0。
& $node $tool '--prepare-zero-paid' @sharedArgs '--report' (Join-Path $qaParent 'five-gold-resume-preparation.json')
```

新 preparation 必须在 owned Core close 后落盘、原19 usage/18 completed/1 unknown仍原样、无新请求、source/model签名相等、完整corpus不变、closed DB/WAL/SHM SHA保存、私有lock正常释放。prepare 不是只读 DB：正常 saved IPC auth refresh 和 Core 生命周期允许其正常保存账户会话状态；它是零模型请求验证。本轮没有执行它。

root 再独立读 preparation 原字节/原 unknown 账本/真实5 context计数和预算，决定是否接受可能重复计费，独立制作 `five-gold-resume-root-review.json`。严格对象不接受额外字段，值来自已核 preparation；tool 不替 root 写 approval。

```json
{
  "format": "marlin-five-gold-manual-resume-review-v1",
  "approved_by": "root-explicit-review",
  "run_id": "def03505-f77e-453f-b847-80d29ee9acc8",
  "dataset_id": "65e6892b-aa68-4961-bf6e-cb9f32fd0b65",
  "tool_sha256": "40b33233eba3f49ea6bf35958c89075ab298c4439af28abddc648357bc4c033d",
  "preparation_sha256": "<new preparation 原字节 SHA256>",
  "build_identity": "<完整复制 new preparation.build_identity 对象，而非字符串>",
  "source_fingerprint_sha256": "<new preparation.signature_check.source_fingerprint_sha256>",
  "configuration_signatures_sha256": "<new preparation.signature_check.configuration_signatures_sha256>",
  "original_unknown_invocation_sha256": "<new preparation.baseline.original_unknown.invocation_sha256>",
  "acknowledge_unknown_paid_request": true,
  "acknowledged_possible_duplicate_charge": true,
  "resume_post_limit": 1,
  "outer_timeout_ms": 900000,
  "model_timeout_ms": 60000,
  "worker_timeout_ms": 300000,
  "automatic_retry": false,
  "gui_verified": false
}
```

上述含占位符的 JSON 只是契约说明，不能作为有效 approval。root 完成独立手工批准和文件哈希后，才可考虑以下唯一一次执行；该工具不能生成新run，也不能继续使用原五题工具 POST runs。

```powershell
$prep = Join-Path $qaParent 'five-gold-resume-preparation.json'
$review = Join-Path $qaParent 'five-gold-resume-root-review.json'
$prepSha = (Get-FileHash -LiteralPath $prep -Algorithm SHA256).Hash.ToLowerInvariant()
$reviewSha = (Get-FileHash -LiteralPath $review -Algorithm SHA256).Hash.ToLowerInvariant()
& $node $tool '--execute-reviewed-resume' @sharedArgs `
  '--report' (Join-Path $qaParent 'five-gold-resume-result.json') `
  '--reviewed-preparation' $prep '--reviewed-preparation-sha256' $prepSha `
  '--root-review' $review '--root-review-sha256' $reviewSha
```

独占 `five-gold-resume-attempt-def03505-f77e-453f-b847-80d29ee9acc8.json` 必须wx创建并fsync早于付费边界；存在就立即停止，成功/失败/超时均不删除。不接受自动重试/resume/re运行；未知处保留账本和结果事实，不能仅删marker重跑。正常取消最多对该run POST cancel一次；外层真实 OwnedProcessRegistry 负责Windows私有Job及最终清理。本轮没有新的Windows Job实测，复用冻结生产接口不算本工具实际Win通过。

只有本次明确 attempt2 verified/completed 才下载真实IPC binary，原字节独占保存并重开核SHA/metrics/source/current配置/5samples/validcoverage1/三真实指标/未实现null。账单审计按固定 job_id+四 scenario+actual UUID聚合全部 attempt；metrics.usage.calls仅当前完成逻辑slot，不会抹去原unknown历史请求。即使成功也保留原unknown可能已付费说明，不宣称厂商账单确定；GUI始终false。
