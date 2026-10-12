# 最新集成安装/启动：仅准备

本目录只包含新harness审阅资料。没有执行Windows进程调查、NSIS、Marlin、GUI、模型或注册表操作；主三文档checkpoint保持不变。旧安装/hidden失败/continue证据及工作目录不修改。实际计划见[设计](../../desktop-refactor/INTEGRATED-INSTALL-READINESS-PLAN.md)。

目前真实仅分块422的产品修复尚未形成新的最终freeze/完整prepare/package证据；已知043848…属于修复前阶段。没有可执行的artifact binding request，不预填installer SHA/大小或新版本安装通过。

## 文件与范围

待根代理执行的临时主脚本固定`/tmp/marlin-agent-integrated-installed-20261012.py`，审阅归档为[reviewed-harness.source.txt](reviewed-harness.source.txt)。最终SHA与检查结果记录在[preparation-manifest.json](preparation-manifest.json)。主脚本保留供根执行，消费后由根归档精确删除；此处guard临时脚本使用后另行删除。

复用两份原始归档，均不改：

- [541行升级原函数](../20261012-root-cancel-install-preparation/reviewed-harness.source.txt)，SHA256 `102b230813fece9297b8ce11a16dbb5d37ca8d3405cd1af8ac0a25ff95cd4965`。
- [688行启动最终原函数](../20261012-root-cancel-installed-launch-preparation/reviewed-harness-final2.source.txt)，SHA256 `8cf04e7bebb3cb77566507acb6ee6035a34d65c48e8feab5d54d846d06c94a4f`。

阶段共5个：bind-artifact、baseline、upgrade、hidden-smoke、visible-retained。首个阶段只读正式builder `verify_prepared`、成功prepare/package日志、ASAR/完整runtime、真实installer及sidecar/导出报告，生成新绑定；第二阶段在自然退出后采当前离线完整数据基线；第三阶段才执行私有JobObject中的NSIS；后两阶段分别启动独立空数据和既有retained数据。所有阶段默认不执行，需要root显式`--execute-reviewed`及阶段精确SHA参数。

安装和数据路径不接受参数，固定`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`和`验收数据 二次`；stage/output同设计。原可见旧安装27784/FILETIME134362309196213069必须由root自然trayQuit且所属树归零；保护25268/FILETIME134361236166333286及精确外部QA executable，不使用CIM datetime或CommandLine。PID复用由真实Win32句柄核验，未读到候选身份会拒绝；不将未知旧failed原因解释成已证实CIM缓存。

## 根绑定真实产物

每轮创建新的`reviewed-binding-request-N.json`，N为1–99整数。模板[reviewed-binding-request.template.json](reviewed-binding-request.template.json)有明确未绑定的null字段，不能被执行器消费；必须由root在实际新freeze和正式prepare/package/ASAR成功后填入真实值并全读/取SHA。必填键精确固定，未知键拒绝。sourceFreezeRelative必须是固定公开`docs/refactor-evidence/20261012-*`中的单层JSON文件，名称含source-freeze，可带迭代后缀；buildEvidenceRelative必须是该公开范围下单层目录。路径由root全读并SHA锁定的request确定，安装、数据、stage/output不允许更换。新freeze结构要求sourceInputs/additionalReviewedTestInputs/localCompiledOutputs为非空SHA集合；实际数量从真实freeze取，不写死451/520，正式builder来源必须完全等于sourceInputs。

N对应独立`iteration-N`收据、`.integrated-readiness-generation-upgrade-20261012-N`、`.integrated-readiness-generation-launch-20261012-N`、`启动验收 页面就绪 20261012 第N轮`及IPC空目录。已有iteration/attempt/receipt一律拒绝，不覆盖或自动重试。不同iteration不得重新解释先前failed为通过；初次实际安装仍要求原root-cancel升级收据的旧安装身份，若先前新升级已改变安装，需另行root复审新的前置身份，不能直接重复此harness。

## 精确执行命令

以下PowerShell仅供根代理全读后执行，本准备没有运行。复用脚本中的完整固定scope和guard；必须先完成旧27784正常退出，且在准备期间不改变源、stage、产物、注册表或retained数据。

```powershell
$taskScript = '\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-integrated-installed-20261012.py'
$taskEvidence = '\\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\docs\refactor-evidence\20261012-integrated-install-preparation'
& 'C:\Python313\python.exe' -B $taskScript
# 上一命令只输出review_only，Windows/应用/安装器调用0。
# root审阅并创建实际request后，再逐阶段执行；这里选择新iteration1。
$taskRequest = Join-Path $taskEvidence 'reviewed-binding-request-1.json'
$taskRequestData = Get-Content -Raw -LiteralPath $taskRequest | ConvertFrom-Json
$taskReviewedSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath $taskScript).Hash.ToLowerInvariant()
$taskRequestSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath $taskRequest).Hash.ToLowerInvariant()
$taskCommon = @('--execute-reviewed','--iteration','1','--reviewed-script-sha256',$taskReviewedSHA,'--binding-request-sha256',$taskRequestSHA,'--source-freeze-sha256',$taskRequestData.sourceFreezeSHA)
& 'C:\Python313\python.exe' -B $taskScript --phase bind-artifact @taskCommon
$taskIteration = Join-Path $taskEvidence 'iteration-1'
$taskArtifactSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $taskIteration 'artifact-binding.json')).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -B $taskScript --phase baseline @taskCommon --artifact-binding-sha256 $taskArtifactSHA
$taskBaselineSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $taskIteration 'readonly-baseline.json')).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -B $taskScript --phase upgrade @taskCommon --artifact-binding-sha256 $taskArtifactSHA --baseline-sha256 $taskBaselineSHA
$taskUpgradeSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $taskIteration 'executed-upgrade.json')).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -B $taskScript --phase hidden-smoke @taskCommon --artifact-binding-sha256 $taskArtifactSHA --upgrade-receipt-sha256 $taskUpgradeSHA
# root读实际smoke-window.png、确认登录画面，再继续visible；不是只检查mounted。
$taskHiddenSHA = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $taskIteration 'executed-hidden-smoke.json')).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -B $taskScript --phase visible-retained @taskCommon --artifact-binding-sha256 $taskArtifactSHA --upgrade-receipt-sha256 $taskUpgradeSHA --hidden-receipt-sha256 $taskHiddenSHA
```

每条命令应单独等待真实exit0并读其收据，不把整个块当无需审核的自动流水线；任一步失败立即停，不执行后续命令。计算出的SHA必须与本目录review archive及root全读后的request/receipt相等；仅现场重新取Hash不能替代审阅。visible命令持续7200秒以内每5秒输出owned存活状态，保持私有Job至正常托盘退出；不要因150秒工具yield主动关闭所属Job。

hidden必须实际mounted/pageReady=true、kind=login、精确startup_interval、Node隔离/preload IPC及fresh schema，记录mount/pageReady/renderer_wait/startup分别区间，截图由root另读；fresh独立实例只应出现登录页，不将所有业务加载完成算入ready。还执行原随包Node+FTS/vec 64bit、private fork和Python noDjango原断言，不借系统Node/Python或开发服务器。

## 本次准备的验证限制

本次只运行Linux Python实际harness的review_only、参数/实际request解析及档案/布局guard；本地fixture不是Windows安装/进程/GUI成功。Win32字段和函数原型已核已安装Windows SDK10.0.19041.0的TlHelp32.h/processthreadsapi.h；真正Windows权限、快照/退出、NSIS树、当前baseline、pageReady截图及新版生命周期未运行。没有Paid请求、秘密值、用户数据库或其他现有证据修改。
