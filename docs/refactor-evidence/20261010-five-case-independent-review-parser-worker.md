# 五题真实厂商评测脚本独立只读审查

日期：2026-10-10。审查者：parser_worker。

结论：本次源码合同核对未发现需要阻止这份脚本进入人工批准付费阶段的实质缺陷。没有执行脚本的 prep、paid 或 GUI 分支，没有读取认证材料、用户私有副本、模型密钥，也没有修改产品、脚本或 stage。此结论是静态合同审查，不是五题厂商评分成功或页面验收证明。

审查对象：`/tmp/marlin-real-vendor-five-case-20261010.cjs`，334 行，SHA-256：`8adcc7396418969dfd57e521125e437dc629e3270916e80b286eb9e49d0d3d0b`。审批 gold 文件是已有脱敏 [零付费预检 JSON](20261010-real-vendor-evaluation-preflight.json)，SHA-256：`7e6c5cdc37e8fbc0a2f3de8711265d480c9dd0f35b598e3a4e3df7e5ec527499`。

## 核对结果

| 项目 | 脚本及实际合同 | 判断 |
| --- | --- | --- |
| 默认 prep | 第 121–130、242–279 行只允许正常认证、资料/模型读取、固定手工数据集创建/审核/发布、估算；不允许 generate、resume、retry 或 run POST。第 242 行起拒绝 fetch；第 276 行核对用量不增及无 fetch。实际 `estimate()` 只调用 preflight，不调用模型或 Ragas。 | 默认不会按当前合同发模型请求。prep 会正常写私有副本的数据集及可能刷新设备会话，并非只读模式。 |
| 身份与权限 | 第 247–261 行先拒绝有 queued/running 任务的副本，再构造正常 Core/IPC；`auth/me` 失败仅使用正常 refresh 后重试 me，真实 user/tenant/device 必须与已批准预检一致。没有构造 AuthContext、注入 token 或借用另一账户。后续 API 仍经过应用 authorize 和评测权限检查。 | 认证恢复与租户授权路径合法；私有 corpus/usage SQL 是成功授权后的固定只读核验，不对渲染器提供凭据。 |
| 五题及来源 | 第 145–177 行核对五份固定文件哈希、完成/启用状态、全部 chunks 和 PNG 真实 OCR；五题只从当前启用 text chunk 的 code point 区间生成 quote，附 file_hash/source_generation，再校验 API 返回的全部 gold 字段及 validation_errors。 | 五个不同问题均有标准答案和事实来源；采购 948+903=1851（不含运费），第五题由现行手册与交付计划共同支持。未把旧失效文档或 OCR 结果充作这五题的 gold。当前运行时来源仍由脚本再次核验，本审查没有重读私有数据库。 |
| 审核、发布与版本 | 第 262–279 行经真实 create→review→publish API，要求 5 pending→5 approved、published/version 1、精确 dataset_hash；paid 模式不重建数据集，要求 ID、版本、gold/hash、完整 corpus、模型公共配置、估算及正式 build identity 与人工确认的 prep 相等。 | 与不可变发布和运行 fingerprint 合同一致；不是未经审核候选直接运行。 |
| 单次付费与未知结果 | 第 280–287 行在恢复 fetch、run POST 前，以固定 dataset ID 的 `wx` 文件创建并 fsync attempt ledger，写入请求 UUID。只提交一次，不删除 marker，不提供自动重试/恢复。即使 POST 返回前失联，marker 仍保留未知状态。 | 同一已批准数据集不能通过换 report 文件盲目重放。Core 每次真实调用另有持久 pending/completed/unknown invocation ledger；未知付费结果需显式人工确认才能 resume，脚本不开放该路径。 |
| 取消与退出 | 第 288–299 行最多等待 15 分钟，取消后等待 terminal 有界；失败/取消/中断不被视作完成。第 320–334 行先 await app.close，再只读重开副本汇总已发请求最终用量，不在最后一次状态轮询截断审计。 | 保留实际已发请求的账实，不自动继续失败任务。成功判定需同时要求进程 exit 0、无 shutdown_failed/usage_audit_unavailable；单独读取 state 字符串不够。 |
| 报告与缺指标 | 第 214–226、300–311 行要求 completed/verified/current、5 个有效样本及三个真实 Ragas 分数；context_recall、answer_correctness 必须为 null 且列入 unavailable_metrics。`report_hash` 核对 canonical metrics SHA，下载字节另核 IPC binary SHA/长度，再保存、重新打开及检查 history。 | 与当前报告和二进制 DTO 一致；不将缺指标写成 0，不混淆指标哈希与整份下载哈希。 |
| 用量与阶段 | 第 197–213 行仅查询实际 run 的四个 evaluation scenario，检查 UUID、每条 request_count=1、非负有限整数，并核对指标 calls 与审计记录数。embedding 以持久 stage 事件和审计 created_at 分段；时间相等归入 ambiguous。Core 两者均使用 ISO UTC 时间。 | 明确是审计时间分段，不冒充逐题归因或 wall time；duration 求和与端到端耗时分开。 |

## 已核对的产品合同

- [评测路由](../../packages/core/src/adapters/evaluation-routes.ts)：真实 dataset/review/publish、estimate/run/status/cancel/history/report 路由及 jobs 调度。
- [数据集](../../packages/core/src/evaluation/datasets.ts)、[评测服务](../../packages/core/src/evaluation/index.ts)、[fingerprint](../../packages/core/src/evaluation/fingerprint.ts)、[canonical digest](../../packages/core/src/evaluation/common.ts)：证据校验、发布、最少五题、模型/index 配置与源变化围栏。
- [执行器](../../packages/core/src/evaluation/executor.ts)、[持久存储](../../packages/core/src/evaluation/store.ts)、[Ragas bridge](../../packages/core/src/evaluation/ragas.ts)：逐调用 ledger/审计、未知结果手工恢复、三指标有限值、报告内容及 worker 生命周期。
- [CoreApplication](../../packages/core/src/application.ts)、[CoreIpcAdapter](../../packages/core/src/adapters/ipc.ts)、[认证服务](../../packages/core/src/auth/index.ts)、[JobQueue](../../packages/core/src/jobs/queue.ts)：真实 IPC 身份恢复、授权、二进制响应、关闭等待与过期租约恢复。
- [用量审计](../../packages/core/src/settings/usage-audit.ts)、[模型配置](../../packages/core/src/settings/model-configuration.ts)、[SQLite 存储](../../packages/core/src/storage/database.ts)：公共模型投影、有限计数和审计时间格式。

## 验收边界及检查记录

仅完成全文阅读、合同交叉核对与 SHA 复算。未运行该 utility、模型、Python 评分、GUI 或新全套测试。已有零付费预检可证明认证恢复和五份资料/模型配置前置条件；它没有创建/发布评测数据集，也没有得到 Ragas 分数。

脚本经正常 Core/IPC 自动化审核和发布人工已确认的五个 gold，不证明 GUI 候选生成、逐题编辑/审核、发布或页面下载动作。最终报告保留 `gui_verified:false`、`opened_in_gui:false`；这些 GUI 步骤仍需另行真实验收。完成真实 run 还需人工批准本次 prep、确认当前正式 stage/私有副本不变及执行结果 exit 0。若结果未知，保留 ledger 和 request_id，由人工调查，不再次运行付费分支。

未确认的残余风险：该一次性工具信任已冻结正式构建报告及 ACL 保护的本地人工 prep/attempt 文件，不提供抗同一用户恶意改写机制；本审查不将这个明确受控 QA 边界视作产品缺陷。
