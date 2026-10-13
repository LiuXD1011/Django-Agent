# 根因已动态确认：外部Node无法加载ASAR内bootstrap

869旧来源包的正常GUI正式启动仍为FAIL。installed Runtime在Windows用独立bundled Node22 fork `path.join(__dirname,'runtime-bootstrap.cjs')`；其真实packaged `__dirname`在`resources/app.asar`，外部Node把ASAR当普通路径，加载bootstrap前即MODULE_NOT_FOUND并退出1。唯一改为相同bootstrap字节的真实physical路径，对照已完成native绑定、私有IPC ready→stopped→exit0。诊断host有明确instrumentation，不能当旧安装包正式GUI已修好。

## 原失败与三个不同范围

| 范围 | 真实结果 | 可以证明 | 不能证明 |
| --- | --- | --- | --- |
| 原installed正常Electron GUI/main19340 | 用户原图loading+Core代码1，正式startup FAIL；外98461/main/tree0 | 本次产品失败与生命周期收尾 | 登录、业务ready、正常tray PASS |
| 第一只读bundledNode探针 | addon.currentIdentity正确，exact ASAR路径resolve/require MODULE_NOT_FOUND；48236 actual0/Job0 | 原ASAR边界不可被独立Node读取，addon身份层正常 | Core业务启动、产品GUI PASS |
| byte-exact Runtime canonical host真实fork对照 | ASAR子1 vs physical子native/IPC ready→stop0；98736 actual0/Job0 | 唯一bootstrap路径变量可以解释并消除这一加载失败 | 原artifact已修改、新来源正式包GUI PASS |

原normal事实见[原GUI REPORT](../20261013-owned-runtime-installed-gui-preparation/REPORT.md)、[用户原图SHA证明](../20261013-owned-runtime-installed-gui-preparation/user-provided-startup-failure-evidence.json)、[原main/树终态](../20261013-owned-runtime-installed-gui-preparation/gui-terminal.json)。图SHA17623328602ce518e9c61c7cddc9e80280f5953e7caa4a882d51b41e8ccf2d10不编辑；main19340/FILETIME134363478637834112、outer98461 actual0与树0只收尾，未看到Core原HANDLE。原9 outside Codex Node终态仍alive、独立sentinel20044在GUI树终态后保持alive再自身stop0的事实保持；不把它们称旁业务窗口保护PASS。

## 源、真实依赖与包边界

[source boundaries](source-boundaries.json)记录installed/runtime/owned/bootstrap原字节与初读current相同，installed Runtime SHA1ae591f2a876fc4c38a996049c3b85fd0596bf0f86565b60e529812cb01cbb83，owned eeddc9…，bootstrap ccfb574f35675498db7756883594dc51295b3ef9990211fd2e4cc7ac1d4c51b3。完整读[installed Runtime](installed-runtime.cjs.source.txt)、[owned](installed-owned-runtime.cjs.source.txt)、[bootstrap](installed-runtime-bootstrap.cjs.source.txt)、[installed Core entry](installed-desktop-process.js.source.txt)、[current Core entry](current-desktop-process.ts.source.txt)、[当前NAPI源](current-runtime-job.cc.source.txt)，以及actual Node/Electron/fork/module类型、installed CoreOwner/client/worker/application初始化链。

实际addon是b3875cb777f4890c7ca8340819ef2324a2a384454c0995aab15f75fc8e82e4a9，bundledNode22.23.2 x64 exe SHA0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4；不使用独立fixture addon代替。原ASAR d4d16b42a36b0ec19357c74574217cd7deaa3969a6c61a99404af5e342fcc530未改。bootstrap的身份/import/pre-ready disconnect catch均可能close1，而Runtime只drain stderr；本次已在更早的模块加载边界获得确定证据，无需猜这些catch或业务凭据为原因。

旧准备门禁通过staging物理app/runtime.cjs、普通物理fixture；没有覆盖真实ASAR dirname→外部Node bootstrap路径差异。Root已另行修改当前Runtime路径为root/owned-runtime/runtime-bootstrap.cjs，当前只读SHAfb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112；Root报告相关31/31 passed。此生产修复非本agent执行、也不改变旧installed869字节。后续新包需另正式build/安装/GUI验证。

## 第一探针：只读ASAR加载边界

[计划](PLAN.md)、[探针源码](marlin-installed-core-asar-load-probe-20261013.cjs.source.txt)、[runner](marlin-installed-core-asar-probe-runner-20261013.py.source.txt)、[binding](asar-load-reviewed-binding.json) SHA9e3f5c6867507c28f7d9007c5f5cf99ecfd3d41beb8bf2ed400d35852f091139。

唯一session48236，首6470c9/末a71d3c actual0，2.413827秒。原bundledNode29752/FILETIME134363485858483372 Wait0/Exit0/Jobactive0；原conhost18352/134363485858794690同0，保留HANDLE全部关闭。[probe结果](asar-load-probe.json) SHA7af38a24834e108ebf3076a84a3cfa436f36843788a32b29899792299834202d，[原Job终态](asar-load-probe-execution.json) SHAe70e78418a2ac7b689a44e06999341c7d0518819500fdaa33a8f6e49cb0979ab。

实际addon.currentIdentity PID/FILETIME与原HANDLE一致。exact路径`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用\resources\app.asar\runtime-bootstrap.cjs`的Module._resolveFilename与direct require均实际MODULE_NOT_FOUND。另将原Runtime字节以canonical ASAR filename编译，只截获fork路径后立即拒绝：得到同exact ASAR script、bundledNode execPath/physical Core entry/cwd。这个host dry capture没有创建Core、没有读取DB/Key；其instrumented属性写入原结果，不伪称产品执行。

## 原paired helper语法失败1保留

首次真实paired helper少一个observer闭合大括号。我漏了执行前node --check，native script解析失败，没有创建baseline/physical Core子进程；此为helper错误，不能当产品对照结果。

原session83907，d5ef14→f3222f actual1，2.403681秒；原driver19596/FILETIME134363491721210092 Wait0/Exit1/Jobactive0，原conhost26316/134363491721774225 Exit0。[原execution](fork-comparison-execution.json) SHAe2b6478629817e86a7c5f5c923e1e6eadd709d41522f40d9526f3cc08411b2aa、[原binding](fork-comparison-reviewed-binding.json)、原两份helper源码保留。独立语法actual1与错误见[syntax RED](paired-helper-syntax-red.log)；[修订diff](paired-helper-v1-to-v2.diff.txt)、[语法证明](paired-helper-syntax-verification.json)记录新脚本--check实际0，不把原1改为0。

首次runner只生成新的owned诊断数据副本；Root批准的业务QA副本只读backup，77表/25opaque材料/三类active0/model_usage174。未触碰Source原QA。语法修复后v2固定新SHA、复核已owned未启动Core的副本，未重新clone、未运行GUI。

## 单变量真实fork：baseline1与physical0

[v2 JS](marlin-installed-core-fork-comparison-20261013-v2.cjs.source.txt)、[v2 runner](marlin-installed-core-fork-comparison-runner-20261013-v2.py.source.txt)、[v2 binding](fork-comparison-reviewed-binding-v2.json) SHAebd3144bf84b97a514694076f47e77fa501da5a80fbecc4d6355b5eaefbe4481。原Runtime/owned/bootstrap字节未修改；canonical module host只观察fork、原native.bindRoot与安全IPC阶段，physical case仅把script替换为原ccfb…副本。

唯一session98736，cd80e0→824bf7 actual0，5.1158624秒。[真实对照](fork-comparison-v2.json) SHA6eba3aba2af7f168aedd7be7f5ec652adf39976fc091acb590338eb38556e004，[原HANDLE/Job终态](fork-comparison-execution-v2.json) SHA608a1738116140faba1089500c929bdd12048657387340272ce8df59445afa65。

- 原driver34132/FILETIME134363494308624337 Wait0/Exit0/Jobactive0；原conhost33032/134363494308964106 Exit0。
- Baseline原ASAR真实fork子28928/FILETIME134363494331321589 Wait0/Exit1；原conhost33192/134363494331726023 Exit0。stderr764字节，仅MODULE_NOT_FOUND安全marker与SHA0ea6df3b…输出，无原文本落证据；没有owned-bootstrap/ready，authorized=false，Runtime stop/lifetimeclosed。
- Physical子21156/FILETIME134363494332303116 Wait0/Exit0；原conhost12456/134363494332587498 Exit0。收到owned-bootstrap→native.bindRoot真实status rootExited=false/active1→私有IPC ready(protocol1/TypeScript/http_listener=false)→stopped→child exit0；native原Job最后rootExited=true/rootExitCode0/active0，Runtime authorized=true/lifetimeclosed。parent与所有原保留成员终态、HANDLE全部关闭。

两case数据目录相同，entry/native/Python/worker参数（排除按生命周期正常随机generation）合同SHA同为cd716113…，env合同SHA同为bc62bb9f…，stdio/json序列化相同；唯一script是ASAR虚拟路径与byte-exact physical路径。physical ready约2175ms，仅是诊断ready→stop，不推断GUI启动时延或旧包可用。

诊断副本固定`C:\Users\lxd\AppData\Local\Temp\Marlin Core诊断 20261013\数据`，marker为marlin-owned-installed-core-diagnosis-20261013。两case共77表/25材料，desktop_jobs/task_records/agent_actors active前后0，model_usage174前后同。源owned业务QA DB/25材料严格前后SHA保持，诊断credentials.key与复制源SHA保持，没有解密/输出Key或读private-auth。未发送invoke/login/业务/model请求，没有产品GUI、HTTP服务或安装器。当前诊断时outside实际3个Codex Node原HANDLE保持alive；原正常GUI时outside9是另一个时点，不伪造一直9。

## 最小修复与必要回归

把供独立Node执行的bootstrap放在physical runtime资源目录，Windows Runtime指向该physical路径；payload复制、mandatory资源/源字节SHA及最终runtime manifest必须覆盖它。保留原native身份/Job/私有IPC机制，不需要修改用户凭据、模型、Core schema或增加system runtime依赖。

回归至少包含真正packaged ASAR dirname的Runtime→bundledNode→physical bootstrap→NAPI authorize→Core ready→stop，及physical bootstrap缺失/字节变化的强制门禁；普通fs fixture不能代替。Root已分派路径+31项回归与packaging复制/hash/ASAR gate，本agent只给动态证据，不改生产/build文件。源码/测试/review完成后需新来源正式prepare/package，再隔离安装正常GUI验收；旧869包原startup FAIL保持。

## 资源与边界

控制进程复用已审v2 owner052d7d…与utils8e9833…：CREATE_SUSPENDED→private Job→Resume，同原HANDLE/FILETIME持续观察，最长60/120秒；无新增异常清理代码、不按PID/image/port泛化kill。外部只读pin，Job0后关闭自己的原HANDLE。stdout/stderr用流hash与最多64KiB安全marker检查，不将任何Key/token/密码/raw数据库行/未经审查stack落证据；异常仅name/code与message/stack SHA。

自己的诊断helper使用结束后按[消费ledger](temporary-resource-ledger.json)归档核精确SHA删除；owned诊断数据目录、installed/originalQA/业务QA、旧失败图/回执/stage/output保留。无Git写入，无formalbuild或installer/normalGUI重放。Root确认用户关闭Fast、两平台service_tier default；本阶段没有修改tier或用其他档位绕过capacity。
