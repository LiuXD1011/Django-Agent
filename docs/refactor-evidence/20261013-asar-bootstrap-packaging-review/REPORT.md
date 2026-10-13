# WIN-ASAR-BOOTSTRAP-001 packaging 独立审查

2026-10-13。结论：本轮 source 规格审查和质量审查接受，blocking0、新发现0。此结论允许继续执行已授权的当前来源 Windows 构建，不能代替实际目标平台门禁或新安装器的普通窗口验收。旧869a普通启动仍是FAIL，Goal未完成。

## 审查来源与范围

收到 implementation owner 明确稳定交付和停止写 scope 后，依据 Root [设计](../20261013-asar-bootstrap-fix/DESIGN-PLAN.md)审查[完整 implementation REPORT](../20261013-asar-bootstrap-packaging-fix/REPORT.md)和[完整含新增差异](../20261013-asar-bootstrap-packaging-fix/code-complete.diff)，完整阅读八份受影响来源：build_windows、verify-payload、audit-asar、start-desktop、windows-gates、startup.test、test_build_windows，以及新 verify-packaged-runtime。另读原 bootstrap、Runtime、owned lifetime、main、实际 Windows Job runner和产品 openNativeDatabase；核查安装并锁定的 ASAR3.4.1、Electron44.7.0 和实际 Node／SQLite声明。

[输入绑定](inputs-before.json)共29份；[执行后绑定](inputs-after.json)相同。八个 scope SHA逐个与 owner [最终清单](../20261013-asar-bootstrap-packaging-fix/after-sha256.json)相符。新 gate SHA `47925f8b5e8fdd54ce42e5c940e50d627970a6bfe731146f2b52171768b56e58`，builder SHA `9ceab93add98259a3128fe51d11c8b4c9f3b2bb6d23cf541b9a85d8e3cb46280`。外部已审 Runtime SHA `fb2b569b…`、cleanup后回归 SHA `46cdd96a…`保持；Runtime [R-01关闭记录](../20261013-asar-bootstrap-runtime-review/iteration-2/REPORT.md)未被覆盖。

## 规格与质量判断

| 核查项 | 独立判断 |
| --- | --- |
| Physical资源 | fresh stage_application和eligible refresh均逐字复制同一 source 到 `payload/owned-runtime/runtime-bootstrap.cjs`；现有12个ASAR资产继续保留，没有通过移除归档脚本或改Node ABI解决问题。 |
| SHA和来源 | write_manifest先要求physical字节等于source，再记录bootstrap_sha256。inventory校验实际文件集，start preflight同时检查app／physical／frozen source，actual ASAR audit把physical映射到归档条目字节。删除、改字节、重绑普通inventory都不能替代来源。低层utility可用于无source snapshot的合成测试；正常prepare／package／launch仍强制完整source绑定，不形成正常打包绕过。 |
| Source覆盖 | source_inputs已有scripts/desktop目录扫描会冻结新增gate，DESKTOP_GATE_FILES还显式加入新packed-bootstrap回归；JS startup的来源集合同步加入该test。源集合增删或变化使prepare／package复核失败。旧payload缺少新必需physical资源会被拒绝，本轮没有修补旧artifact来冒充新包。 |
| Packed实际加载链 | 新gate拒绝ordinary Node、RunAsNode和非win32/x64；检查prepared锁定official Electron路径与44.7.0。该真实Electron main通过canonical output `app.asar/runtime.cjs` resolve／require，再由Runtime使用actual output `resources/runtime`、bundledNode22.23.2、compiled Core entry和NAPI native Job。代码不把 ordinary staging IPC、VM 或 RunAsNode 当作此gate替代。 |
| Gate范围 | 使用prepared official Electron主进程加载packaged ASAR，而不是声称已正常打开 installed Marlin.exe。无renderer，profile／data全新且在application resources外；setPath在whenReady前执行，符合实际Electron声明。既有staging IPC和controlled Electron gates保留，各自边界独立。 |
| Core退出与数据 | Runtime.start之后检ready／capabilities setup_required／authorized Job，finally await stop；检查实际child exit0／signal null／lifetime.closed及failure list空。之后只用productNode／SQLite readonly+fileMustExist读synthetic model_usage_count=0，关闭SQLite句柄，核资源和manifest未变化。没有向vendor发送模型请求的代码。 |
| Original ownership／timeout | builder的run_owned动态加载冻结的原Win32 Job runner；该runner CreateProcess suspended→Assign private Job→Resume，保留原HANDLE／验证成员HANDLE，120s受控gate预算和5s清理期限，不按名字／端口终止。返回成功须树终态；失败／timeout拒绝gate，fixture清理只允许自己的exact path及`.owned`，拒绝链接或无标记目录。 |
| Strict report | report验证actual ASAR路径、八类资源哈希、frozen source、runner哈希和observed exit code；CorePID／协议／退出／计数拒绝bool冒充int，job_bound／job_closed和GUI范围声明必须匹配。actual report不能靠重新哈希或引用stale success授权。 |
| Packaging次序 | full和package-only共享package_windows：NSIS后再次核source／prepared，actual ASAR audit后强制run packaged gate，再核source／prepared，之后才copy installer及伴随gate报告到output。任一失败抛错时不会继续到copy。没有新增publish、版本或依赖变更。 |
| 两项回归适配 | native Windows gate采用严格fixed-path adaptation保持两项原body和全部assertions，并记录unit native／Core doubles的明确scope；它不是新actual packed Electron-Core gate。临时适配执行文件由finally精确删除，另保留review archive。 |

完整差异 `c410ce2f9f663cf99dc2adf7c7a57a3538ce8e1903eb35a96e61b48ed7d06712` 在独占临时目录从七份before及新增文件独立patch重建：[实际日志](independent-patch-reconstruction.log)／[回执](independent-patch-reconstruction.json)，actual0，八份后字节SHA全部相同，临时目录已删除。没有依赖Git unstaged diff推断完整范围。

## 独立执行与边界

实际工具 `25f48a` exit0；[完整日志](independent-targeted-tests.log)、[命令回执](independent-targeted-tests-execution.json)。Conda Python、Node22.23.2、实际ASAR3.4.1，只选择四个 `scripts.test_build_windows.PackageTests` 用例：mandatory/source bootstrap、actual ASAR audit、strict packaged report以及nonzero／timeout／missing-report cleanup。4／4 PASS，0FAIL／SKIP，unittest0.391s，wrapper wall0.494729559s。这是implementation49的子集，不另累加为新套件总数。

其中ASAR archive创建、提取和inventory audit是真实执行；Windows／Electron／native addon的report和failedrunner情形是synthetic unit projections，明确不算实际Windows gate。related原49=47PASS/2WindowsSKIP、startup135=130PASS/5WindowsSKIP来自owner准确回执，reviewer没有重跑这些套件、Core或Frontend。所有skip仍是skip；目前没有actual Electron／Windows执行，旧正常startupFAIL保持。

29份输入执行前后字节相同。独立[验证](validation.json)记录scope／API／外部Runtime绑定及界限。自有[helper原文](review-helper.source.py.txt)已归档按SHA精确删除，见[清理回执](helper-cleanup.json)；patch和所选测试只使用自有temporary fixtures。没有触碰Source QA DB／Key、private auth、Docker、GUI、模型或Git，没有写production、implementation证据、原Runtime review或四份主文档。

## 尚待真实验证

新实际packed Electron→ASAR→bundled Node→Core/native Job gate尚未在Windows执行。接下来必须以当前完整来源fresh prepare／package得到真实`PACKAGED_RUNTIME_GATE_EXIT=0`和严格有效report，然后新包隔离安装、正常启动／登录／页面／单实例／托盘／退出。source审查、上述四项Linux测试或gate helper单独0均不能替代这些结果。
