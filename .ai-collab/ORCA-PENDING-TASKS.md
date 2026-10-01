# 当前批次已完成（2026-10-01T04:40:57.763510+00:00）

8项全部独立验收passed。此文件下文为历史规格/状态，不能据旧dispatched/blocked重复派发。当前准确状态与后续缺口见ORCA-HANDOFF.md。

## 当前状态 2026-10-01T04:20:04.262028+00:00

D2 round2已独立验收passed：Windows30 exit0，Codex6probe exit0，执行者Linux30 exit0。原手动窗口保留并已复用执行SEC1 task_a8da76839ae3 / ctx_35705b9eeaf5（允许附带D2报告两处措辞勘误，msg见Orca）。R2B task_a225951b0d82 / ctx_7202552dc69a仍执行中。当前已批准8项中6项验收通过，2项执行中。禁止重复派发/提交推送发布。下面旧状态保留作历史，当前以本段为准。

# 已批准但未完成的 Orca 任务

协调 Run：run_c0d51a93432f。用户已确认额度恢复；两个ZCode握手Ready后原Task retry成功。当前D2-r2 task_7c898801f949 / ctx_bff176173eda；R2B task_a225951b0d82 / ctx_7202552dc69a 执行中。SEC1仍blocked待D2独立验收。下文旧Dispatch状态属历史记录，当前以本条与ORCA-HANDOFF.md为准。

## task_849586d20efa

状态：completed，Codex 独立验收 passed；依赖：无。

MARLIN-P02A Orca修复round2（新Task，前轮task_c88afbb1710f/ctx_e3d54d183f92已completed，不retry）。本项目marlin Windows优先。前轮Codex独立108项/7.362s通过，但验收changes_requested，本轮只解决下列具体缺口。仅可改 scripts/local_services.py、personal_knowledge_base/test_runtime_lock_portability.py、.ai-collab/ORCA-P02A-RESULT.md（原子替换）；model_rate_limit.py/open_rag_benchmark.py仅必要锁语义修复才可改，其余业务、P01四文件、依赖、配置、任务恢复禁止改。其他两个ZCode只读审计/设计。
R1 Langfuse：FileLock等待必须使用剩余原deadline预算且不能max(.05,...)增加预算。拿锁后、每次docker命令前先检查剩余>0，耗尽返回startup_timeout不调用后续Docker；超时使用剩余预算，不用max(.1,...)延长。保留既有早退/失败映射。确定性测试重现Codex发现：实际FileLock.acquire wrapper先真实acquire，再令mock monotonic超过既定deadline，ensure_langfuse应startup_timeout且docker 0调用（前轮实测2次）；另覆盖首个compose消耗剩余时间后不调第二命令。无需真实Docker/HTTP。
R2 测试进程：同key互斥、prepare blocking/nonblocking均用显式held/attempting/release屏障；不要让holder睡0.8/1.2s自行释放以猜测contender何时启动。慢启动不能漏验互斥，prepare released标志的写入顺序不能在unlock后与contender竞争。完成要communicate并校验实际exitcode与stderr；异常终止才kill。全部Popen创建从第一进程开始就在try/finally内，二次spawn失败也回收首个。_wait_marker可观察child提前退出并立即报stderr，无需空等30s。保留真实业务锁测试/异常释放/独立key并行，框架保持小。资源检查只在held期间，不假设Windows释放保留锁文件。
R3 最终runner：保存labels，白名单env，临时DB/BASE_DIR/MEDIA_ROOT，sys.argv=['manage.py','test']且settings覆盖在django.setup前；子进程已有unittest标记可保留。不要只setdefault继承业务凭据。一次合并原四模块+新模块即可，不重跑已知基线。Codex日志 /tmp/marlin-codex-p02a-r1-review.log 已证明108旧tests通过。
R4 报告勘误：exposure2是config路径/NameError测试草稿错误；exposure4只有3探针证实fcntl问题，第4是新FileLock实现约束，第5仅marker未出现（日志未证明fcntl崩溃，原prefix无blocker），不要臆测；原iso-regression.log首行startup recovery no such table警告说明runner副作用未完全隔离，不能称全部正式隔离已满足。保留真实历史并添加r2命令/退出码、新hash、新/改/删完整清单。graphify update直接记实际返回码，勿用tail的$?代替。原子写报告，保持P01四hash与HEAD。
完成前必须循环check并ack每个Delivery直到空，不能只reply部分消息后漏掉批次ack；每个自然检查点亦如此。按preamble ask提问，不能结束等用户。worker_done摘要3句，--files-modified只传一次逗号分隔CSV，列本轮实际修改文件（报告同时列整个P02A交付清单），--report-path真实。不提交/推送/合并/发布，不内置子代理，完成保留终端并停写。

## task_7312466bd6b5

状态：completed，Codex 独立验收 passed；依赖：无。

MARLIN-DESKTOP-D3：已批准首次使用可靠性修复，待协调者派发后执行。路径marlin，Windows优先。仅可改 frontend/src/views/Login.vue、frontend/src/stores/auth.ts、frontend/src/router/index.ts；新增frontend/src/views/Login.behavior.test.mjs、frontend/src/router/auth-guard.test.mjs（必要可合并一个，测试实际逻辑，不只正则）；新增.ai-collab/ORCA-FIRST-RUN-RESULT.md。不改样式主题、后端、依赖/lock/package脚本，不改其他worker文件。
具体问题：quickStart缺try/catch/finally导致失败后loading一直true；auth.autoSetup丢弃res.data.temp_password；router无token时静默autoSetup导致首次随机管理员密码丢失。采用最小显式初始化设计，无新页面。
行为：1.路由无token访问受保护页直接回/login，不调用初始化/创建账号；已有token原流程保留。2.auth.autoSetup继续persist已知认证字段，返回响应data供调用方使用；temp_password不得写localStorage/sessionStorage、日志、URL或分析事件。3.Login.quickStart显式触发，loading保护重复调用，清空旧错误，finally复位；setup_busy提示稍后重试，auto_setup_disabled提示此环境未开启初始化，setup_already_completed提示使用已有账号登录（disabled不是already_completed），未知/网络错有可读fallback。4.初始化成功先留在当前页，向用户一次展示后端返回的账号/临时密码（正常Vue转义），提示先保存并在设置中修改密码；用户点击“已保存登录信息，进入工作台”后才导航，不静默丢弃密码。临时信息只放组件内存，离开后释放；无返回temp_password时不能伪造，显示明确初始化已完成、说明需用已知凭据，避免自动再次初始化。不把建议改密码说成服务端已强制改密码。5.普通登录成功/失败保持；错误/忙后可重试，失败不导航，不重复建号。
验收：依现有langfuse.test.mjs用esbuild/VM或已有Vue compiler执行真实script/router逻辑，mock store/api/router边界。测busy/disabled/completed/网络错恢复、pending期间双击只调用一次、成功不立即导航且显示账号/临时密码状态、确认后导航、store返回数据但storage无temp_password、无token路由不调用autoSetup、普通login保持。避免把源码字符串存在当行为证明；测试用固定假密码，不用真实用户凭据。先有意义red后修复。
依赖由前一cleanup任务npm ci准备；若无依赖告知Codex，不安装新测试框架。npm --prefix frontend run test:unit和build均通过，必要现有frontend_contracts验证；原生Windows/browser未跑则not_run。报告命令退出码/全改动文件/遗留，graphify更新按协调窗口ask。preamble check每自然检查点及done前处理ack至空，ask只问Codex。worker_done三句+准确CSV --files-modified及报告路径。无内置子代理、不提交/推送/合并/发布，不关闭终端。

## task_9765eb989516

状态：completed，Codex 独立验收 passed；依赖：无。

MARLIN-CLEANUP round2 唯一缺口：仅可改frontend/package.json中test:unit、.ai-collab/ORCA-CLEANUP-RESULT.md（原子）。前轮completed不能retry；Codex独立Node22单元30tests/exit0、build/exit0、README links/exit0均通过，但用npm_config_cache=/tmp/marlin-review-npm-cache npm exec --yes --package=node@20.19.0 -- node --test 'src/**/*.test.mjs' (cwd frontend)实测exit1 literalglobnotfound，日志/tmp/marlin-codex-node20-unit.log。报告称Node20.19实测与证据矛盾，必须明确勘误，不能仅删历史。最小方案 test:unit改为cd src && node --test（Node自动发现src目录下所有*.test.mjs，先在Node20.19和当前22实际验证，无需增依赖/脚本）；若该方案不能覆盖全部19文件30tests，再ask批准极小fs递归runner。保留test:e2e/esbuild与其他文件；不改README支持范围以掩盖问题。验收两个Node版本均19文件30tests，原unit成功套件为对照；Windows未实跑不声称已支持实测；不必重跑build无业务变化。graphify由Codex，报告列前轮/本轮真实命令、exitcode。自然checkpoint及done前check/ack至空，worker_done真实CSVfiles一次，无commit/push/merge/关闭终端，不碰后端或其他worker文件。

## task_3eec37f60d3e

状态：completed，Codex独立Linux/Windows验收passed。

MARLIN-D1 用户数据目录分离（已由Codex自主批准；须在P02A/r2及恢复R1/r2验收后派发）。目标：Windows安装目录只读时所有运行写入可定向到独立用户数据根，源码资源仍从源码根读取。允许改 config/settings.py、新增config/runtime_paths.py、personal_knowledge_base/model_rate_limit.py、eval_dataset_registry.py、eval_reports.py、tasks.py（仅两处checkpoint路径）、scripts/local_services.py（仅Langfuse状态目录）、.env.example（只新增可选APP_DATA_DIR说明，ALLOW_AUTO_SETUP保持默认false）、新增personal_knowledge_base/test_runtime_paths.py、.ai-collab/ORCA-D1-RESULT.md（原子）；除此禁改，尤其accounts/P01测试/锁语义/恢复逻辑/前端/依赖。源码实际目录/home/liuxuedeng/orca/workspaces/Django-Agent/marlin。
设计：APP_DATA_DIR env可选，缺省现有BASE_DIR兼容；显式路径expanduser并resolve绝对，不要chdir去改变其他路径。settings.APP_DATA_DIR可用None代表未指定，统一runtime路径helper运行时fallback settings.BASE_DIR，保证既有override_settings(BASE_DIR=temp)隔离测试生效，而非导入时冻结旧根。可同模块放纯stdlib的resolve_data_directory(base,value)供settings和非Django的local_services调用，django.conf依赖只在必要函数内，不把local_services变成Django导入链。
数据库优先已有DJANGO_DB_PATH，其次APP_DATA_DIR/db.sqlite3；MEDIA_ROOT、STATIC_ROOT改用户根相应子目录；templates、前端dist、静态资源来源、dataset manifests、.env/.env.langfuse/docker-compose仍从源码BASE_DIR读取。五类cache全部迁移引用：model-rate-limits/eval-datasets/eval-reports/open-rag-runs(创建及cleanup根)/langfuse启动state+lock。Langfuse从已解析local_env获取APP_DATA_DIR，默认root既有行为。不自动迁移/复制/删除旧用户数据，不在import时mkdir/生成secret，不改变DEBUG/SECRET_KEY failclosed/ALLOW_AUTO_SETUP默认，不借设计报告D1全局生成密钥那段执行。Desktop launcher下阶段独立管理secret。
验收：新测试执行真实各path helper与实际临时写入并断言所有路径落userroot、source资源定位未变，显式DJANGO_DB_PATH优先；默认兼容和override_settings(BASE_DIR)不污染源码；隔离子进程验证DEBUG=false且无secret仍拒绝。含空白/空env处理与路径含空格。配合filelock真实测试和恢复/报告/数据集相关测试有针对性回归，不重复广泛基线；白名单env+temp DB/BASE_DIR/MEDIA_ROOT，argvtest在django.setup前，绝不访问真实API/DB。报告记录新改删全清单/测试命令/exitcode/Windowsnot_run，Codex将用已备Windows venv独立验收。graphify本波由Codex统一更新。自然checkpoint/done前check+ack至空；按preamble ask决策；worker_done真实三句和一次CSVfiles；不提交/推送/合并/发布/关闭终端。

## task_3eaaedeb24fd

状态：dispatched，ctx_d84c89eb85bf；旧ctx_01684d22edc2确认进程被终止后failed，同Task retry，详见ORCA-D2-RECOVERY.md。

MARLIN-D2 最小Windows桌面运行入口（Codex批准，D1验收后才能派发；已有设计报告错误，以本Task为准）。允许新增 scripts/start_desktop.py、config/desktop_wsgi.py、personal_knowledge_base/test_desktop_runtime.py、docs/desktop.md，修改requirements.txt（只增waitress>=3.0,<4及whitenoise>=6.12,<7，保留已有依赖）、root package.json只加start:desktop脚本、README桌面启动/首次初始化说明，新增.ai-collab/ORCA-D2-RESULT.md。D1/config.settings/任务恢复/前端与P01原则不改，需要额外范围用ask。无Electron/Tauri/安装器/自动更新/签名/付费/真实用户数据演练。Codex将独立Windows native验收。
实现可维护的小入口，不单文件堆巨大框架：主入口仅显式desktopmode，--data-dir/--port/--no-browser，缺省Windows LOCALAPPDATA/Marlin，Linux XDG_DATA_HOME或~/.local/share/marlin；Windows只能明确127.0.0.1监听，port合法范围，源码/前端dist资源定位保持源码根。未构建dist/index.html时清楚失败，不自动npm install。专用用户目录instance FileLock非阻塞，重复实例清楚拒绝，不删数据/锁来绕过。持锁期间安全创建/读取非空持久应用secret（原子写、POSIX0600、不输出密钥，不宣称Windows ACL已保障），只由desktop入口生成，generic production settings仍缺secret报错。子进程环境强制DJANGO_DEBUG=false、DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost、APP_DATA_DIR和DJANGO_DB_PATH指向选择目录，LANGFUSE_AUTOSTART=false；ALLOW_AUTO_SETUP仅显式desktop入口设置开启，普通.env全局默认不变。
顺序：先迁移成功，再启动Windows可用Waitress web与run_task_worker --queue evaluation（documents已由web现有机制执行，不要误开documents却漏evaluation）。迁移失败不启动二者；已有库且存在待迁移项时用SQLite backup API先备份data/backups，非空已有secret失败要报错不要无声替换，第二次无新迁移不反复生成backup；不复制/移动旧项目库。web与worker都用sys.executable创建直属Popen，不用shell执行字符串，不启动Docker/真实LLM。支持源码路径/数据目录带空格。
config/desktop_wsgi.py是独立桌面WSGI入口，使用WhiteNoise只服务已构建frontend/dist/assets映射/assets/（正确JS/CSS MIME），正常Django负责SPA深链/health/API/files鉴权；不拿django开发static视图冒充生产，不整个用户目录静态暴露，不改通用WSGI部署。桌面边界：对有Origin的API写请求仅允许本机同源(含实际端口)，拒绝null/外部站点；auto-setup限定POST，GET不能建号；token/初次密码响应no-store，不把实际密钥/密码记录日志。可在desktop_wsgi包装实现以不扩大P01全局变更。本机CLI无Origin请求允许，Host白名单保持生效。
健康检测必须验证自己启动的web（例如随机instance_id响应头+比对，同时检查子进程poll），不能端口被另一健康服务占用仍显示成功。全部启动wait/HTTPprobe有timeout并禁系统代理，web/worker任一提前退出则整组失败回收，健康才可选webbrowser.open。Ctrl+C/正常退出/启动失败都仅terminate/wait再kill本入口实际持有的子进程，有限等待，绝不按端口/泛化进程名杀其他服务；finally释放实例锁。--no-browser供无人值守验收，不留下服务后台。
测试：真实临时目录secret重启保持/双实例拒绝/源码资源不写；migrate失败、端口占用、健康属于其他实例、worker提前退出、启动超时、停止清理；测试WSGI资产和深链返回200且API/files未暴露；异站Origin的auto-setup拒绝且DB零残留，合法POST仍可初始化；mock不得仅断言实现形状，必要真子进程/临时端口。白名单env与临时DB/数据路径，真实当前工作数据/凭据/外部服务禁止读写。报告实现范围、全部文件、真实exitcode、Windows未跑项目，不声称打包完成。
README/docs明确这是本地源码运行交付基础，不宣称已签名安装包；首次初始化经用户点击并保存临时密码，默认不开Neo4j/Langfuse，需要模型配置的功能如实说明；保留已有开发入口。任务恢复R2另worker/后续独占修改，别自行修。graphify由Codex统一；checkpoint/done前check+ack至空，ask按preamble；worker_done真实3句/一次CSVfiles/报告。不得提交推送合并发布或关闭终端。

## task_0940d993e9ab

状态：completed但审查changes_requested；返工新Task task_4d324a6ff347 / ctx_a0466644ac33执行中。

MARLIN-R2A 评测进度/检查点的属主保护与状态一致性，Codex已批准，仅D1验收后派发。允许修改personal_knowledge_base/tasks.py、新增personal_knowledge_base/test_task_ownership.py，必要修改已有test_evaluation_examples.py/test_ragas_evaluation_loop.py/test_task_recovery.py的调用契约与回归（不得弱化断言），新增.ai-collab/ORCA-R2A-RESULT.md。R1/r2已Linux101/Windows98验收，保持其CAS与取消语义、D1路径、P01/P02A锁不变，无配置/迁移/依赖/前端/其他views文件改动。不要读旧审计全文，只读以下函数与调用关系。
问题：_update_open_rag_runtime只按id/status读写，旧worker可覆盖新owner payload/result/progress并写本进程cache；两个评测任务函数的write/save_checkpoint回调及完成unlink没有属主校验，所有owner共用同一文件和.json.part；task_status先读locmem cache会无限遮盖其他进程已完成/删除的DB记录。
方案：所有实际评测回调显式传捕获的worker_token，runtime UPDATE用_owned_task_records守卫并防快照被抢后改写；0行不写cache，调用方及时停止而非继续昂贵工作。检查点serialize等计算放锁外，持有者才能发布/删除；推荐最小做法在短transaction.atomic内先owned CAS取得行写锁（SQLite数据库写锁）后完成同目录唯一临时文件原子替换/删除，令新的claim/reset必须等这段完成，不能只先exists检查再文件写（TOCTOU仍在），不可在事务内做网络/模型调用。临时文件唯一，0600，finally清理本次临时文件；保留当前task checkpoint路径和重启/resume兼容，不复制海量payload进DB、不引入Redis分布式锁、不声称文件与DB严格两阶段提交。可留明确的离线测试/导入工具unfenced helper，但所有production调用必须走fenced入口，空token兼容只允许实际无owner的legacy运行记录，不得匹配非空newowner。清理/完成删除也不能删新owner checkpoint。如实际结构需要不同等价方案，用ask说明原子性证明再做。
task_status以DB为权威，不能拿8h本进程缓存遮盖新进程完成/删除；保持API字段兼容和tenant鉴权（active路由在compat_views已鉴权，本Task不改）。选择一次主键DB查询的简单方案即可，避免新缓存协调机制。_run_task在重试fn前若已失主/取消应停止，保留仍持主的真实database-is-locked有界重试，不宣称所有外部副作用exactly-once。
验收用确定性真实DB交错覆盖旧owner progress/回调写/完成unlink不得覆盖或删除newowner、同owner正常写与恢复读可用、唯一tmp异常回收、legacy兼容；同时真实两个进程/临时SQLite+文件至少验证一次write与reclaim互斥（屏障同步、有界reap/exitcode，不能sleep猜时序）。跨进程改变DB后旧cache读必须给最新终态，DB删除则not_found。相关eval/task/compat测试一次有针对性回归，临时DB/BASE_DIR/MEDIA_ROOT、白名单env，禁止真实模型/网络/用户数据。报告实际diff全清单、命令exitcode、not_run及保留语义；graphify由Codex整波统一。checkpoint/done前check/ack到空，ask按preamble；worker_done真实CSVfiles一次；不提交推送合并发布或关闭终端。

## task_a225951b0d82

状态：dispatched，ctx_734a5b249ea8；R2A-r2验收passed后放行。

MARLIN-R2B 持续任务恢复，Codex批准；R2A属主/检查点保护验收后派发，避免先扩大幽灵写发生面。仅可改personal_knowledge_base/tasks.py（恢复过滤/调度部分）、personal_knowledge_base/management/commands/run_task_worker.py、personal_knowledge_base/test_task_recovery.py；可新增personal_knowledge_base/task_recovery.py及test_task_worker_lifecycle.py；新增.ai-collab/ORCA-R2B-RESULT.md。其他业务/配置/前端/依赖/迁移不改，无Redis/Celery/多机集群。
当前schedule_startup_recovery只有0.1/90.1秒两个Timer，此后崩溃worker租约永远不恢复；run_task_worker只查pending且不触发startup recovery。改最小常驻有界恢复loop：每进程最多一个daemon线程/stop Event、固定可测试间隔(约30s)、首次检查保留启动小延迟，连续周期直到停止；失败记录简短错误并等待下一间隔，不能tight spin或重复创建无限Timers。close_old_connections在每轮前后，shutdown/命令异常finally stop/join有限时间；管理命令/test/migrate/autoreload-parent过滤仍有效。向量重建启动检查只在初始化执行，不每30s重复触发全量重建。web可恢复原有队列；worker命令只恢复其--queue队列，必须即使正同步执行长任务或队列持续繁忙也有扫描，不能仅空闲时检查。
给recover_incomplete_tasks增加可选queue_names过滤时，作用于所有分支（unsupported/process_knowledge/generic等），保持默认全队列行为和R1 snapshot CAS；pending->eval worker消费仍不被web直接运行。--once保持既有drain语义，执行一次确定性恢复后处理可用pending直至空并退出，不留daemon；正常模式finally停止自身恢复loop。对invalid/nonfinite poll间隔清楚拒绝或安全下界，不无限忙等。保持worker持有token语义与取消/终态，不能重置活跃续租者。
验收：用事件/可控时钟或可控wait验证超过原90秒窗口后仍扫描、繁忙worker期间仍扫描、正确queue边界、异常后下一周期可用、启动幂等、stop不遗留线程、--once drain并退出。可用R1/R2A真实跨进程机制证明持有者崩溃后待租约过期被恢复且后继只认领一次（允许测试缩短间隔，禁止长sleep猜时序和真实模型调用）；同步顺序任务、取消、租约回归一次合并测试。不得为形式重跑大量已验证基线。隔离白名单env/temp DB/BASE_DIR/MEDIA_ROOT，报告命令/exitcode/所有改动与not_run；不宣称高QPS/多节点HA/exactly-once。graphify由Codex统一，check+处理+ack每个自然checkpoint和done前至空，按preamble ask；worker_done准确CSVfiles一次。不提交推送合并发布/关闭手动终端。

## 2026-10-01 最新协调状态
D1已独立验收passed；D2 ctx_01684d22edc2执行中；R2A首轮报告完成，独立24项exit0但changes_requested，round2规格见下。R2B须等round2验收通过，不能仅凭原Task completed启动。SEC1 task_a8da76839ae3待D2验收。

MARLIN-R2A round2 定向返工，新Task；原task_0940d993e9ab/ctx_58790f1fbfa7已正式完成但Codex changes_requested，不能retry旧完成Dispatch。只改personal_knowledge_base/tasks.py、test_task_ownership.py及必要原eval测试契约，原子更新.ai-collab/ORCA-R2A-RESULT.md；不碰D2桌面文件/依赖/前端/D1路径/R1 CAS谓词。Codex刚独立24项exit0，但仍有以下代码证据阻断。
1 原始claim身份丢失：_run_task持有worker_token，但两个evaluation函数876/1432仍从再次读取的record payload/claimed_by取token。若原owner检查后被reclaim，新执行开始前旧fn可读取并冒用新owner token。将原始(task_id,worker_token)限定在执行上下文，例如ContextVar在_run_task调用fn外set/finally reset，evaluation入口捕获原上下文token且task_id必须匹配；不可从fresh DB替换已有上下文身份。无上下文直调测试/legacy需明确兼容边界，不允许跨task串用。加确定性测试：claim后到evaluation读取前更换owner，旧回调不能写DB/checkpoint；context异常/返回后恢复，重试保持同token。
2 _cleanup_open_rag_checkpoints仍stat旧mtime后无锁unlink，可能删new owner刚replace的新checkpoint，且会删长期running/pending可恢复任务。必须与fenced发布使用同一DB互斥边界，并在边界内重新判断mtime/任务可恢复性；至少保护active/recoverable记录，不用exists检查假装互斥。可选择更保守只清理已终结且确认过期的记录，未知/无记录跳过，避免引入分布式锁。测试旧mtime检查与新owner发布交错不会删除fresh文件、active恢复文件保留、真正终结过期文件仍能清理；唯一tmp异常不残留。
3 task_status运行态stage/partial_metrics依旧来自旧locmem cache，DB result已有新值也会输出旧顶层字段。保持API展平兼容，直接从最新DB result构建允许runtime字段；不要把cache未经owner/version校验当权威。加DB stage judge vs cache retrieval断言并保留现有终态/not_found/progress测试。
测试先暴露上述缺陷再修；Codex已有5probe+19tests仍需通过，必要eval/task回归一次，真实并发测试保留屏障/有界回收，隔离临时数据、白名单env，无真实模型/外部服务。不运行graphify由Codex整波更新；不提交推送合并发布，不关闭终端。按实际preamble每个自然checkpoint及done前check处理并ack全部协调消息，ask问Codex，正式worker_done准确报告全部files/真实命令exit/未解决问题后停止。

MARLIN-SEC1 前端依赖审计修复，round1，Codex按用户总体目标自主批准。只在D2验收后派发，避免其产物验收期间改变前端构建。只可修改frontend/package.json、frontend/package-lock.json、新增.ai-collab/ORCA-SEC1-RESULT.md(原子)。不改业务源码、root package、Python依赖、任务/桌面入口、文档或他人文件；不提交推送合并发布。
问题证据：Codex npm_config_cache=/tmp/marlin-review-npm-cache npm --prefix frontend audit --json 实际exit1，/tmp/marlin-codex-npm-audit.json(2026-10-01)：axios direct high <=1.19.0 修复>=1.20.0；nanoid transitive high<=3.3.17；postcss transitive high<=8.5.22；esbuild direct/transitive low0.27.3-0.28.0，audit建议0.28.2。以执行时实际registry/audit及锁定版本为准，不把推断版本写成实测。
目标：最小兼容依赖调整使npm audit --json无high/critical，尽可能消除全部四项；不可盲目npm audit fix --force或升级整套Vue/Vite生态。保留Node20.19+/22兼容与现有unit/e2e脚本。可升级axios同主版本、PostCSS/nanoid安全补丁、esbuild直接依赖及必要最小override；若要跨Vite主版本或无法避免大范围变更，按preamble ask Codex，先说明lock差异与兼容证据。不能靠省略dev依赖/ignore漏洞/改audit阈值掩盖结果。任何保留项须明确真实适用边界、版本、原因，不称audit全绿。
验收：npm ci从最终lock成功；npm run test:unit现有45项(或后续正式新增数量)全部发现且pass；npm run build通过；Axios运行时升级需跑既有test:e2e38项，验证登录/知识库/聊天等现有mock协议回归。无需真实模型/账号/用户DB/外部业务服务。报告真实命令与退出码、前后audit摘要、实际解析版本和所有改动文件；pipe tail不能替代真实exitcode。Windows npm实际unit由Codex在已备native临时frontend目录验收，不宣称你跑过。缓存用/tmp、测试数据临时隔离；不要删除用户node_modules以外数据或改git历史。按实际注入preamble在自然checkpoint及done前check/ack全部消息，ask只问Codex；worker_done正式报告真实files CSV与report路径后立即Ready，不写个人memory；graphify由Codex统一。

## D2 round2 当前修复Task task_7c898801f949 / ctx_31326d0ea19c
MARLIN-D2 round2 定向返工，Codex批准。原task_3eaaedeb24fd/ctx_d84c89eb85bf已正式完成，但Codex审查changes_requested，新Task而非retry已完成Task。只可改根package.json、config/desktop_wsgi.py、personal_knowledge_base/test_desktop_runtime.py、原子更新.ai-collab/ORCA-D2-RESULT.md；scripts/start_desktop.py仅发现真实生产清理缺陷时按ask批准后改，其他D1/R2/前端/依赖/文档禁止改。
1 根package.json你按HEAD恢复packageManager pnpm与devDependencies.@playwright/test，实际上回退了已批准cleanup，不是修草稿越界。证据.ai-collab/ORCA-CLEANUP-RESULT.md 62-63行：统一npm并移除根重复依赖，Playwright已直接声明于frontend/package.json。请重新移除根packageManager/devDependencies（现只含Playwright），保持四原脚本+start:desktop；报告勘误“恢复草稿误删”的错误断言。不能把HEAD当当前批准基线，不能重加根lock。
2 desktop_wsgi._same_origin移除netloc比较后只检查两端均loopback和端口，漏了hostname相等，http://localhost:8899可伪作Host127.0.0.1:8899同源。Codex /tmp/marlin_codex_d2_probes.py新增第6项，当前5pass1fail exit1，日志/tmp/marlin-codex-d2-origin-review.log。补规范化hostname相等（大小写正规化），保留隐式80==显式80、安全拒绝userinfo/null/外站/错端口，添加反向loopback alias也拒绝测试；不能仅放行所有loopback。
3 Windows原生全模块29项实跑2fail2error exit1，/tmp/marlin-codex-d2-final-windows.log；Linux29/23.051s exit0。两PermissionError WinError32来自测试with sqlite3.connect只管理事务、不关闭连接，5处均用contextlib.closing或finally显式close，不能ignore_cleanup_errors掩盖或跳过Win测试。env契约硬编码“/data dir”与Windows实际“\data dir”不等：改比较Path/str(Path(...))且保留真实值语义，不能只删断言。
4 worker早退测试Windows _port_refuses立即False。Codex独立单项/tmp/marlin-codex-d2-port-probe.log证实首次False、100ms后True，WindowsCIM核实无残留waitress/worker/launcher进程；目前是退出后端口释放可观察性短延迟，未证实生产进程泄漏。测试改有限deadline的条件轮询等待端口拒绝（2-3秒上界，保留最终断言），不要无界while或固定sleep假通过，确保正常/异常路径全部owned进程returncode/wait证据；若实际发现生产泄漏，ask Codex附证据，不擅增JobObject/泛杀策略。
验收：先复现再改；独立6probe通过；Linux desktop模块（现29+新origin用例）通过；测试必须真实exit0。Windows由Codex使用现有临时native venv再验，worker不冒称运行。无需再跑已验证无关后端/前端全套，不改底层失败断言来掩盖问题。保留已有完整D2行为和8项恢复修复，report追加round2实际文件/命令/未跑项与勘误。每自然checkpoint/done前check/ack，ask依preamble；worker_done正式准确一次后立即idle，不写个人memory、不提交推送合并发布，不关闭终端；graphify由Codex统一。

## 配额阻塞结算
D2-r2 task_7c898801f949 / failed ctx_31326d0ea19c；R2B task_a225951b0d82 / failed ctx_734a5b249ea8；均blocked，无worker_done。恢复必须同Task --retry-of，不能创建重复任务。SEC1未执行。
