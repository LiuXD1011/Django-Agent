# Runtime 独立审查 iteration-2：R-01 已关闭

2026-10-13。完整读取 Root [清理修订报告](../../20261013-asar-bootstrap-runtime-cleanup/REPORT.md)及修订后的整个 test，独立核查只改 fixture setup／清理。当前 test SHA `46cdd96a9b4b625d0478a209b627204dc7bb8845981645695130c945cf939272`，见[审查原文](reviewed-test.source.cjs.txt)；生产 Runtime 仍是 `fb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112`。原 [R-01 发现及原版本结论](../REPORT.md)、原 SHA `184ca9c8…`、原 2 项执行与冻结保持，不覆盖。[完整前后 test 差异](cleanup-test.diff)及[本轮输入绑定](inputs-before.json)保留明确来源。

审查结论：R-01 关闭，新发现0，生产阻塞0。`child/runtime` 先声明，`t.after` 在 mkdir／copy／ASAR 创建等 setup 前注册，尚未初始化 Runtime 时使用 `runtime?.lifetime`；嵌套 finally 使 stop 或 uncache 异常仍经过目录删除。正常 Node／ASAR loader、IPC plain-object 校验、原 Job、正负回归断言均未放宽。

## 实际独立核验

工具 `7d6e45` 实际 exit0；Node 22.23.2。正常执行只包含 `node --test desktop/packaged-bootstrap.test.cjs`，见[完整 TAP](independent-new-tests.log)和[回执](independent-new-tests-execution.json)：2 tests／2 PASS／0 FAIL／0 SKIP／0 CANCEL，TAP154.663928ms。这两项仍是实现方 31 项的子集，不重复计数或视为新增完整套件。

另在独占临时目录复制相同 Runtime／bootstrap／owned-runtime 和两份 test，使用[临时 injector 原文](setup-fault-injector.source.cjs.txt)在 ASAR 的 `createPackage` 阶段故意抛错；它包装真实 fs 创建／删除以记录确切新目录，同时记录 uncache 调用。生产文件未被改写。两份 test 的 setup 都在 Runtime 初始化之前失败，不会因 optional Runtime 检查产生 TDZ／ReferenceError 或额外 hook failure。

| 受控故障实验 | 实际 Node 结果 | 清理观察 |
| --- | --- | --- |
| 原184ca9c8 test | actual1，2 tests／0 PASS／2 FAIL，预期注入异常；[TAP](before-cleanup-setup-fault.log)、[回执](before-cleanup-setup-fault-execution.json) | pack调用2、目录创建2、清理0、剩余2、uncache0，独立复现 R-01。 |
| 新46cdd96a9 test | actual1，2 tests／0 PASS／2 FAIL，仍保留预期注入异常；[TAP](after-cleanup-setup-fault.log)、[回执](after-cleanup-setup-fault-execution.json) | pack调用2、目录创建2、删除2、剩余0、uncache2，无额外清理异常，R-01 行为关闭。 |

这些 actual1 是故意注入 setup 异常的真实失败回执，不被改写为绿色测试或统计为通过。核验依据是失败后确切目录是否存在。抛错发生在真实 child fork 之前，可从 test 执行顺序判断 Runtime／业务尚未初始化；该边界并非 Windows native counter 的观测。本轮没有实际注入 stop／uncache 抛错，其 finally 行为只作完整静态审查。

审查结束仅删除原故障实验自行创建的两处残留和本轮独占实验目录，未删除其他已有 fixture；最终新增残留0。[validation](validation.json)记录生产及7个输入字节不变、原审查12个文件字节不变，以及确切清理范围。临时[helper 原文](review-helper.source.py.txt)已归档后精确删除，见[回执](helper-cleanup.json)。

## 集成边界

本轮没有重跑31项／完整Core／Frontend，没有 Windows GUI／native 或付费模型调用，不修改生产／Git／主文档。真实 ASAR＋外部 Node 的正常两项仍使用 VM Electron loader、Windows platform／Job 与 synthetic Core 替身。packaging mandatory physical copy／SHA／真实 packed Electron-Core gate 和新包安装后正常窗口验收仍由相应负责人完成；旧869a普通 GUI startup依然是FAIL，Goal未完成。
