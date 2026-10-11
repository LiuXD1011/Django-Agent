# 评分预算与取消修复：隔离候选补丁

本候选只在 `/dev/shm/marlin-evaluation-budget-20261010-model-runtime/work` 实施。主仓库产品源码、正式 stage、安装目录均未写入；候选补丁尚未应用，等待父代理完成安装生命周期后统一集成。审批范围依据[原审查与最小计划](../20261010-evaluation-worker-budget-abort-plan.md)。

## 可审查交付

- [candidate.patch](candidate.patch)：3 个产品文件和 3 个新增测试文件，共 311 行补丁。
- [sha256-manifest.json](sha256-manifest.json)：逐文件原 SHA / 候选 SHA，以及主仓库 180 个原 Core src/test 文件的冻结校验。
- [原 src 与 worker 全量 SHA 校验](logs/main-source-freeze-check.log)：校验命令退出 0。
- `git apply --check` 在另外的隔离原始快照上退出 0，只检查补丁，不应用。
- 主仓库本轮只新增本 evidence 目录；没有提交、推送、模型/API/GUI 操作。

隔离副本以 `OWNER.txt` 标明所有权。Core `node_modules` 通过符号链接只读复用原安装依赖；`dist`、测试数据库、辅助脚本及运行日志均留在隔离空间。受控 HTTP 模型服务只监听 `127.0.0.1`，凭据是固定 fixture 字符串。

## 最小实现

产品范围固定为：新增 `packages/core/src/evaluation/budget.ts`，修改 `executor.ts`、`ragas.ts`。没有修改 settings、models、Python worker、store、service、签名、指标或 thinking。

`planRagasBatches(rows, judgeConfiguration, embeddingConfiguration)` 导出 `RagasBatch[]`，批次包含原始顺序的 `rows`、全局 `offset` 和 `timeoutMs`。复用实际 `resolveProvider` 的模型超时解析：优先 `timeoutMs`，其次 `timeout` 秒，最后 60 秒；传入的 configuration 已包含现有 startup 设置的有效值。没有覆盖任何模型调用本身的超时。

锁定 Ragas 0.4.3 的正常串行路径每行最多为 `5 + C` 次 judge 和 2 次 embedding，其中 `C` 为实际送入评分的上下文数量（1 至 5）。预算为：

```text
rowCost = (5 + C) × judgeTimeoutMs + 2 × embeddingTimeoutMs
          + (7 + C) × 1000
batchTimeoutMs = max(300000, 60000 + Σ rowCost)
```

60 秒启动额度及每 RPC 1 秒协议额度是有上限的工程余量，不是实测厂商 SLA。每批最多 50 行且最多 3600000 ms；所有行先完成预算校验，再开始评分。单行本身超过一小时会明确报 `evaluation_budget_exceeded`，不缩短模型时限或默默删掉上下文。评分前已有的回答/检索阶段不属于这个 worker 预算。

| 5 题实际上下文 / judge 与 embedding 超时 | 批次与预算 |
| --- | --- |
| 每题 1 个 / 均 60 秒 | 5 行，2500000 ms（41 分 40 秒） |
| 每题 5 个 / 均 60 秒 | 4 行 2988000 ms；1 行 792000 ms |
| 每题 5 个 / judge 120 秒、embedding 60 秒 | 2 行、2 行、1 行；2724000、2724000、1392000 ms |

executor 只把这个计划作为 bridge 的 `timeoutMs`，仍用原始全局 offset 更新进度。Ragas 的 prompt、strictness 3、三个指标、阈值、数据筛选和输出验证均保持原样。

bridge 现在自己拥有 deadline timer，不再把相同 timer 交给 OwnedProcessRegistry。到期时先固定 `evaluation_timeout`，立即 abort 给在途模型的 signal，由现有 OwnedProcessRegistry 停止拥有的 helper；再等待模型回调、usage/ledger 审计及进程清理完成。迟到模型取消错误使用 `error ??= cause`，不能覆盖更早的 timeout 或协议错误。worker 非零退出也先 abort，再等回调。timer 在启动失败和 finally 中清理。

## RED → GREEN 证据

新增测试：`evaluation-budget.test.ts`（4 项）、`evaluation-deadline.test.ts`（4 项）、`evaluation-budget-recovery.test.ts`（1 项）。

- 编辑实现前，[预算与 deadline RED 日志](logs/red-tests.tap)证明预算模块缺失、2 秒 worker deadline 后 6 秒内审计仍未开始；该初始诊断日志随后停止，未作为完整测试结果。
- 编辑实现前，[executor RED 日志](logs/red-recovery.tap)退出 1，实际 executor 未传预算，观察到值为 0，预期为 2500000。
- 固定测试 fixture 后，对隔离原始快照完整回放相同最终测试：[RED 回放](logs/red-final-tests.tap)退出 1，8 失败 / 1 通过；协议错误也被旧代码迟到的 `model_cancelled` 覆盖。
- 候选实现：[新增测试 GREEN](logs/green-new-tests.tap)退出 0，9 / 9 通过。
- [typecheck](logs/typecheck.log)和[build](logs/build.log)均退出 0。
- [既有相关测试](logs/related-tests.tap)：`evaluation.test.ts` + `evaluation-bytecode.test.ts` 退出 0，17 / 17 通过（201.637 秒），包括安装的真实 Ragas 0.4.3、localhost HTTP 五题 45 请求/usage、取消恢复 46 请求/usage及公开 corpus 五题 45 请求/usage路径。

执行目录均为上述隔离副本的 `packages/core`，RED 完整回放另在 `red-work/packages/core`：

```bash
TMPDIR=/dev/shm node --import tsx --test test/evaluation-budget.test.ts test/evaluation-deadline.test.ts test/evaluation-budget-recovery.test.ts
npm run typecheck
npm run build
TMPDIR=/dev/shm node --import tsx --test test/evaluation.test.ts test/evaluation-bytecode.test.ts
```

取消测试使用实际 `fetch`：deadline 时服务器已发送未完成 JSON body；worker 退出/协议错误时请求已到服务器，响应尚未发出。确认模型 signal 被 abort，bridge 在审计 gate 放行前保持 pending，结束时保留原先错误码，服务器连接实际关闭，且请求没有重放。

恢复测试直接使用隔离 CoreDatabase、JobQueue、EvaluationService 和真实 localhost HTTP；仅 helper 是标准库 Python 受控协议 fixture（每行两次 RPC），不代表 Ragas 算法评分或模型质量通过。首次故障共 7 请求 / 7 usage：5 个回答及 1 个 judge 已完成，1 个 judge 在途结果未知。所有已完成 invocation 留存，未知 invocation 被标记 `unknown`。

关闭并重建 service 后，默认 resume 不发请求并报 `paid_result_unknown`。模型 timeout 从 60000 改到 61000 后，即使显式确认仍报 `checkpoint_mismatch`；恢复原模型配置后显式确认才允许重试。5 个已完成回答和 1 个 judge 复用，不新增它们的 usage；最终共 16 请求 / 16 usage，其中只有原未知调用重新发出。相关 fixture 不把 60 秒未知调用当作可自动重放失败。

## 覆盖率与依赖

[Node 内置覆盖率](logs/coverage-new-tests.tap)仅针对新增 9 项测试，退出 0：

| 文件 | 行 | 分支 | 函数 |
| --- | ---: | ---: | ---: |
| budget.ts | 100.00% | 100.00% | 100.00% |
| executor.ts | 90.65% | 55.00% | 81.25% |
| ragas.ts | 97.40% | 73.24% | 88.46% |

它不是完整 Core 覆盖率；未覆盖 executor 的部分检索、rerank 与比较路径由已有相关测试验证。

实际核对依赖：Node 22.23.2、TypeScript 6.0.3、tsx 4.23.0、`@types/node` 22.19.15、better-sqlite3 13.0.3、sqlite-vec 0.1.9；读取实际 `AbortController`、`NodeJS.Timeout.unref()` / `clearTimeout` 定义及 OwnedProcessRegistry 类型。Linux 对应 Python `/home/liuxuedeng/anaconda3/bin/python` 安装 Ragas 0.4.3；正式 Windows 随包环境只读核对阶段已完成，本轮未操作该环境。

## 恢复与验收边界

预算没有进入 checkpoint 或 model signature，因此既有 stopped run 可以在完全相同的数据源、模型有效配置、指标和 thinking 下恢复；完成请求复用，未知请求仍需原显式确认。该补丁不会让变更模型超时后保持旧 run 的配置一致性，也不会把旧 run 的未知计费结果判为成功。

评分 worker 总预算变长不会解决单次 provider 60 秒模型 timeout。原真实 run 的 19 个调用事实及第 19 个未知结果没有被本轮改写，重新运行仍可能遇到单次模型时限或供应商响应问题。没有为通过评测调整答案、指标、阈值或 thinking。

本轮验证平台是 Linux 隔离副本，不声称 Windows 正式安装生命周期、真实厂商五题评测或 GUI 验收已经通过。原仓库正式集成仍待父代理释放冻结。
