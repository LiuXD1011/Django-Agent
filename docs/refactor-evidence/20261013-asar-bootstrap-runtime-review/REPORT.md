# WIN-ASAR-BOOTSTRAP-001 Runtime 独立审查

2026-10-13。只审 Runtime 所属修复，不修改生产、Git、四份主文档或安装目录，不启动 Windows GUI／native 进程或付费模型。Root 已授权的[设计](../20261013-asar-bootstrap-fix/DESIGN-PLAN.md)是规格；独立完整阅读 Runtime、新回归、bootstrap、owned lifetime、main、实际锁定 ASAR 3.4.1 声明和实现，并核查[实现完整差异](../20261013-asar-bootstrap-runtime-fix/full-scope.diff)、[实现报告](../20261013-asar-bootstrap-runtime-fix/REPORT.md)及先前真实 Windows 诊断。[输入绑定](inputs-before.json)与[执行后绑定](inputs-after.json)涵盖 19 个来源。

结论：Runtime 生产修复符合本轮规格，未发现生产阻塞问题；有一个测试清理问题需要收尾。Root 已接手，不应将它升级为物理启动路径的失败，也不应在修复前称测试质量全部完成。此报告冻结原 test `184ca9c855368a7543b1f4cd0ba31dd72a03475410b9592332c59f8abb3dc813`；后续修复与核查须单独记录。

## 规格与质量核查

| 项目 | 独立判断与依据 |
| --- | --- |
| 正确资源根路径 | main 在 packaged 模式取 `process.resourcesPath/runtime`，开发模式取 payload；Runtime Windows fork 改取该 root 下 `owned-runtime/runtime-bootstrap.cjs`。外部 Node 可直接访问物理脚本，避免 ASAR 虚拟目录；非 Windows 分支仍直接使用 Core entry。 |
| 最小生产差异 | [before](../20261013-asar-bootstrap-runtime-fix/before/runtime.cjs) 与 [after](../20261013-asar-bootstrap-runtime-fix/after/runtime.cjs) 只有 fork 的 modulePath 一行改变；独立逐字替换验证见 [static-checks.json](static-checks.json)。Runtime 后 SHA `fb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112`。 |
| Node／IPC／授权 | bundled Node、Core entry／generation／nativePath／data-root 参数、cwd、execArgv、环境白名单、JSON serialization、stdio 和 hidden 不变。bootstrap 仍先发送 current identity；原 native bind 成功后才发 owned-start，之后导入业务。没有增加 renderer 权限或放宽 plain-object／generation 协议。 |
| cancel／shutdown／原 Job | bootstrap 与 owned-runtime 两个来源 SHA 不变。Runtime 请求、cancel admission、stop 与 RuntimeLifetime 保留原 ChildProcess 和原 Job，不引入名称／端口定位或新 fallback。新测试确认授权前 marker 不存在、正常 stop 后 child exit0／lifetime.closed。真实 NAPI／Windows HANDLE 完整判定仍属于 Windows gate。 |
| 回归有效性 | 测试用真实锁定 ASAR createPackage／packed 条目提取／statFile 和真实外部 Node fork，检查业务导入、private JSON invoke 与 exit。它没有对期望路径字符串作镜像断言；最终 fixture 的 before Runtime 重放仍会 MODULE_NOT_FOUND／exit1。 |
| 缺失脚本 | archive 内仍保留 packed bootstrap，但没有 physical 副本的场景真实 Node 退出1、stderr MODULE_NOT_FOUND、bind0、无业务导入；没有偷偷回退 ASAR。 |
| VM realm 修正 | 首次 fixture 失败保留为实际失败。修正是在 VM 自身 realm 对真实 JSON 反序列化，以模拟正常 Electron 向自身 realm 交付 IPC 对象；生产 plain-object 校验未改。 |
| 证据边界 | VM 代替 Electron loader 和 Windows platform；native identity／Job 和 Core 业务是明确 unit doubles。先前 Windows paired probe 用真实 NAPI／Core 的 physical 单变量成功是诊断，不是旧 installed GUI 成功。本轮不重复 31 项、完整 Core 或 frontend。 |

## 发现 R-01：初始化失败尚未注册 fixture 清理

等级：低，测试质量问题，生产阻塞数 0。原 [reviewed test](../20261013-asar-bootstrap-runtime-fix/after/packaged-bootstrap.test.cjs) 在 `mkdtempSync` 后执行 mkdir／copy／写 fixture／`await asar.createPackage`／archive 断言／VM 初始化，直到原第 72 行才注册 `t.after`。若上述 setup 抛错，测试没有删除新建自有目录。例如 pack 阶段抛错时会遗留 `marlin packed 中文 …`，无需涉及产品进程便可触发。

建议在创建自有临时目录后立即注册清理，允许 child 和 Runtime 尚未初始化；保持只清理自有 ChildProcess／目录／archive cache。Root 已明确接手该小范围修复，独立报告不跨写 test。此轮成功执行未留下新目录，不能据此覆盖上述失败分支缺口。修复后应只独立核新 2 项和该 setup 失败清理边界，并用新 SHA／单独证据保留本次发现。

## 独立执行

实际工具 `fcf662` exit0；[执行回执](independent-new-tests-execution.json)、[完整 TAP](independent-new-tests.log)：Node 22.23.2，ASAR installed／locked 3.4.1，命令 `node --test desktop/packaged-bootstrap.test.cjs`，2 tests／2 PASS／0 FAIL／0 SKIP／0 CANCEL，TAP 186.673746ms，wrapper wall 0.217414475s。两项属于实现方 31 项的子集，不重复计数。

执行前后 19 个输入字节相同，新增 fixture 残留0，未删除已有 fixture 目录。独立 helper [原文](review-helper.source.py.txt) 已按 SHA 归档后仅删除自身临时路径，见 [清理回执](helper-cleanup.json)。没有读取 Source QA 数据／Key，没有模型请求，也没有 Git 写操作。

## 后续集成限制

此结论只适用于 Runtime 所属来源。packaging 负责人正在实现 physical copy、mandatory SHA 和 actual packed Electron→bundled Node→真实 Core gate，不在此报告中视为完成。869a 旧 installer 的普通 GUI startup 仍为 FAIL；只有新来源构建、新包安装和 Root 正常窗口验收可改变产品判定。Goal 保持未完成。
