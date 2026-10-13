# PBKDF2 默认核心测试脱离 Django 的实施设计

2026-10-12。先只读准备；随后Root明确6e37产物已绑定、允许新来源迭代，本专项已完成仅测试/静态fixture修改。历史6e37安装身份不改写，新测试不属于该旧包。正常运行无 Django与原 `npm test:core` 中的测试依赖分别记录，不把测试环境缺模块称为生产认证缺陷。

## 范围与依据

完整读 [auth.test.ts](../../packages/core/test/auth.test.ts)、[passwords.ts](../../packages/core/src/auth/passwords.ts)、AuthService 与已安装 Django5.2.15 的 PBKDF2/SHA1 encode/verify、UTF-8 force_bytes、Node22.23.2实际 crypto 类型。原认证测试文件SHA为`49faa356…`，现为`b5ca1994…`；生产 passwords 始终`c610a951…`，index始终`0ee2ffcc…`。原精确值见[来源前置](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/source-before.json)。

只拥有 `packages/core/test/auth.test.ts`、新静态 `test/fixtures/django-pbkdf2.json` 及本专项/独立证据。生产 auth、依赖/lock、知识查询、主报告和构建目录不改；不接触真实账号/设备/密钥，不运行 GUI/厂商或已有 source 服务。旧[Playwright auth配置](../../frontend/playwright.auth.config.ts)第15行仍启动 Django，其真实两设备/共享页 spec 已完整读取，本次不混合迁移它。

## 选择

仅保留旧260000单向量会失去“新随机盐hash也符合跨语言格式”的检查。改另一 native PBKDF2 API较快，但容易与生产相同派生实现重合。采用可追溯 Django 黄金向量 + 测试私有 HMAC 递归/XOR oracle；oracle不调用生产 verify 或 pbkdf2Sync，低迭代黄金向量先校准它，再只对一个新1000000迭代hash作规范验证。分块输入、big-endian block编号和迭代异或按 [RFC8018 §5.2](https://www.rfc-editor.org/rfc/rfc8018.html#section-5.2)自行编写；当前两算法输出恰为一个PRF块，不扩大为通用加密库。

[已生成的候选](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/golden-candidate.json)全为公开合成密码/盐：原Unicode SHA256/260000哈希保持逐字节；SHA256/1 ASCII；SHA256/2组合字符、emoji和Unicode盐，预组合错误密码应拒绝；SHA256/1000000当前因子；旧SHA1/4096/NUL/Unicode。每个由实际Django encode并verify正确/错误密码，绑定三个安装源码SHA与生成脚本SHA；没有 Django setup/settings、数据库或账号调用。生成环境仍使用Django仅用于固定数据，不成为将来默认测试运行步骤。[真实生成记录](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/golden-generation.json)。

保留原旧hash真实AuthService.login、错误密码零签发、不悄悄重哈希；保留malformed编码、refresh absolute lifetime及所有其他认证断言。新随机hash明确核algorithm、1000000因子、18字节base64url盐、32字节标准base64派生结果，wrong拒绝及两次新盐不同。两盐不同只检查行为，不宣称测得安全熵。百万次HMAC增加测试CPU时间，会记录隔离样本耗时，不能当产品性能/P95。

## 执行步骤与门禁

- [x] 完整读受影响文件/实际依赖；Root认可只测试/静态fixture范围。
- [x] 合成黄金候选生成5条；无真实用户/凭据/API。
- [x] 确认 `/tmp/marlin-parser-isolation-20261010/bin/python` 是Python3.12.2且`find_spec('django') is None`，`-B -I`实际生效。[环境事实](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/no-django-environment.json)。不改全局PATH/系统Python。
- [x] Root明确6e artifact已绑定后授权；[解析完整receipt并核SHA3a21/verified_uninstalled](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/source-unlock.json)。初始raw cat超过工具输出上限，不称逐字完整审读manifest；历史receipt未改。
- [x] RED：在单次auth测试子进程env中仅前置该venv/bin，显式绝对Node+`--import tsx --test --test-name-pattern='^TS generated passwords verify with Django,' test/auth.test.ts`。原兼容测试确因`ModuleNotFoundError: No module named django`失败；保留完整raw和exit，不能以import缺本项目模块为RED。
- [x] 最小GREEN：复制已SHA绑定的静态candidate至新fixture；增加黄金验证与私有oracle；仅替换原动态Python验证代码，原其他断言保持。
- [x] 同一无Django环境运行完整原auth文件，再跑相关 auth-reader/discard、migration及核心typecheck；不提前扩大full suite、不并发写build/dist。生产 passwords/index 的SHA与前置精确比较。
- [x] 复核diff/静态fixture provenance、各日志命令/exit、源码SHA及仅自有temp助手清理；交Root最终统一核心/打包检查。

## 实际结果与限制

原单项RED session37823 exit1，0/1、0skip、TAP2478.114ms，raw和[完整命令](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/red-original-no-django.execution.json)保留。初次修改auth全文件session46042为12/12、exit0；核心typecheck session70799 exit0。[初次完整auth](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-no-django.stdout.tap)、[核心类型](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/typecheck.execution.json)。

因核心tsconfig仅检查src，额外strict/noEmit测试文件检查发现既有preferences Json类型未缩窄，exit2/2诊断；原49faa源码临时副本在原117行重现相同2诊断，不是新增HMAC类型错误。仅在owned测试增加object/nonarray assert，原`enable_memory=false`断言保留；两份失败原样保存：[当前初次失败](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-test-typecheck.stdout.log)、[原基线同样失败](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-baseline-typecheck.stdout.log)。

最终稳定源auth session53595实际12/12、0skip、exit0，TAP26314.087ms；strict测试类型session45601 exit0/5621.515ms。其间测试与生产来源SHA前后完全相同，[终态auth TAP](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-final-no-django.stdout.tap)、[来源/命令](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-auth-final-no-django.execution.json)、[测试类型终态](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/focused-test-typecheck-green.execution.json)。相关auth-reader/discard/migration session23534为17/17、0skip、exit0，TAP8137.459ms，[相关raw](../refactor-evidence/20261012-pbkdf2-compatibility-fixture/green-related-no-django.stdout.tap)。没有重复计为29个独立产品功能。

最终HMAC+原malformed/absolute用例9574.385ms，仅一次百万轮oracle、并行strict编译的隔离n=1测试成本，不是业务响应/P95。没有full suite/build/Windows/GUI/模型实测；本结果仅证明auth默认检查脱离Django，整个核心仍有必要Python解析/评测与AES-GCM兼容测试，旧Playwright auth入口未迁移。所有测试业务写入只在各自新临时SQLite夹具，finally清理；不触碰真实用户或source服务。

替换的是测试运行依赖，旧密码兼容能力、正常运行和历史双向Django实测证据不删除。自有helper按SHA归档删除；最终源码、diff和证据冻结交Root统一集成。Goal active。
