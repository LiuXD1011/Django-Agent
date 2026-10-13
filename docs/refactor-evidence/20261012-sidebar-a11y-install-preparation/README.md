# 新侧栏包安装脚本：仅准备

候选为440行`/tmp/marlin-agent-sidebar-a11y-installed-20261012.py`，完整归档`reviewed-harness.source.txt`，SHA256 `95a8dafdcbae7ce14830e9ac2ca39c7c62516b6ba088710e12821bf9dab196ec`。Root已全文读取；执行仍未授权。本目录没有实际artifact绑定、安装、卸载、smoke、GUI、注册表或用户数据操作，也没有新的厂商调用。

基准是旧e48的399行[完整归档](../20261012-web-search-result-install-preparation/reviewed-harness.source.txt)，`harness-delta.diff`保存准确增量：新Sidebar A11y stage/output/evidence及自有WORK/新空数据，前一实际升级改绑a34/5cab，最近33404代次，当前来源严格绑定6e。默认review_only、完整ASAR/runtime与大小SHA检查、独立iteration、当前fresh12表/全部文件/凭据baseline、私有NSIS Job、6926同句柄30秒reap及pageReady/IPC/Node/Python断言保持。

进程守卫复用[76e11实际正常clone的checked_identity_api](../20261012-installed-clone-visible-launch/reviewed-harness.source.txt)：QueryPath/GetProcessTimes失败时先保存原Win32错误，再用**同一handle**Wait0及GetExitCode确认；只在signaled且exitCode可读时忽略已退出候选。仍活动、WAIT_FAILED、未知或无法读退出码都拒绝，没有泛化kill/CommandLine。成功取得身份后再核同handle当前活动态，避免把已退出对象按原第一次Wait结果认作活动。RACES记录候选PID/可公开basename、原错误/WaitAfter/ExitCode，成功及失败工具输出保留。

`guard-results.json`真实27项通过，包括默认脚本实际Linuxreview0、同handle状态替身的活/已退/WAIT_FAILED/退出码不可读拒绝分支，以及原artifact_binding/configure/execute、私有Job/reap算法的AST差异检查。状态替身不是Windows SDK或安装通过；执行候选只供Root以后全读/授权。guard与generator临时脚本精确归档删除，执行候选保持SHA待review。

`binding-request-unbound.template.json`的installer SHA/大小、prepare/package执行SHA及ASAR SHA均为null，实际parser会拒绝；这些必须在真实prepare与package成功后由Root绑定，不预填成功产物。当前prepare仍在途，package、installer及新empty hidden未执行。将来新hidden仅按正式`--smoke-test`新空数据做一次、完整保留结果，不加disable-gpu，不将早时点UnknownVizError归因猜测视作修复。若再复现再进入独立受控诊断，不自动重试。

正常clone另需绑定本次installed/source及**当前fresh业务/media/vault基线**，不能用旧restore完整audit与已登录后的认证增量强比。本候选仍是原retained升级/隐藏/retained启动步骤，不声称另一个浏览器副本启动已经准备或通过。

Root已核后续普通卸载的正式模板deleteAppDataOnUninstall=false；未来J03必须无`--delete-app-data`，精确绑定owned注册UninstallString/QuietString，并分别保护“验收数据 二次”与“浏览器资料副本 20261012 第1轮”的fresh文件/业务/vault及原25268自然运行。本候选不包含卸载动作，本轮禁止实际卸载。旧99ba产物和hidden/诊断失败、原升级/恢复/正常退出证据均不覆盖。
