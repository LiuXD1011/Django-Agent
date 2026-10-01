# Codex 独立验收与批准记录

## 2026-09-30 当前波次独立验收

共同基线：prep-desktop-commercial-release / afa7e0138f9fbad80e80aa4ead6f1d80af0145da。协调Run run_c0d51a93432f。用户已授权总体目标内自主技术决策；不提交、推送、合并、发布，不关闭用户手动终端。

- MARLIN-P01 / round 1：补充 Windows 原生验收，隔离 Windows Python 3.13.3 venv，Django 5.2.15 / DRF 3.14.0 / filelock 3.13.1 / sqlite-vec 0.1.9。URL 导入成功、FTS5 与 sqlite-vec v0.1.9 真实加载。accounts portability+processes 共17项，16通过，1因系统/账号不支持符号链接跳过，退出码0。日志 /tmp/marlin-native-p01-review.log；不代表全依赖/安装包/全产品 Windows 已验收。
- MARLIN-P02A / round 1：changes_requested。独立108项通过，另定向证明拿锁后deadline耗尽仍调用Docker两次；进程测试缺可靠屏障/exitcode检查；报告有超证据归因。round2 Task task_849586d20efa：原ctx_e6d244bf4bc5终端明确Killed且PID消失，已abandon保留shell；通过retry-of复用同Task，当前ctx_9d969a1cf87f由第二ZCode执行。
- MARLIN-RECOVERY-R1 / round 1 (task_8590df29493c / ctx_16e0a24ebf0f)：changes_requested。独立93项中92通过/1失败；3个额外确定性DB探针全部失败，发现legacy lease=NULL仅updated_at续租会误reset/failed，失主fn仍执行3次。失败证据 /tmp/marlin-codex-recovery-probes.log；93项日志 /tmp/marlin-codex-recovery-r1-review.log。已新建round2 Task task_36bf3dea2cfa/ctx_e51dfc4c29db，不重试completed旧Task。
- OpenRAG邻近422：在HEAD源码临时副本独立复现embedding_model_required，确认原成功测试缺必要模型fixture，不是P02A文件锁造成。基线日志 /tmp/marlin-codex-head-openrag-review.log；只准补测试fixture，不能弱化真实产品校验。
- MARLIN-CLEANUP / round 1 (task_b0a290393112/ctx_6a6066f47fa3)：删除6个已审计文件的工作树副本，未改历史；含曾硬编码令牌脚本，验收仅名称/统计，不输出删除正文。独立Node22测试30/30、build、README链接均exit0。但Node20.19命令带字面glob失败exit1，报告声称20.19实测不准确；改用src目录自动发现的独立探针30/30 exit0。已建立round2 Task task_9765eb989516，仅修测试入口与勘误报告。

后续已批准方向：Windows优先，先独立用户数据根D1，再最小本地桌面launcher D2（明确127.0.0.1、非DEBUG静态资源、迁移、持久secret仅launcher管理、evaluation worker与所创建子进程生命周期），前端D3显式首次初始化并让用户保存临时密码，恢复R2周期性处理崩溃租约。暂不引入Electron/Tauri、Redis/Celery/多机HA；不声称完成签名安装包或商业授权审查。

旧ORCA-DESKTOP-DESIGN.md仅为未验收设计，以下建议已被否决：全局settings自动生成生产secret、默认开启auto_setup、只开documents worker却留下evaluation pending、直接用Django开发static视图当生产静态服务器、Node18要求和npm包称Windows wheel。以后Task规格优先；D1涉及锁路径/任务路径，须等相应修改验收后独占编辑。

当前graphify更新权集中在Codex验收阶段，避免多个worker并发写图。协调者测试仅写OS临时目录/忽略构建产物与本协调记录；业务文件由ZCode改。剩余待验收，不以worker_done succeeded代替代码通过。

## 14:49 UTC 调度修正 / 同run，P02A round2

第二attempt ctx_9d969a1cf87f也出现明确Killed并退回shell（对应父进程4140765消失），已worker-abandon保留终端，无processAction。内核日志明确记录两次zcode-cli OOM kill：PID3895444匿名RSS约10.9GiB、PID4154053约8.4GiB；不得将之当作代码测试失败。P02A待第三执行者完成R1后以task_849586d20efa --retry-of ctx_9d969a1cf87f恢复，勿新建替代Task绕开次数限制。当前唯一执行者ctx_e51dfc4c29db仍运行；后续改为串行派发，减少并行构建，不能自行关闭/重启用户终端。

Windows前端临时副本已npm ci退出0，原生Node22.15在src目录node --test 30/30退出0，Vite原生build退出0（首次采集因Python GBK stdout打印checkmark失败，构建日志已存在但退出码未保存；修正采集后重跑保存exit0，不把采集失败称为构建失败）。副本C:/Users/lxd/AppData/Local/Temp/marlin-native-review-20260930/frontend-review；证据同父目录frontend-unit.log/frontend-build.log/frontend-build-exit.json。

npm审计只读结果：2 high（nanoid、postcss）、1 low（esbuild）；完整/tmp/marlin-codex-npm-audit.json。项目构建依赖已知通告待小范围更新验证，不能以开发构建链告警直接声称桌面运行时可被利用。esbuild官方Windows开发服务器通告https://github.com/evanw/esbuild/security/advisories/GHSA-g7r4-m6w7-qqqr；postcss https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp。当前未升级，以免与前端验收范围混杂。

后续任务编号（只按依赖与验收通过后派发，未执行不计完成）：清理round2 task_9765eb989516；首次初始化前端D3 task_7312466bd6b5；数据目录D1 task_3eec37f60d3e（依赖P02A与R1r2）；桌面启动D2 task_3eaaedeb24fd（依赖D1）。各Task已有可修改文件和可观察验收标准，用户无需再次选择技术方案。

## MARLIN-RECOVERY-R1 / round2：passed（2026-09-30 14:56 UTC）

Task task_36bf3dea2cfa / Dispatch ctx_e51dfc4c29db；实际diff已检查，新增/删除：本轮无新增业务文件、无删除；tasks.py/test_task_recovery.py/test_open_rag_runs.py及ZCode报告在范围内。已修复updated_at-only续租误重置/误判失败、旧worker正常返回后重复执行、测试缺模型fixture；没有降低产品校验。Codex独立Linux101tests/5.288s/exit0；Windows原生98tests/5.414s/exit0（额外3个独立审查探针只在Linux执行，其等价核心用例已进入repo），日志/tmp/marlin-codex-recovery-r2-review.log、/tmp/marlin-native-recovery-r2-review.log。git diff --check退出0；P01四文件sha256仍匹配。隔离临时库/BASE_DIR/MEDIA_ROOT，无真实模型请求。

本验收不涵盖尚未修复的进度/检查点属主约束、常驻恢复扫描器、多机器HA；不以101tests绿声称这些缺口已闭合。worker_done已核对settled，用户终端retained，下一负责人Codex恢复P02A已失败Task，再串行推进后续计划。

后续可靠性任务已落入同Run：R2A task_0940d993e9ab（D1后，进度/检查点属主保护、状态DB权威读取）；R2B task_a225951b0d82（R2A后，常驻扫描与worker繁忙期间/queue过滤/退出生命周期）。只按明确范围分批派发，未运行不算完成。

商业化盘点证据：原始eval_datasets/open_rag_benchmark.manifest.json声明CC-BY-NC-4.0，180子集manifest未单列license；仍保留来源与文件，无替换授权声明。Creative Commons官方说明非商业限制：https://creativecommons.org/licenses/by-nc/4.0/ 。requirements声明PyMuPDF>=1.24.0；官方采用AGPL或商业许可：https://pymupdf.io/licensing ，https://pymupdf.readthedocs.io/en/latest/faq/index.html 。根MIT不替代第三方许可条件；最终发布形态/第三方分发清单未审定，本轮不购买许可、不对外发布。

P02A round2当前恢复attempt：ctx_0ecff319bf3a，Task task_849586d20efa，第三手动终端term_db08c892-566d-4233-8314-3ad01577385f；明确--retry-of ctx_9d969a1cf87f。保持单执行者。补充审批msg_e8f41424ea14：同一deadline也覆盖HTTP健康探针，不使用max(.1,剩余)延长预算；只在原scripts/local_services.py与测试范围内。R1r2终端settlement已retained，delivery已处理ack；当前workspace无db.sqlite3/.cache/media/.env。

## 最终资源阻塞检查点（2026-09-30T15:11:19.556276+00:00）

Task task_849586d20efa / round P02A-r2 / attempt ctx_0ecff319bf3a：第三ZCode亦明确Killed回shell，内核OOM记录PID66498匿名RSS20283828kB。已worker-abandon，processAction=none，未自动创建/重启/关闭终端。三次P02A r2尝试均未改业务文件：local_services SHA256=809705b7bcef08f9146b04b5170832f227d815837165413055b59bad5623d28d，locktest SHA256=2739184c095a7e6c00122be8a114a143392ce3a87ef1c0ae1ff9eb93e677322a，仍为r1。

本波已停止全部业务写入，graphify update .退出0（5260节点、13066边、283社区）；diff check退出0，index无暂存，HEAD不变。没有剩余可派发ZCode；D3和清理r2记录blocked_no_executor，其余依赖任务保持pending，不冒充完成。恢复方法与终端状态见ORCA-HANDOFF.md，完整批准规格见ORCA-PENDING-TASKS.md。终端reclaimable查询为空。


## 2026-10-01T00:51:41.309886+00:00 / task_849586d20efa / P02A-r2 attempt-4

恢复未进入业务执行：自动 worker-start 创建 ctx_0abee2006076，agent_readiness timeout；界面存在但30/60秒Ready等待均失败；复用同终端返回 agent_unconfigured。按运行时 recovery 执行 worker-release 已回收本次自动窗口，保留旧手动终端。业务改动与验收结论未变化，产品测试本次 not_run；最新重试目标改为 ctx_0abee2006076。详见 ORCA-HANDOFF.md 最新恢复记录。


## 2026-10-01 / task_9765eb989516 / cleanup round2 / 独立验收

当前 frontend/package.json 的 test:unit 已变为 cd src && node --test；报告显式勘误原Node20“实测”错误，未删除历史。Codex独立运行最终npm脚本：Linux Node22 30/30 exit0（/tmp/marlin-codex-cleanup-r2-node22.log），Node20.19 30/30 exit0（/tmp/marlin-codex-cleanup-r2-node20.log）；Windows原生Node22临时副本仅同步当前package.json后实际 npm run test:unit 30/30 exit0（/tmp/marlin-codex-cleanup-r2-windows.log）。此次未重跑build（纯测试入口变化）。代码与报告检查通过，等待对应正式worker_done核对生命周期后转入D3。


## 2026-10-01 / task_849586d20efa / P02A-r2 / passed

ctx_afb1b54dfa95正式worker_done核对通过。Codex检查三个业务锁实现、子进程创建/回收、退出码/stderr与屏障：本轮范围内修复完成。独立两deadline探针由red（Docker2/2）变green（0/1）；Linux合并111tests exit0；Windows原生20tests=19pass+1权限位skip exit0。最后两处新增真实失败acquire探针后，Linux和Windows各定向2tests exit0（/tmp/marlin-codex-p02a-r2-barriers{,-windows}.log）。真实Docker启动/联网health未运行。报告中“Windows未准备依赖”仅适用于worker未使用环境，Codex原生临时环境已准备并完成上述验证；worker_done的“20+1skip”以实际19pass+1skip为准。没有将上述结果外推为整个Windows交付完成。终端retain，旧Task正式结束；后续D1可执行。


## 2026-10-01 / task_7312466bd6b5 / D3 / 独立验收证据

Codex检查Login.vue/auth.ts/router/index.ts与两新增行为测试：取消静默初始化；显式初始化展示临时密码、确认才导航；错误finally复位、防重复调用；store仅持久已知认证字段。Linux npm run test:unit 45/45 exit0，build exit0；Windows临时副本同步5个D3文件后实际npm run test:unit 45/45 exit0。日志 /tmp/marlin-codex-d3-{unit,build,windows-unit}.log。

真实Chromium+临时SQLite验收 /tmp/marlin-codex-d3-browser.py：busy/disabled/already_completed错误提示与可重试；无token受保护路由回login且0次建号；一次POST成功后留login、显示真实临时凭据、localStorage/sessionStorage不含临时密码；确认后进入知识库且无pageerror；错误密码后可用真实生成凭据正常登录；390px无横向溢出。退出0，日志/tmp/marlin-codex-d3-browser.log，不打印凭据。首轮脚本因Codex自己的Playwright route回调参数错误exit1，修正装置后通过，非业务失败。Orca goto已打开隔离登录页，但snapshot接口runtime_unavailable，实际自动测试由Python Playwright完成，不声称Orca snapshot通过。等待正式worker_done核对后结案。


D3结案：2026-10-01正式收到msg_9f255cc36d64 / ctx_a6038010d6cb，Task/Dispatch/6个修改文件与报告核对一致，独立证据见上，验收passed。终端retain，等待D1完成后再安排后续独立批次。


D3补充广泛前端回归：Codex实际运行 npm --prefix frontend run test:e2e -- --output=/tmp/marlin-codex-d3-e2e，38/38 passed，1.3m，exit0；桌面与mobile-390项目，覆盖已有聊天/知识库/评测/轨迹UI，接口模拟，无真实模型调用。日志 /tmp/marlin-codex-d3-e2e.log。独立首次初始化端到端另见真实临时后端测试，两类证据不混淆。


## D1 independent verification — 2026-10-01 01:54 UTC
Task task_3eec37f60d3e / dispatch ctx_522070980665. Worker still preparing formal delivery; review evidence ready, not yet dispatch settlement.
- Linux runtime_paths: 22/22, exit 0, 0.844s; /tmp/marlin-codex-d1-linux.log.
- Windows native Python runtime_paths: 22/22, exit 0, 2.582s; /tmp/marlin-codex-d1-windows.log.
- Linux locks/recovery/open-rag-runs/eval-reports/eval-dataset-sources: 98/98, exit 0, 7.920s; /tmp/marlin-codex-d1-regression.log.
- git diff --check exit 0. Reviewed helper, settings source/runtime split, five cache consumers; no migration/deletion of user data.
- Finished frontend verification services: own PTYs 53041 and 1826 stopped with Ctrl+C, both exit 0; isolated temporary backend database cleaned by context manager. User browser tab and manual terminals retained.

D1 final: **passed**. worker_done msg_186488e9c77a matches task/dispatch and all ten delivery files; report file SHA256 values match the reviewed final source. Linux22+98 and Windows22 independent evidence above. Worker report Windows not_run refers to worker only; Codex native test was run and passed. Terminal retained.

## R2A independent pre-fix probes — 2026-10-01 02:02 UTC
Temporary test module /tmp/marlin_codex_r2_probes.py, isolated Django TransactionTestCase runner. Three tests fail as expected before R2A, exit 1: DB completed vs stale cache returns running; DB deletion vs stale cache returns running; ownership transfer after first database-is-locked call still retries callable (2 calls, expected1). Log /tmp/marlin-codex-r2-before.log. Initial probe draft used TestCase with connection-closing worker and a deleted instance id; those harness issues were corrected before this confirmed three-failure run. No business files modified. Re-run after R2A to independently verify behavior.

## D2 in-progress draft review (not accepted) — 2026-10-01 02:38 UTC
Task task_3eaaedeb24fd / ctx_01684d22edc2 still active. Must resolve before acceptance:
- msg_d7f0711a4936: take instance lock before secret generation; create secret temp with0600 from creation; resolve relative data root; detect preexisting DB before Django/executor connects; migration signature mismatch; finally reap migration child on KeyboardInterrupt; child exit should fail health immediately; no artificial extension of remaining deadline; one stop failure must not skip remaining children.
- msg_1e40158b1fc8: migration child must set management argv before django.setup to suppress startup recovery; correct default HTTP port80 origin normalization.
- msg_05ebbfc4dec5: bounded readiness wait, not blocking readline; garbage DB test writes selected data/db.sqlite3 and asserts real failure/no children. Login-field claim was incorrect and explicitly retracted in msg_208ae1313d38: both email/username supported, admin valid.
- msg_3bb2a84c8759: Windows failing tests also close stdin and bounded-wait graceful launcher cleanup before terminate; do not leak web/worker on assertion failure.
- msg_ea74091f36cc: test_double_instance uses temporary FileLock(...).acquire() then drops lock reference, releases lock and accidentally starts real web/worker indefinitely. Use retained/context-managed lock and explicit synchronization. Actual pipeline `timeout300 python... | tail -5; echo EXIT=$?` reports tail exit code, not test exit; require true command status/log. Observed owned test PIDs2459523(parent),2459592(web),2459593(worker); bounded timeout expected to reap them, verify no orphan.
Queued non-interrupting terminal reminder accepted to check/ack actual Dispatch inbox after current test. No business code edited by Codex.

## D2 preliminary independent integration — 2026-10-01 02:49 UTC
Still NOT accepted: outstanding draft review items remain, worker still editing.
- /tmp/marlin-codex-d2-lock-probe.py exit0: held real FileLock rejects second instance with no secret-file side effect (code had already fixed ordering when probe ran). Log /tmp/marlin-codex-d2-lock-review.log.
- Real launcher HTTP smoke Linux exit0 and Windows native exit0: isolated data path with spaces; real migrations, Waitress, evaluation worker; health/login/assets MIME/deep link; GET auto-setup rejected; null/external/mismatched Origin rejected; same-origin first setup + no-store; repeat setup401/setup_already_completed; duplicate instance rejected; graceful exit0 and listener closed. Logs /tmp/marlin-codex-d2-smoke-linux.log and /tmp/marlin-codex-d2-smoke-windows.log. Harness first draft expected wrong repeated-setup status and was corrected against existing accounts contract, not a product defect.
- Linux real Chromium using production Waitress+WhiteNoise: protected deep-link redirects login, generated temporary credentials login, knowledge-base empty state fully loaded, no JS page errors; exit0, /tmp/marlin-codex-d2-browser.log. Screenshots /tmp/marlin-desktop-login.png and /tmp/marlin-desktop-workbench.png; latter visually inspected after waiting for loaded empty state and disabling screenshot transitions. All temporary services stopped by owned helper, no real user DB or model requests.
- Earlier stalled worker test PIDs2459523/2459592/2459593 all confirmed absent after bounded timeout.

## R2A 首轮验收：changes_requested (2026-10-01)
Task task_0940d993e9ab / Dispatch ctx_58790f1fbfa7；worker_done msg_0fdbf3e1483d核实，手动终端retained，delivery_1a302d84dd7f已ack。独立运行5 probes+19 ownership：24 tests/7.136s，exit0，/tmp/marlin-codex-r2-final.log。仍需原始claim身份绑定、cleanup stat/unlink竞态保护、DB runtime附加字段权威，新Task定向返工。
SEC1：npm audit实际exit1，high3/low1；task_a8da76839ae3待D2验收，详情见pending specs及/tmp/marlin-codex-npm-audit.json。

## R2A round2 独立回归检查点（待正式完成报告）
Task task_4d324a6ff347 / ctx_a0466644ac33。Linux 7独立probes + ownership/recovery/evaluation/ragas/open-rag共148项，12.916s，exit0，/tmp/marlin-codex-r2-round2-linux.log。Windows原生ownership/recovery共87项，12.810s，exit0，/tmp/marlin-codex-r2-round2-windows.log。测试源码hash快照/tmp/marlin-r2-round2-tested-sha.json，最终接受前核对一致性。代码初查ContextVar原始身份与finally reset、cleanup guarded DB写锁+重新stat、task_status DB result展平符合要求。
Worker扩展225项只有D1 test_runtime_paths SimpleTestCase无DB终态fixture失败。msg_9ff9f3211b3b批准仅该文件真实隔离DB测试适配，保留全部路径/删除/保留断言，禁止以此放宽生产清理规则；待Linux/Windows补验D1模块。当前尚未passed/尚未放行R2B。

## R2A round2 验收：passed
Task task_4d324a6ff347 / ctx_a0466644ac33。正式worker_done msg_b3f065fccccb与四文件metadata/report一致，核心文件hash仍与独立测试一致，diff --check通过。Linux核心148/12.916s + D1补验22/0.749s；Windows核心87/12.810s + D1补验22/2.612s均实际exit0。审查身份上下文、DB状态权威、checkpoint发布/清理互斥与新用例，三项返工关闭。未知/无记录checkpoint保守保留、PG/多机未测，外部副作用不宣称exactly-once。手动终端retained，放行R2B。

D2恢复草稿检查点：5项独立失败探针修复后5/5 exit0 (0.011s)，/tmp/marlin-codex-d2-probes-current.log；尚未最终passed。R2B基线：/tmp/marlin_codex_r2b_probes.py 真实DB --once过期evaluation仍running，1fail/0.043s/exit1，/tmp/marlin-codex-r2b-before.log。

## D2 retry验收：changes_requested
Task task_3eaaedeb24fd / ctx_d84c89eb85bf；worker_done msg_f17e967176bf已核实，retained，delivery_4dd9868c632c已ack。Linux29/23.051s exit0；Windows原生29/34.684s 2fail2error exit1（/tmp/marlin-codex-d2-final-linux.log、-windows.log）。5probe原项绿，但新增loopback不同主机同端口拒绝probe失败，/tmp/marlin-codex-d2-origin-review.log。
返工新Task task_7c898801f949（规格/tmp/marlin-d2-r2-spec.txt）：恢复已批准npm清理（worker误以HEAD为基线重加根pnpm/Playwright）；strict同源补host相等；测试显式关闭5处sqlite连接、跨平台路径断言；早退端口拒绝改有限条件等待。Windows诊断/tmp/marlin-codex-d2-port-probe.log：立即未拒绝、100ms后拒绝；CIM无残留测试服务，暂不改生产process-tree管理。
SEC1 task_a8da76839ae3显式blocked至本返工验收；不能仅凭原D2 Task completed派发。

## 配额阻塞检查点（2026-10-01T04:08:32.614051+00:00）
两worker明确1308账号上限/Turn execution failed，重置2026-10-01 13:57:23北京时间。已abandon ctx_31326d0ea19c/ctx_734a5b249ea8保留窗口文件，Task blocked；reclaimable为空。当前D2六probe通过exit0但测试sqlite连接尚有4处未修；R2B四probe1pass3fail exit1，功能未完成。7关键Python AST通过、git diff --check通过，graphify update . exit0（5718 nodes/13841 edges），不替代验收。无提交推送发布、无自动后台监督。


## 2026-10-01T04:19:21.658247+00:00 D2 round2 passed
Task task_7c898801f949 / Dispatch ctx_bff176173eda; worker_done msg_28aacb6fc554 received, retained manual terminal and acked. Reviewed actual package.json cleanup preservation, same-origin hostname strictness and test five SQLite close sites, Path assertions, bounded eventual port refusal. Worker Linux30 exit0 (/tmp/marlin-d2-final-r2.log). Codex independent6 probes/0.011s exit0 (/tmp/marlin-codex-d2-r2-probes.log), Windows native full30/36.196s exit0 (/tmp/marlin-codex-d2-r2-windows.log). Previous Windows 2fails+2errors resolved, no skipped desktop cases. Production launcher unchanged in this repair. Source desktop runtime accepted; not installer/signature/full requirements acceptance. Report small historical wording correction sent as msg_15bb70d3aa99 raced completion; carry into next scoped task, no reopening completed Dispatch. SEC1 can now proceed. R2B still modifying recovery independently.


## 2026-10-01T04:37:49.095549+00:00 SEC1 round1 passed
Task task_a8da76839ae3 / ctx_35705b9eeaf5; worker_done msg_bbab58dccd1c validated, manual terminal retained and delivery acked. Actual diff confines dependency versions to axios1.20.0/esbuild0.28.2(+platform packages)/nanoid3.3.19/postcss8.5.28. Vite7.3.5 retained; esbuild override removes vulnerable nested0.27.7. Codex audit exit0 all severities0 (/tmp/marlin-codex-sec1-audit.json); Windows fresh npm ci exit0 + unit45/45 no skips exit0 (/tmp/marlin-codex-sec1-windows.log), final package/lock sha256 matches tested snapshot; independent Node20.19 unit45/45 exit0 (/tmp/marlin-codex-sec1-node20.log). Worker Linuxci/unit45/build/E2E38 exit0 evidence read (/tmp/marlin-sec1-build.log, -e2e.log). D2 report two historical wordings corrected under currentTask authorization. No further code edits required. Current batch7/8 accepted; R2B remains active.


## 2026-10-01T04:40:57.763510+00:00 R2B passed and final integration
Task task_a225951b0d82 / ctx_7202552dc69a, worker_done msg_4ac13c5b9b67 validated, manual terminal retained and delivery acked. Reviewed queue filters in all recovery branches, unchanged snapshot CAS, process singleton stopping/queue guards, --once nonzero failure and continuous daemon recovery/atexit. Codex independent probes4/0.226s exit0 (/tmp/marlin-codex-r2b-resumed-probes.log); independent related modules142/16.419s Linux exit0 and142/22.979s Windows native exit0 (/tmp/marlin-codex-r2b-final-linux.log and -windows.log). Tested file SHA snapshot unchanged. Worker report table says lifecycle25 but actual suite24; accept actual142 total, not143; this is a report counting typo. Worker describes POSIX SIGKILL; Windows Popen.kill native path was independently exercised successfully. No claim of distributed HA/exactly-once or full commercial readiness.
Final real production-shaped desktop startup and Chromium login/workbench integration exit0, no JS page errors, launcher exit0 and listener closed (/tmp/marlin-codex-final-integration.log). Final graphify update AST-only exit0 (/tmp/marlin-graphify-final.log), git diff --check exit0. All8 current batch outcomes passed, no active Dispatch/reclaimable terminal obligation. Manual ZCode/Codex terminals retained; no commits/push/merge/publish.
