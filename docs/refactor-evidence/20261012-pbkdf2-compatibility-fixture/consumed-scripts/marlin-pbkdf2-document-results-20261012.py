from pathlib import Path
ROOT=Path('/home/liuxuedeng/Django-Agent');DOC=ROOT/'docs/desktop-refactor/PBKDF2-COMPATIBILITY-CHECK.md'
s=DOC.read_text();s=s.replace('Root 已认可方向；本阶段只有只读准备和合成向量，不改 repo 源码/测试。当前6e37产物绑定完成及允许新来源迭代的明确通知到达前，不执行修改。','先只读准备；随后Root明确6e37产物已绑定、允许新来源迭代，本专项已完成仅测试/静态fixture修改。历史6e37安装身份不改写，新测试不属于该旧包。')
s=s.replace('现认证测试文件SHA为`49faa356…`，生产 passwords SHA为`c610a951…`；精确值见','原认证测试文件SHA为`49faa356…`，现为`b5ca1994…`；生产 passwords 始终`c610a951…`，index始终`0ee2ffcc…`。原精确值见')
s=s.replace('- [ ] 等Root明确6e artifact绑定通过、允许新来源迭代。','- [x] Root明确6e artifact已绑定后授权；[解析完整receipt并核SHA3a21/verified_uninstalled](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/source-unlock.json)。初始raw cat超过工具输出上限，不称逐字完整审读manifest；历史receipt未改。')
s=s.replace('- [ ] RED：','- [x] RED：').replace('原兼容测试预期因实际`ModuleNotFoundError: django`失败','原兼容测试确因`ModuleNotFoundError: No module named django`失败').replace('- [ ] 最小GREEN：','- [x] 最小GREEN：').replace('- [ ] 同一无Django环境','- [x] 同一无Django环境').replace('- [ ] 复核diff/','- [x] 复核diff/')
s=s.replace('这份计划尚不是RED/GREEN执行结果；修改或检查失败均保留，Goal active。替换的是测试运行依赖，旧密码兼容能力、正常运行和历史双向Django实测证据不删除。','''## 实际结果与限制

原单项RED session37823 exit1，0/1、0skip、TAP2478.114ms，raw和[完整命令](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/red-original-no-django.execution.json)保留。初次修改auth全文件session46042为12/12、exit0；核心typecheck session70799 exit0。[初次完整auth](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-no-django.stdout.tap)、[核心类型](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/typecheck.execution.json)。

因核心tsconfig仅检查src，额外strict/noEmit测试文件检查发现既有preferences Json类型未缩窄，exit2/2诊断；原49faa源码临时副本在原117行重现相同2诊断，不是新增HMAC类型错误。仅在owned测试增加object/nonarray assert，原`enable_memory=false`断言保留；两份失败原样保存：[当前初次失败](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-test-typecheck.stdout.log)、[原基线同样失败](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-baseline-typecheck.stdout.log)。

最终稳定源auth session53595实际12/12、0skip、exit0，TAP26314.087ms；strict测试类型session45601 exit0/5621.515ms。其间测试与生产来源SHA前后完全相同，[终态auth TAP](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-final-no-django.stdout.tap)、[来源/命令](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-final-no-django.execution.json)、[测试类型终态](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-test-typecheck-green.execution.json)。相关auth-reader/discard/migration session23534为17/17、0skip、exit0，TAP8137.459ms，[相关raw](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-related-no-django.stdout.tap)。没有重复计为29个独立产品功能。

最终HMAC+原malformed/absolute用例9574.385ms，仅一次百万轮oracle、并行strict编译的隔离n=1测试成本，不是业务响应/P95。没有full suite/build/Windows/GUI/模型实测；本结果仅证明auth默认检查脱离Django，整个核心仍有必要Python解析/评测与AES-GCM兼容测试，旧Playwright auth入口未迁移。所有测试业务写入只在各自新临时SQLite夹具，finally清理；不触碰真实用户或source服务。

替换的是测试运行依赖，旧密码兼容能力、正常运行和历史双向Django实测证据不删除。自有helper按SHA归档删除；最终源码、diff和证据冻结交Root统一集成。Goal active。''')
DOC.write_text(s)
