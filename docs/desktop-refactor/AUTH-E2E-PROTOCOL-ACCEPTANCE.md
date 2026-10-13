# 原跨设备认证规格的 TS 协议复验

本轮Root在Goal恢复active后明确扩展了spec归属，只应用已审阅的协议补丁：7个 `pkb_access/pkb_refresh` Cookie字面量变为真实HTTP的 `marlin_access/marlin_refresh`，两处知识库创建状态201改为当前Core契约200，旧Django注释改为TS Core + Vue。生产HTTP、认证、配置/helper、依赖/lock均不改，不stage/reset/commit。Root独占Orca/native GUI，本轮只执行独立headless Playwright。

方案不添加Cookie兼容别名、不改生产返回状态、不删或skip断言。先保存原spec和完整diff，反向标准化这10处协议/注释变化必须逐字等于原spec，证明其他业务/安全断言未动。此前[启动器阶段](AUTH-E2E-TS-ENTRY.md)及[400d历史冻结](../refactor-evidence/20261013-auth-e2e-ts-entry/freeze.json)保持原字节，其原3FAIL仍是历史失败，不能改写。

计划：

- [x] 完整读当前spec/config/helper和原proposal，核SHA/独立4180、8180空闲与helper staged index，按原proposal应用允许的最小变化。
- [x] 用原启动器创建全新空Core数据/cache目录，真实跑原三项规格，无Django、模型或原用户资料；完整保存终态及失败。
- [x] 对原spec执行必要严格类型检查，不重复未变产品的361前端单测/Vitebuild。
- [x] 核helper/Core正常退出、独立端口无监听、原Source3833788代次保持、staged helper未动；检查diff/链接及原失败保护，临时助手精确归档删除。

原三项分别验证：两个独立Cookie jars正常UI注册/登录、390px上下文与共享KB/撤销A后B保持；同Cookie jar两个tab切换账号并清掉A私有内容/本地身份；移除access Cookie后用HttpOnly refresh恢复。保留无JS/localStorage凭据、两个设备ID不同、活动设备数、真实DELETE/URL/内容和本地身份等全部断言。用例结果仅属于程序化浏览器协议与认证链路，不冒充Orca真实mouse、自然600秒到期、迟到refresh或正式Windows IPC，更不标A整组/Goal完成。

## 实际结果与新问题

协议变化已严格采用旧proposal，反向标准化逐字等于原spec：7个Cookie字面量、2处创建状态与1条注释之外完全不变，3项test和所有expect/URL/数据断言保留。[实际最小diff](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/protocol-only.diff)、[修改前绑定及staged保护](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/before.json)。当前spec SHA `4ca3836fa53313a8edab826284bd006ce877ec4c5df1ef23036dd5f50e0d10a9`。

真实原三项运行session12211实际exit1，命令53881.299495ms，2PASS/1FAIL：

| 原规格 | 实际结果 |
| --- | --- |
| 两独立Cookie jars、桌面/390px、真实共享KB、撤销A而B继续登录 | 通过全部原断言，包括HttpOnly/不进JS及localStorage、不同device ID和两活动设备、DELETE200、A回login/B仍见原库 |
| 同Cookie jar两tab切换到新私有账号 | 失败：B正常注册进入platform后，原A页在spec:83继续停`/login`，5000ms内14次URL观察均未进入platform；其后身份/私有内容断言未执行，不标通过 |
| 移除access、HttpOnly refresh恢复并保持无JS refresh token | 通过全部原断言 |

原三项均实际执行，没有跳过、mock或放宽断言。[原始输出](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/spec.stdout.log)、[命令和退出](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/spec.json)。独立strict/noEmit规格类型检查session27666实际exit0、2727.408464ms。[严格类型](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/strict-types.json)。配置/helper及前端产品未改，没有重复既有361单测或Vitebuild。

只读诊断读取本轮新trace，公开白名单只保存25条path/method/status/time，未导出headers/Cookie/password/request或response body。A页在01:42:44.226Z GET `/login`200；B注册44.537Z开始、约45.023Z以200结束；A新document到45.549Z才请求auth store、45.649Z才请求auth transport，随后未请求me或platform。所选auth请求均200，没有厂商、权限401或后台错误证据。[公开时序](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/shared-tab-public-network.json)。

最可信解释是可丢失的跨document身份交接：`auth.ts` 的authenticate先invalidate并默认广播logout；transport的logout事件立即导航login。成功persist才发布一次identity storage事件，此时A新document的监听module可能尚未加载；公开login guard直接通过，Login组件也没有startup恢复，所以它停在login。这与实测时序一致，但未直接观测storage事件执行，保留为待Root修复核查的根因，不编造确定事件顺序或修改生产代码。[只读源码绑定](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/readonly-diagnostic-source.json)。应修交接的可恢复状态，不能删spec:83、延长等待掩盖或把login当新私有空间。

同次Core记录close code0/signalnull，helper/Core两个准确PID均已消失，随机data/cache移除，4180/8180无监听；外层Playwright exit1来自上述断言。没有单独取得helper退出码，不把PID消失推定为另一个实测exit0。原Source3833788/startTicks22088558仍在，未发signal/业务请求；没有Orca/native GUI、真实资料/模型或付费操作。[生命周期界限](../refactor-evidence/20261013-auth-e2e-protocol-acceptance/lifecycle.json)。本轮5份私有失败artifact单独保留，旧11份trace与400d旧38份证据均未变。

本轮仅完成已授权协议迁移和真实2/3复验，新共享页产品边界仍失败，已报告Root协调生产修复；不继续越过spec归属、不重放测试，不称全部E2E/A组/正式安装通过。Goal active。
