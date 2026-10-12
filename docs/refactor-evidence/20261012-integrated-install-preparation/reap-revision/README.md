# Bootstrap reap修订：仅准备

根已授权对新integrated harness作有限收尾修订。主脚本仍`/tmp/marlin-agent-integrated-installed-20261012.py`，新SHA256 `6926f38880facafb627f417af36e54ab7a7c333b4718a129f5706d1ebc37bfbf`，[同字节完整审阅归档](reviewed-harness.source.txt)。旧8b源码归档/原prepared manifest/旧failed receipts完全保留，不能用本修订改写历史终态。[修订计划](../../../desktop-refactor/INTEGRATED-INSTALL-REAP-REVISION.md)说明范围。

原legacy三个末尾语句实际从541/688行归档提取执行。单位Kernel替身模拟6秒后signaled及未清空child Job，第一次RED因类继承重复计数4FAIL保留；修正测试继承后为2PASS/2FAIL，6项仅GREEN观察覆盖在RED跳过，不将其记通过。[有效RED](../reap-red-corrected.tap)。首次helper10/10 GREEN后，加慢Accounting/ExitCode越过30秒回归，再实际2FAIL RED，随后[最终12/12 GREEN](reap-unit-final.tap)无skip。真实原故障没记录Wait返回，不以这些单位场景推断其确切根因。

新helper固定30000ms预算、≤100ms同handle Wait；job accounting/exit读取后再次核预算，signaled+ExitCode0+JobActive0才返回。WAIT_FAILED即记录实际lastError并拒绝；其他错误/非0退出/timeout也有固定公开码。只记录Wait/elapsed/Accounting/退出码/轮询数和0 reap终止动作，不新增终止或重放程序。

[受限AST守卫](adapter-guard-results-final.json)对两个原函数都验证：只改Wait5000/ExitCode三语句及一个返回字段，反向撤掉这些改动后AST与原函数完全相等。原900秒NSIS/7200秒visible预算、创建/拥有/cleanup均原样；编译后的实际适配tail在单位Kernel6秒状态成功，源SHA不符拒绝。实际Windows Kernel/NSIS/app未运行。[原24项相关guard](nonexecuting-guard-results-final.json)在新source/STAGE继续24/24；[命令日志](related-commands.json)exit0，不把单位模拟或SDK核验当Windows通过。

## 新clean STAGE与绑定

85b54e…refresh由于root主动CJK源码变化被source gate拒绝，失败前部分payload已改变而旧manifest仍043848，因此不能把该stage当可信reusable依赖，更不能重写manifest冒充。根决定保留旧WORK，只在全新empty目录完整`--prepare-only`；新主harness的STAGE固定为：

`C:\Users\lxd\AppData\Local\Temp\Marlin TS Chinese Query Final Build 20261012`

OUTPUT仍固定`C:\Users\lxd\AppData\Local\Temp\Marlin TS Readiness Generation Installers 20261012`；INSTALL/DATA/GUID及保护25268/FILETIME、旧27784精确代次守卫不变。[新request模板](reviewed-binding-request.template.json)只更新STAGE，其实际新freeze/build receipts/installer SHA/size均null，不能执行。未猜测最后CJK来源/安装器身份。

最终[模板与review_only守卫](final-preparation-guards.json)确认目标平台PureWindowsPath语义下两个路径与main固定常量完全相等，模板和6926…主源码均未修改。首次validator误读工具JSON转义后错误预期路径不等，实际AssertionError已另存；字符码核实为单个分隔符，该校验脚本错误不作为业务RED。

根全读新source和SHA后，按[原五phase命令](../README.md)的相同顺序执行，但使用本修订scriptSHA和本模板生成新`reviewed-binding-request-N.json`（根审阅后取requestSHA），不得使用原old-STAGE模板或把现场Hash计算当批准。阶段仍bind-artifact→当前offline baseline→upgrade→hidden-smoke→visible-retained。原27784已由根实际Quit及独立audit证实退出，原visible失败不改；升级baseline应重采当前94files/12表/key，不能强求旧90文件或12表全同。

safe first command仍是review_only：

```powershell
& 'C:\Python313\python.exe' -B '\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-integrated-installed-20261012.py'
```

此阶段只有Linux实际parser/request/unit Kernel/AST和SDK签名核验；Windows进程、安装、应用、GUI、模型调用0。root后续独立执行真实Windows及pageReady截图/正常退出，不预填成功，也不将额外harness等待称产品性能优化。最终source/检查/链接/SHA与临时脚本消费见本目录freeze.json。
