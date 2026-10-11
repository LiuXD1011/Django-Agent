# 最新同步发布采样分析

本分析只读取根代理已保存的两份 CPU profile、命令回执、TAP 与对应源码；未执行新大文件入库、CPU profile、真实模型或 GUI。产品源码没有改动。另用匹配内核现有 native binding 的隔离内存 SQLite 检查小型 SQL 计划及候选语义，不打开生产数据库。

## 哪份文件包含业务

两文件名称都含 PID 2969238，但线程后缀不同，不能按文件名强行称其为“父进程与测试子进程”。

| 文件 | 原始采样与角色 | 加权时间 |
| --- | --- | --- |
| [.0.001](CPU.20261011.185350.2969238.0.001.cpuprofile) | 9930 个配对 sample/timeDelta，包含 document-workflow.test、pipeline、SearchIndex 和数据库业务栈，是实际测试/core 主线程 | sum(timeDeltas) 17681.057ms；profile elapsed 17682.262ms；尾部未归属 1.205ms |
| [.1.002](CPU.20261011.185350.2969238.1.002.cpuprofile) | 14987 个配对样本，无 pipeline 或 document-workflow.test 业务帧；主要 node:internal/modules/esm/worker、hooks、package_json_reader，是 ESM/tsx loader 辅助线程 | sum(timeDeltas) 17447.599ms；profile elapsed 17448.091ms；idle self 15835.538ms |

不能把 loader 的 17 秒计入发布，也不能把它作为纯分块 Worker 的 CPU 数据。这两份 profile 没有独立纯分块计算的函数采样。主线程 idle self 5774.882ms 表示等待/空闲，不是 5.8 秒同步发布。

[原始业务 TAP](large-local.tap)的 process_knowledge 为 14220ms、publish_local 为 6609ms、实际子测试为 15627.976177ms。[命令回执](command.json)为 17893.41ms，包含启动、模块加载、fixture 和测试工具时间。上述时间的范围不同，不能互相替代。

## 计算方法和对应源码

self 为每个样本的 timeDelta 归到 sampled node；inclusive 将该 timeDelta 归到祖先路径中每个不同的 callFrame，同一递归函数不重复累计。按 functionName/url/生成行/生成列聚合，不使用 hitCount×固定采样间隔。两个 profile 均无负 delta；主线程最大单个 delta 189175µs，因此这是加权采样归属，不是精确的每 SQL 计时。

原始 profile 的 TS 行列来自 tsx 压缩后的生成代码。例如 pipeline.ts 的 1:9207 是含 insertMany 与 indexKeywords 的发布事务回调，1:8960 为其 publish_local 外层 work；当前原始源码中仅这一回调同时包含这两次调用。以下链接定位到已由原始命令 SHA 绑定的原始 TS 文件，JSON 保留生成位置和完整调用栈，不假称已有源码 sourcemap 还原。

| 范围/热点 | 加权采样时间 | 原始源码与解释 |
| --- | --- | --- |
| publish_local 外层 work inclusive | 6513.011ms | [pipeline.ts](../../../packages/core/src/documents/pipeline.ts) 第 184 行；与 6609ms stage 同量级，但没有单调 stage marker，不能精确切样本边界 |
| 发布 pub 回调 body inclusive | 5927.017ms | pipeline.ts 第 191 行，同步执行所有块和索引写入 |
| 外层 work 内 sqliteTransaction self | 572.509ms | [transaction.js](../../../packages/core/node_modules/better-sqlite3/lib/methods/transaction.js) 第 52 行；before/after.run 包含 BEGIN/COMMIT 或 SAVEPOINT/RELEASE，采样不能进一步拆分或全部命名为 commit |
| indexKeywords inclusive | 4407.383ms | [search-index.ts](../../../packages/core/src/retrieval/search-index.ts) 第 74 行，已存在 64-ID 批量，不是待实现的逐块 FTS 写入 |
| 直接 FTS 批次 callback → Database.run self | 3319.844ms | search-index.ts 第 97/98 行，直接 run 只有批量 DELETE/INSERT；[database.ts](../../../packages/core/src/storage/database.ts) 第 129 行停留在 native Statement.run |
| #rowid inclusive | 693.251ms | search-index.ts 第 48 行；其中 run self 425.351ms、get self 110.173ms。合并查询保留序号/登记写入，不消除它们 |
| insertMany inclusive | 974.266ms | database.ts 第 176 行；批量 flush→run self 633.140ms，字段校验/defaults/编码仍必须执行 |
| pub body 内 JSON decode self | 18.262ms | [json.ts](../../../packages/core/src/storage/json.ts) 的 parseStoredJson；不能把整个测试的 658.367ms JSON decode 移到这里 |

父子 inclusive 互相包含，不能把表中各行全部相加。主线程全部 run self 4714.672ms，发布 body 内 run self 4463.208ms。发布 body 内 encoded self 192.826ms、normalized self 101.396ms；JSON 与数据转换有成本，但当前主要热点是 native 索引/业务写入及事务边界。

纯分块 Worker 只移走分块算法；pipeline 第 191 行的 pub 仍在同一 core 线程同步执行，内部 64-ID 循环没有异步让出。因此“已使用 Worker”和“已批量写入”仍可以同时出现 6.6 秒 core IPC/HTTP/取消处理阻塞。这份数据不能证明 GUI/P95，也不能把前次 6584ms 与本次 6609ms 的单次差异称为速度回退。

## FTS 配置、计划与最小验证方向

当前 [migrations.ts](../../../packages/core/src/storage/migrations.ts) 第 95 行是普通 FTS5：`CREATE VIRTUAL TABLE chunks_fts USING fts5(content, tokenize='trigram')`。实际匹配内核 binary 的 better-sqlite3 13.0.3 / SQLite 3.53.4 检查见 [SQL 计划](profile-analysis-sql-plan.json)。

- 64-ID DELETE 的 QP 写 `SCAN chunks_fts VIRTUAL TABLE INDEX 0:=`，但 VM 的 VFilter 参数为 `=`，是 rowid IN 的约束访问，不能仅看到 SCAN 就断言全表扫描。
- 64-row INSERT 为 `SCAN 64-ROW VALUES CLAUSE`，随后循环执行 VUpdate。一个批量 SQL 仍需处理每一行的 FTS 内容和索引；采样只落在 native run，不能把 native 内部耗时进一步断言为 trigram tokenization、磁盘 I/O 或索引合并。
- 当前 DELETE 与 INSERT 共用同一父 callback 和同一 Database.run callFrame，生成位置又在同一行；本 profile 无法拆出两条 SQL 各自耗时。需要分别记录这两类 Statement.run 的小 fixture 耗时与行数，才能决定下一步。

一个最小待验证方向是仅对有效块比较现有 DELETE＋INSERT 与 `INSERT OR REPLACE`，先分开计时，再以真实 FTS 回归验证。隔离小证据已证明当前配置支持 OR REPLACE，最大 64-bit rowid 保真、旧词移除、新词可检索、无关行保留和事务回滚均成立；这不是产品修复或速度提升证据。inactive 块仍必须显式 DELETE，原 #rowid 全局冲突、旧序号/向量清理、scope 校验和同一 owner 外层事务不能省略。未改变 tokenizer、召回内容、排序语义或开启第二个生产写连接。

首次 SQL 夹具误用包默认 prebuild，在 GLIBC_2.33 要求处失败；实际内核已有显式 local nativeBinding，因此这是分析夹具问题。保留[首次错误摘录](profile-analysis-sql-plan-first-fixture-error.log)、[初版脚本](profile-analysis-sql-plan-first-fixture-script.json)，改为匹配真实内核绑定后[检查通过](profile-analysis-sql-plan-green.log)。没有更改产品依赖或 native 文件。

完整加权 self/inclusive、限定发布子树、来源 SHA 与脚本归档/清理见 [分析 JSON](profile-analysis.json)和[清理凭证](profile-analysis-cleanup.json)。
