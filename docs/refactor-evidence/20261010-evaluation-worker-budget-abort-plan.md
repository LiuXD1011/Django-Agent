# 五题真实评测：评分 worker 预算与在途取消实施计划

> **执行者须知：** 产品源码仍冻结。收到根代理明确释放通知后，使用 executing-plans 按下面的红→绿步骤实施；本文件不授权执行产品修改、Core/API、模型请求或 GUI 操作。本轮仅保存审查与计划，不提交。

**目标：** 根据当前评分算法、实际上下文数量与既有模型超时，为每次评分 worker 提供有上限的预算；worker 到达期限时先取消在途模型 signal，再等待调用审计与进程清理结束。

**结构：** 新增一个评分预算纯函数，executor 使用它分批并传入既有 `RagasCallOptions.timeoutMs`。Bridge 自己管理评分期限，沿用原有 AbortController 和 owned supervisor。模型配置、worker 算法及恢复账本保持原规则。

**技术：** TypeScript 6.0.3、Node 类型 22.19.15、原生 fetch、既有 OwnedProcessRegistry、Python JSON-lines RPC、锁定 Ragas 0.4.3 collections。

## 冻结与范围

- 不改变 faithfulness / answer_relevancy / context_precision、strictness=3、提示词、temperature=0、maxTokens=4096、答案、contexts、阈值或 GLM thinking。
- 不新增界面、产品配置字段、依赖、迁移或自动重试。
- 不改模型/证据签名校验、调用 key/hash、ledger_id、invocation UUID、completed 复用或 pending/unknown 人工确认。
- 产品执行前必须重新完整读取实际受影响文件，并核查冻结期间是否有变化。
- 本文件中的代码是拟议实现；未写入产品，未执行任何测试。

## 已确认事实与证据

1. [executor](../../packages/core/src/evaluation/executor.ts) 当前最多 50 题一批，调用 Bridge 时只传 signal/onProgress，没有 timeoutMs；[Bridge](../../packages/core/src/evaluation/ragas.ts) 默认 300000ms，合法上限 3600000ms。预算从 worker 启动起算，仅覆盖评分，不覆盖检索与答案阶段。
2. [worker](../../workers/evaluation/worker.py) 按题、指标串行。CoreLLM.agenerate 直接执行同步 stdin RPC；collections API 不经过旧版 RunConfig/retry 包装。正常每题 faithfulness=2 chat、answer_relevancy=3 chat+2 embedding、context_precision=C chat，其中 C 为实际传入 contexts 数量。无 generated questions 时省去两个 embedding，不能据此降低正常预算。
3. executor 当前实际 C=1..5，因此评分每题正常 8..12 请求。五题 hybrid+rerank 的前阶段为 15 请求，正常全链 55..75；已有 18 个 completed 后，仍需 37..57 次新请求。这里是算法上界/下界，不是厂商计费保证。
4. [模型配置服务](../../packages/core/src/settings/model-configuration.ts) 在没有显式 timeoutMs/timeout 时注入 active startup.model_timeout。 [startup](../../packages/core/src/settings/startup.ts) 默认 60 秒、产品设置范围 1..600 秒、重启生效；[provider](../../packages/core/src/models/providers.ts) 的真实优先级为 timeoutMs > timeout×1000 > 60000。预算复用这个解析结果，不重复猜测参数规则。
5. 现有 SettingsService、system-fields、EvaluationOptions、RagasOptions、desktop 入口均没有评分总预算产品设置。后台 task_workers 不会增加 worker 内 RPC 并发。
6. [Bridge](../../packages/core/src/evaluation/ragas.ts) 当前 await owned.completion 的错误处理之后，先 await modelCalls，再在 finally 中 abort。 [owned registry](../../packages/core/src/jobs/owned-process.ts) 的 timeout 只停止子进程；在途模型可能继续等待自身超时。此结论来自静态源码，尚未运行回归复现。
7. [恢复服务](../../packages/core/src/evaluation/index.ts) 会重新比较 configurations/fingerprint；executor 每次调用也比较模型 digest。修改模型 timeout/thinking 或重启后改变模型实际 fallback timeout，会阻止旧 run 继续，不得删除该围栏。
8. GLM glm-5.3-flash 当前 default 已发送 thinking.enabled，judge 没有辅助 low override。本方案不改变它。

锁定依赖核查：正式 Windows payload 的 `python/Lib/site-packages/ragas-0.4.3.dist-info/METADATA` 确认 0.4.3；collections 的 Faithfulness / AnswerRelevancy / ContextPrecisionWithReference 与 worker 所用类一致。Faithfulness metric.py SHA256=`f3850ad76e173c932dff09464489934f7df7c499a8e43b178cd69f339511965d`，ContextPrecision metric.py SHA256=`14854b05af2e30e540b54e3e748ca405a877965b86cea1d1023957cc0c08eecc`，与已完整阅读的 Linux 安装源码相同。

已完整阅读相关生产文件：executor、ragas、evaluation/index、store、worker、owned-process、JobQueue、startup、model-configuration、settings、providers、thinking、usage-audit；读取现有 contracts 的实际 ModelConfiguration/ModelCallOptions 类型及 @types/node AbortController/AbortSignal/timer 声明。已完整阅读 evaluation.test.ts、evaluation-retention.test.ts、evaluation-bytecode.test.ts、settings.test.ts、jobs.test.ts、workers/evaluation/test_worker.py。worker/配置/service/store 为只读边界，不列入产品改动。

## 推荐方案与预算公式

推荐沿用已冻结的单次模型超时，不另设 judge 超时，不改 settings/service/store/worker。

对每题实际 C，保守正常上界为 J=5+C 次 judge、E=2 次 embedding。单题调用预算为 `J*Tjudge + E*Tembed + (J+E)*1000`；每个 worker 加 60000ms 冷启动/固定处理余量，最终至少 300000ms、最多 3600000ms。一秒/调用、60秒/启动是拟议执行余量，不是已测量 SLA。未知或失败请求不自动重试；已完成结果复用仍保留完整预算，不为了省时间改账本。

按原始行顺序贪心分批，每批最多 50 题，加入下一题会超过一小时就提前结束该批。整个计划先完成校验，禁止执行前几批以后才发现某一题无法容纳。如果一题单独超过上限，抛固定 `evaluation_budget_exceeded`，不偷偷截短模型超时或提高上限。

| 实际上下文/题 | judge/embedding 单次超时 | 五题分批 | 每个 worker 预算 |
| --- | --- | --- | --- |
| 1 | 60s / 60s | 5 | 2500s |
| 5 | 60s / 60s | 4 + 1 | 2988s、792s |
| 5 | 120s / 60s | 2 + 2 + 1 | 2724s、2724s、1392s |

这些是有限的保守期限，不是预计实际耗时。原有 2MiB 输入、32MiB 输出、RPC 数量及 worker 进程隔离限制继续生效。

备选方案：只统一提高 Bridge 常量改动少，但不同样本量/超时仍会不匹配；新增配置界面或 RPC 并发改动更大。两者均不列入本次最小实现。

## Task 1：按实际评分行规划有界批次

**新增：** `packages/core/src/evaluation/budget.ts`、`packages/core/test/evaluation-budget.test.ts`。

**修改：** `packages/core/src/evaluation/executor.ts` 评分循环；不公开新增前端接口。

**接口：** `planRagasBatches(rows: RagasRow[], judge: ModelConfiguration, embedding: ModelConfiguration): RagasBatch[]`；每个批次 `{ rows, offset, timeoutMs }`，offset 用于保持原有全局进度和顺序。

- [ ] 先写纯函数红测试：空行无批次；五题 C=1/T=60s 得 2500000ms；五题 C=5/T=60s 得 [4,1]/[2988000,792000]；不同 judge/embed 超时分别加权；timeoutMs 覆盖 timeout；单行超限固定错误；50题原有批大小边界；拼接所有 batches.rows 与输入逐行一致。

```ts
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ModelConfiguration } from '../src/contracts.js';
import type { RagasRow } from '../src/evaluation/ragas.js';
import { planRagasBatches } from '../src/evaluation/budget.js';

const model = (parameters: ModelConfiguration['parameters']): ModelConfiguration => ({
  id: 'protocol-model', name: 'protocol-model', type: 'KnowledgeQA', source: 'openai',
  parameters: { base_url: 'http://127.0.0.1:9/v1', ...parameters },
});
const rows = (count: number, contexts: number): RagasRow[] => Array.from({ length: count }, (_, i) => ({
  example_id: String(i), question: 'Question', answer: 'Answer', reference: 'Reference',
  contexts: Array.from({ length: contexts }, () => 'Evidence'),
}));
test('actual five-context scoring is split before the worker ceiling', () => {
  const input = rows(5, 5), cfg = model({ timeout: 60 });
  const batches = planRagasBatches(input, cfg, cfg);
  assert.deepEqual(batches.map(batch => batch.rows.length), [4, 1]);
  assert.deepEqual(batches.map(batch => batch.timeoutMs), [2988000, 792000]);
  assert.deepEqual(batches.flatMap(batch => batch.rows), input);
  assert.deepEqual(batches.map(batch => batch.offset), [0, 4]);
});
test('model timeout precedence is reused from the actual provider resolver', () => {
  const batches = planRagasBatches(rows(1, 1), model({ timeout: 1, timeoutMs: 120000 }), model({ timeout: 60 }));
  assert.equal(batches[0]!.timeoutMs, 908000);
});
test('an individual row exceeding the ceiling is rejected before dispatch', () => {
  assert.throws(() => planRagasBatches(rows(1, 5), model({ timeout: 600 }), model({ timeout: 60 })),
    { code: 'evaluation_budget_exceeded' });
});
```

- [ ] 在 `packages/core` 执行 `node --import tsx --test test/evaluation-budget.test.ts`，应因模块/实现缺失失败；保存红结果。
- [ ] 实施下列预算函数；不导出解密参数或 headers。

```ts
import type { ModelConfiguration } from '../contracts.js';
import { resolveProvider } from '../models/providers.js';
import { fail } from './common.js';
import type { RagasRow } from './ragas.js';

export interface RagasBatch { rows: RagasRow[]; offset: number; timeoutMs: number }
const ceiling = 3600000, floor = 300000, bootstrap = 60000;
export function planRagasBatches(rows: RagasRow[], judge: ModelConfiguration, embedding: ModelConfiguration): RagasBatch[] {
  const judgeMs = resolveProvider(judge).timeoutMs, embedMs = resolveProvider(embedding).timeoutMs;
  const result: RagasBatch[] = [];
  let current: RagasRow[] = [], offset = 0, cost = 0;
  const flush = () => {
    if (!current.length) return;
    result.push({ rows: current, offset, timeoutMs: Math.max(floor, bootstrap + cost) });
    offset += current.length; current = []; cost = 0;
  };
  for (const row of rows) {
    const contexts = row.contexts.length;
    if (!Number.isSafeInteger(contexts) || contexts < 1 || contexts > 5)
      fail(400, 'invalid_evaluation_input', 'Scoring contexts must follow the evaluation context policy');
    const judges = 5 + contexts;
    const rowCost = judges * judgeMs + 2 * embedMs + (judges + 2) * 1000;
    if (!Number.isSafeInteger(rowCost) || bootstrap + rowCost > ceiling)
      fail(422, 'evaluation_budget_exceeded', 'One scoring row exceeds the supported worker budget');
    if (current.length === 50 || bootstrap + cost + rowCost > ceiling) flush();
    current.push(row); cost += rowCost;
  }
  flush(); return result;
}
```

- [ ] 在原 executor 添加顶层 import；将固定 offset+=50 改为下述循环入口，将原 Bridge 第一个参数换成 batch.rows，将 options 增加 timeoutMs。原 callback 内容、调用 key/hash 和汇总逻辑逐字保留。

```ts
const batches = planRagasBatches(rows, config('judge'), config('embedding'));
for (const batch of batches) {
  const offset = batch.offset;
  // 原 bridge.evaluate 的 rows 参数使用 batch.rows；模型 callback 原样保留。
  // 原 options 使用：
  const bridgeOptions = {
    signal: job.signal,
    timeoutMs: batch.timeoutMs,
    onProgress: (completed: number, total: number) => job.progress(0.3 + 0.65 * (offset + completed) / rows.length),
  };
  // 将 bridgeOptions 直接传给原 bridge.evaluate，并保留原 allScores/checkpoint 写入。
}
```

上面是局部替换位置说明，不是独立可运行 executor；不得另建空的评分循环。无需改 EvaluationService/preflight/effective_pipeline，也不新增预算字段进入旧签名。

- [ ] 增加 executor 回归：通过只在测试中的 Bridge 方法拦截，记录原 callback/rows/options 并返回受控 finite scores；断言实际 contexts 得到的 timeoutMs、行顺序、进度、checkpoint 汇总，且任何批次未改变 judge options/thinking。
- [ ] 执行预算测试与对应 executor 回归，确认由红转绿；然后 `npm run typecheck`。

## Task 2：评分期限到达时先取消模型，再等待审计

**修改：** `packages/core/src/evaluation/ragas.ts`；**新增测试：** `packages/core/test/evaluation-deadline.test.ts`。

**接口：** 保留 `RagasCallOptions` 和 `RagasOptions`。不改 OwnedProcessRegistry；它已支持 signal 取消与 owned tree 清理。

- [ ] 红测试使用真实独立 Python 协议 fixture，启动后发送一个合法 model_call，随后阻塞等待 stdin。model callback 接收真实 Bridge signal，并调用只监听 127.0.0.1 的实际 HTTP ModelRuntime；HTTP 返回不完整 body 并保持连接。模型自身 timeout=20000ms，Bridge timeout=2000ms。
- [ ] 在 callback 进入实际 HTTP 后记录 signal 的 abort；其 finally 进入一个可由测试释放的审计 gate。await 审计 gate 进入后断言 signal 已取消、Bridge promise 仍未 settled；释放 gate 后 Bridge 才可拒绝，错误为 evaluation_timeout，HTTP 连接关闭，实际请求恰好一次。测试总 bound=10000ms，不等待模型自身20秒超时。
- [ ] 原实现应失败：Bridge timeout 后模型没有及时收到 signal。测试清理仅 fixture-created 服务/进程/目录，不终止无关进程。

该回归的可执行骨架如下。它验证真实 fetch 的取消和审计等待顺序；完整数据库 usage/ledger 断言由本任务后面的业务链测试承担，不能把此 gate 当成真实业务持久化。

```ts
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { RagasBridge } from '../src/evaluation/ragas.js';
import { ModelRuntime } from '../src/models/runtime.js';

async function within<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([promise, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('Controlled fixture deadline exceeded')), ms);
    })]);
  } finally { clearTimeout(timer); }
}
test('worker deadline aborts HTTP before awaiting audit and preserves timeout cause', { timeout: 15000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-evaluation-deadline-'));
  const workerPath = join(root, 'deadline fixture.py');
  writeFileSync(workerPath, [
    'import json,sys,uuid',
    'r=json.loads(sys.stdin.readline())',
    "print(json.dumps(dict(protocol=1,id=r['id'],type='model_call',call_id=str(uuid.uuid4()),example_id=r['rows'][0]['example_id'],call_index=1,operation='chat',prompt='fixture',schema=dict(type='object'))),flush=True)",
    'sys.stdin.readline()',
  ].join('\n'));
  let requests = 0, disconnected = false, audited = 0, settled = false;
  const signals: AbortSignal[] = [];
  let releaseAudit!: () => void, auditStarted!: () => void;
  const auditGate = new Promise<void>(resolve => { releaseAudit = resolve; });
  const auditing = new Promise<void>(resolve => { auditStarted = resolve; });
  const server = createServer(async (req, res) => {
    for await (const chunk of req) { /* Drain this fixture request. */ }
    requests++;
    res.on('close', () => { disconnected = true; });
    res.setHeader('content-type', 'application/json'); res.write('{');
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); assert(address && typeof address !== 'string');
  const pythonExecutable = process.env.MARLIN_TEST_PYTHON ?? '/usr/bin/python3';
  const bridge = new RagasBridge({ pythonExecutable, workerPath });
  const runtime = new ModelRuntime({ id: 'protocol', name: 'protocol', type: 'KnowledgeQA', source: 'openai',
    parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, timeoutMs: 20000 } });
  const pending = bridge.evaluate([{ example_id: 'deadline-row', question: 'Q', answer: 'A', reference: 'R', contexts: ['C'] }],
    async (_request, signal) => {
      signals.push(signal);
      try { const value = await runtime.complete([{ role: 'user', content: 'fixture' }], { signal }); return { content: value.content }; }
      finally { auditStarted(); await auditGate; audited++; }
    }, { timeoutMs: 2000 });
  void pending.then(() => { settled = true; }, () => { settled = true; });
  try {
    await within(auditing, 6000);
    assert.equal(requests, 1); assert.equal(signals[0]?.aborted, true);
    assert.equal(settled, false); assert.equal(audited, 0);
    releaseAudit(); await assert.rejects(pending, { code: 'evaluation_timeout' });
    assert.equal(audited, 1); assert.equal(requests, 1);
    await new Promise(resolve => setTimeout(resolve, 50)); assert.equal(disconnected, true);
  } finally {
    releaseAudit(); await bridge.close(); await pending.catch(() => {});
    server.closeAllConnections(); server.close(); await once(server, 'close');
    rmSync(root, { recursive: true, force: true });
  }
});
```

Windows 执行时必须显式设置 MARLIN_TEST_PYTHON 为独立 owned helper copy；不能使用冻结的正式 payload。若当地 supervisor 初始化比2秒长，独立平台测试用5秒 worker deadline、10秒观察边界，同时维持20秒模型timeout；不可通过删掉在途模型断言获得通过。

- [ ] Bridge 在 spawn 前设自身 timer；timer 先设置固定 timeout error，再 abort controller。spawn 的 options 删除 timeoutMs，避免两个不同原因的期限竞争；保留 env/maxOutputBytes。signal 取消仍由既有 owned supervisor 执行进程终止。

```ts
const deadline = setTimeout(() => {
  if (controller.signal.aborted) return;
  error ??= new AppError(504, 'evaluation_timeout', 'Evaluation worker did not complete');
  controller.abort();
}, timeoutMs);
deadline.unref();
```

具体生命周期：timer 放在 error 变量声明之后、registry.spawn 之前；启动异常分支 clearTimeout(deadline)；最终 finally 的第一步 clearTimeout(deadline)。spawn options 保留 `{ env, maxOutputBytes: 32 * 1024 * 1024 }`。等待 owned.completion 的 catch 无论错误来源都先固定安全 error（原错误映射保留），再 controller.abort，然后进入 Promise.allSettled(modelCalls)。模型 callback 的 catch 使用 `error ??= cause`，取消产生的后续 model_cancelled 不覆盖先发生的 evaluation_timeout/协议错误。

- [ ] 不在 deadline callback 提前 throw、resolve/reject 或发布失败；必须等模型 callback 的审计 finally、worker/owned tree 清理都结束，再结束 Bridge。client 不响应 abort 的情况仍受既有单次模型 timeout 限制，本方案不增加强制跳过审计的计时器。
- [ ] 添加没有 model_call 的超时回归、显式 cancel 与 deadline 竞争回归、成功调用无迟到 timeout 回归、close 等待审计回归。原来的 evaluation_timeout/evaluation_cancelled/协议错误、安全消息及无秘密输出断言继续成立。
- [ ] 添加业务链回归：worker 超时时 job 的配置和 owner 仍有效；在途 judge 每次实际请求只记录一条失败 usage，result_unknown=true；ledger 为 unknown，或在 owner 已丢失时保留 pending；resume 不带 acknowledge_unknown_paid_request 必须拒绝，且请求计数不变。终态可为 failed（evaluation_timeout）并显示 result_unknown=true；不要为了展示 interrupted 改 JobQueue。

## Task 3：旧 run 恢复与回归验证

**修改范围：** 测试和本说明；生产 settings/service/store/worker 均无修改。

- [ ] 构造与旧格式一致、没有新增预算字段的 checkpoint；准备 completed 答案与已完成 judge 调用，另有一个 unknown。重启服务，禁止未确认 resume；确认后使用原 ledger_id、原 key/hash，已完成答案/评分调用只读复用，unknown 只进行一次用户授权的新尝试。
- [ ] 新分批的 call_index 仍按每题从1开始：worker 原实现如此，切换批次不应改变 judge:example_id:call_index。断言 batch 拆分不会新增已完成调用的 HTTP 请求或 usage 行。
- [ ] 修改模型 timeout 或 thinking 后 resume 仍报 checkpoint_mismatch；直接 executor 路径仍报 evaluation_configuration_changed。测试中更改 source fingerprint 也必须拒绝。不能为了恢复 def03505 的旧 run 删除此校验。
- [ ] 复用已有五题真实 Ragas+本地 HTTP 测试：五题单context仍40个评分 RPC，keyword链仍45个HTTP/usage；cancel/resume原受控链仍46个实际HTTP。这是算法/协议整合验证，不是厂商通过。
- [ ] 执行相关检查，记录实际 red/green/typecheck 输出，不能在本轮文档中标为已通过：

```sh
cd packages/core
TMPDIR=/dev/shm node --import tsx --test test/evaluation-budget.test.ts test/evaluation-deadline.test.ts
TMPDIR=/dev/shm node --import tsx --test test/evaluation.test.ts test/evaluation-bytecode.test.ts
npm run typecheck
npm run build
```

由于不修改 Python/worker/依赖/前端，本改动不要求 Django 检查或前端全套测试。若最终实现扩展到 Python，按 AGENTS 增加对应 worker Python 测试及 TS 桥接测试。实际 Windows验证在获准后使用独立 helper 副本运行期限/abort/owned cleanup 与 bytecode regression；不修改冻结的正式 stage 或已安装程序。

## 旧 run 与这次真实失败的明确边界

本方案不改模型参数、回答、指标或请求指纹，因此在原模型/证据签名保持一致时，旧 run 可以在明确确认 unknown 之后恢复；扩大的是本地评分 worker 预算，不是未知请求重放授权。

这次真实记录中的 judge 单次 60秒超时仍可能重现。本方案不能保证这一次旧 run 会成功，也不会暗中把单次超时改为120秒。若用户通过现有产品设置增大模型超时，该模型配置签名会变化，需要按原规则创建新 run；旧18个已完成调用的已知事实和第19个未知结果仍保留。

如果配置过大的单次 timeout 使单题超过一小时，方案明确拒绝，而非截短请求。完整评测的最大总耗时仍随已验证样本数增长；每个 worker 期限、最多50题/批、样本上限和人工取消共同提供有限范围。

## 本轮验证状态

本轮仅只读源码/依赖与写入此独立文档。没有产品修改、测试执行、Core/API、模型请求、GUI 或 Git 提交。文档完成后仅检查本文件链接、空白与差异；执行任何上述步骤都需根代理释放源码冻结。
