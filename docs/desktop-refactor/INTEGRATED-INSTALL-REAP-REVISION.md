# 已安装验收bootstrap收尾修订

原visible27784经真实菜单退出后，旧harness已观察Job Accounting active0，却在末尾5000ms bootstrap Wait处failed；收据eed36…保留，具体Wait返回/lastError当时未记录。后续独立Win32同代次audit1aa9…已证明signaled/ExitCode0、窗口无，保护25268仍活；不能将独立事实回填为旧harness成功，也不能推断旧Wait确切原因。

根代理已授权新integrated harness的有限修订。保留原541/688归档、旧prepared8b源码归档和旧收据。选择新增纯bootstrap reap helper，通过已锁定SHA的AST，仅替换原run_owned_tree/run_installer_tree的末尾Wait5000+ExitCode三条语句，并给返回值加bootstrap_reap；其余原函数AST、900秒NSIS/7200秒可见预算、私有Job拥有和cleanup不变。完整复制原函数会扩大重复审阅，单纯延长原Wait不能记录失败类型或再次检查Job，均不选。

helper固定30秒上限、短interval，只读同CreateProcess handle Wait和JobAccounting；signaled、GetExitCode0、Job active0三者同时成立才通过。WAIT_FAILED立即抓lastError并拒绝，异常Wait/Accounting/ExitCode/非0退出或deadline各有固定公开码；公开记录观察elapsed/Wait/lastError/Accounting、预算和轮询数，无私有凭据、泛化kill、GUI或模型调用。增加harness收尾等待不是产品性能优化。

本机Windows SDK10.0.19041.0已核WaitForSingleObject(HANDLE,DWORD)->DWORD、QueryInformationJobObject(HANDLE,class,LPVOID,DWORD,LPDWORD)->BOOL、GetExitCodeProcess(HANDLE,LPDWORD)->BOOL与48字节JOBOBJECT_BASIC_ACCOUNTING_INFORMATION字段。此阶段只能Linux单位Win32替身：实际旧AST片段先RED，再真实新helper/受限AST变换GREEN；没有运行Windows内核/安装器/应用，不称原live根因复现或新版生命周期通过。

实施与验证：

- [x] 新临时测试提取原归档实际末尾判断，观察6秒signaled及仍active Job的功能RED；不用缺helper导入错误冒充RED。
- [x] 最小helper及原SHA+AST精确替换，来源不符/替换数量不符即拒绝。
- [x] 单位替身覆盖即时/延迟/child未退出、deadline、WAIT_FAILED与错误码、ExitCode非0/获取失败，最终12/12、核0终止调用。
- [x] 两原函数反向恢复后的AST完全相同，default review_only/原24guards继续24/24；新完整source/SHA及原RED/首轮GREEN/额外deadline RED保存，临时测试归档消费。
- [ ] 根全读修订与新SHA后，在实际新freeze/prepare/package绑定下执行；观察真实WindowsWait、pageReady和正常生命周期，此阶段不执行。

新审阅证据独占[reap-revision](../refactor-evidence/20261012-integrated-install-preparation/reap-revision/)，旧prepared manifest及8b源码不覆盖；根再审后才使用更新的/tmp主脚本。

根随后发现CJK关键词召回产品缺陷，旧85b refresh在source gate主动拒绝；其混合payload不能复用/重写manifest。本修订STAGE改为新的`Marlin TS Chinese Query Final Build 20261012`，OUTPUT不变；实际最终新freeze/完整clean prepare/package和安装器SHA仍待root绑定，原主进度checkpoint不在本修订改写。
