# Windows clone restore / launcher 准备交接

仅准备，默认 `review_only`；不调用Windows SDK、不复制实际资料、不执行restore/Marlin/模型。本目录是新证据，不改任何旧failed收据。设计见[专项说明](../../desktop-refactor/OFFLINE-WINDOWS-RESTORE-LAUNCH-HARNESS.md)。

Root先完整读[主脚本归档](reviewed-harness.source.txt)、[Node审计](clone-audit.mjs)及[模板](binding-request.template.json)，再核[冻结](freeze.json)。临时主脚本保持 `/tmp/marlin-agent-offline-windows-clone-20261012.py`，消费后Root归档实际receipt并删除它。准备fixture helpers已经记录源码/SHA并删除；不依赖已删除8876 Linux临时脚本。

模板已有实际5cab来源、Linux export/result执行身份、两个不同manifest和成功prepare SHA。未知package/ASAR/artifact-binding/verified-upgrade/installer bytes/SHA保留占位值，不能执行。Root在新的 `reviewed-binding-request.json` 填入实际已完成、完整审阅后的身份，并取其整个文件SHA。这个新request与未来 `executed-*.json` 不在准备freeze文件中；准备freeze不会包含未来实际结果。

固定应用 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`，固定clone `…\浏览器资料副本 20261012 第1轮`，incoming/work/smoke全在独立 `…\.offline-clone-launch-20261012-1`。任何已有clone/work或该阶段receipt均拒绝重放，不删除或改名绕过。保护PID25268及FILETIME134361236166333286；其他已安装Marlin实例必须先由Root自然tray退出。它不安装、卸载、改注册表或修改旧retained/4modelQA。

审阅用的默认命令（Linux无产品调用）：

```bash
python3 -B /tmp/marlin-agent-offline-windows-clone-20261012.py
```

以下都是Root后续实际Windows执行的模板，`REAL_REVIEWED_REQUEST_SHA`必须换成完整真实64hex；默认模板尚不能执行。正式执行只使用固定安装的bundled Node/Python，环境PATH仅System32，不用开发服务、系统Node或renderer token。

```powershell
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-offline-windows-clone-20261012.py --phase restore --execute-reviewed --binding-request-sha256 REAL_REVIEWED_REQUEST_SHA
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-offline-windows-clone-20261012.py --phase hidden-smoke --execute-reviewed --binding-request-sha256 REAL_REVIEWED_REQUEST_SHA
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-offline-windows-clone-20261012.py --phase visible-clone --execute-reviewed --binding-request-sha256 REAL_REVIEWED_REQUEST_SHA
```

Root先核每一阶段actual `state=verified`才继续。restore使用正式 `core/dist/tools/migrate.js restore`、空目标、2400秒私有Job，整个backup/alltables合同保留；附加审计只打开owned clone。空smoke须真正登录页 `pageReady=true`、IPC/TS/无HTTP/无renderer Node、readiness区间及截图，截图仍需Root亲眼核验。visible阶段每5秒输出 `owned_alive`，持有Job最多7200秒；Root正常GUI登录并复核D02/H，再用这个新窗口自己的托盘退出。关闭标题栏只是后台，不能取消harness会话或由150秒外层限时杀Job。自然退出仍须同handle30秒内signaled/ExitCode0/Jobactive0，否则保留failed并人工核查。SDK failure只清理自己私有Job/仍挂起bootstrap，不按进程名kill。

范围限制：普通文件/key及全部受保护业务表须相同，Auth合法变化单独核查；绝对/非受控媒体引用拒绝，外部服务仅记录条件而不启动；无口令时留登录条件，不能改哈希/注册替身用户/注入token。脚本不会将 `manual_gui_verified=false` 改成通过，D02/H的真实截图/引用/下载证据由Root追加专项验收。

准备结果：[Python18项](preparation-tests.stderr.txt)为临时假目录与Fake SDK守卫；[Node纯helper检查](node-preparation-tests.json)只验证canonical/portable语义；[命令](commands.json)保留实际exit/耗时。这些不证明Windows native加载、原资料复制、真实页面、安装生命周期或整个Goal完成。
