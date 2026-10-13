# WIN-ASAR-BOOTSTRAP-001 Runtime 修复

Source Runtime 已完成最小修复：Windows fork 的 bootstrap 从 ASAR 内 `__dirname/runtime-bootstrap.cjs` 改为 `path.join(this.root, 'owned-runtime', 'runtime-bootstrap.cjs')`。生产仅[一行差异](full-scope.diff)，不增加 options、fallback 或新权限。bundled Node、Core entry／argv／env、私有IPC／generation／NAPI Job授权、取消和退出代码保持。物理资源复制及正式packed Core gate归属packaging负责人；新安装包／Windows GUI未在本轮执行或声称通过。采用Root已批准的[设计](../20261013-asar-bootstrap-fix/DESIGN-PLAN.md)和本轮[实施计划](PLAN.md)。

新增 [packaged-bootstrap.test.cjs](../../../desktop/packaged-bootstrap.test.cjs) 使用已安装且锁定的 `@electron/asar` 3.4.1；完整阅读实际声明及 createPackage／extractFile／statFile实现。测试创建真正 packed `app.asar`，从真实条目读出生产 Runtime源码，以 canonical archive filename／`__dirname`在VM执行；真实外部 Node22.23.2随后加载原bootstrap字节并进行JSON IPC。VM明确替代Electron加载上下文及Windows platform；native identity／Job和无DB Core业务是明确替身。这里不是实际Electron ASAR require或Windows HANDLE／完整Core验收，这些由正式package gate补足。

第1项验证授权bind前业务尚未导入、原data-root参数保留、ready后私有invoke200、实际Node正常exit0和lifetime完整关闭。第2项在ASAR仍含packed bootstrap时移除physical副本，要求真实Node报MODULE_NOT_FOUND／exit1且无业务import／bind，证明没有packed fallback。临时fixture及子进程在测试结束时精确清理，不访问真实Source／QA数据库、Key或模型。

| 实际执行 | 结果 | 证据 |
| --- | --- | --- |
| 修复前原回归RED | actual1，2总／1PASS／1FAIL，0SKIP；真实ASAR路径MODULE_NOT_FOUND／Core code1 | [日志](red.log)、[回执](red-execution.json) |
| 首次GREEN尝试 | actual1，2总／1PASS／1FAIL；外部Node已到ready，测试VM跨realm对象导致private wire拒绝 | [原日志](green-fixture-failure.log)、[原回执](green-fixture-failure-execution.json)、[原fixture](first-fixture.source.txt)。仅修测试JSON在VM自身realm反序列化，未放宽生产plain-object检查 |
| 最终fixture重放before Runtime | actual1，2总／1PASS／1FAIL，0SKIP；仍正确复现ASAR MODULE_NOT_FOUND／code1 | [日志](corrected-fixture-red-replay.log)、[回执](corrected-fixture-red-replay-execution.json)。独占临时目录中使用原Runtime，未回滚共享生产文件 |
| 新回归GREEN | actual0，2／2PASS、0FAIL／SKIP；TAP150.249194ms | [日志](green.log)、[回执](green-execution.json) |
| 六个相关desktop测试文件 | actual0，31／31PASS、0FAIL／SKIP；TAP8451.024336ms | [日志](related-tests.log)、[回执](related-tests-execution.json)；含新ASAR、现有真实IPC Runtime／本地模型fixture、bootstrap授权／startup取消、shutdown原Job边界、quit与8个durable cancel admission。新2项属于31总数，不重复累计 |

上述本地模型fixture用自己的小型HTTP响应，不发外部厂商付费请求。没有重跑完整Core或Frontend套件，没有WindowsGUI／安装器或真实Source数据写入。原Windows正常启动FAIL与原v2 review accept均保留；本轮Source修复及相关测试不能替代新包构建、安装和普通GUI的最终判定。

[完整绑定](change-binding.json)：修改 `desktop/runtime.cjs` 前SHA `1ae591f2a876fc4c38a996049c3b85fd0596bf0f86565b60e529812cb01cbb83`，后SHA `fb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112`；新增test SHA `184ca9c855368a7543b1f4cd0ba31dd72a03475410b9592332c59f8abb3dc813`。bootstrap ccfb574f…和owned-runtime eeddc9f5…原字节相等。本轮完整scope为1修改＋1新增，差异从[before](before/runtime.cjs)与[after Runtime](after/runtime.cjs)／[after test](after/packaged-bootstrap.test.cjs)生成，未依赖unstaged diff；在自有临时目录实际patch重建后两文件SHA相等、actual0，目录已精确删除。

本轮只写所属两份production／test路径及独占证据目录，没有修改package.json、native、bootstrap本体、scripts、Core、Frontend、四份主文档或Git。Root协调packaging新增physical副本与mandatory SHA、实际packed Core gate，然后对新包独立正常GUI复测；Goal保持未完成。
