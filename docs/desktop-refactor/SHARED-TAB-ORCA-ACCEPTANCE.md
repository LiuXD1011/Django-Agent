# 共享标签页账号交接的 Orca 实际复验

2026-10-13，Root 在 Orca 内置浏览器同一新隔离 profile 的两页中，实际注册 A、创建 A 私有库，再从 B 页注册另一个账号。B 提交后没有手动刷新或导航旧 A 页；两页自动进入 B 的知识库列表，A 私有内容不可见。只读服务端身份与本地低敏缓存均为 B，A 的一次性交接记录已消费。[实际验收摘要](../refactor-evidence/20261013-root-shared-tab-orca/acceptance.json)、[65份原始证据冻结](../refactor-evidence/20261013-root-shared-tab-orca/freeze.json) SHA `4f8385ac5a15e92349e97a7c9cfddd3e30e581f2afa89e6afea5c2766b743343`。

这是 CD-15 修复后的一个自然鼠标样本，没有人为延迟业务模块。先前故意制造 listener 尚未安装时的事件丢失，以及 RED/GREEN 原三项 Playwright 认证结果，继续分别以[生产修复专项](SHARED-TAB-AUTH-FIX.md)和[历史协议失败](AUTH-E2E-PROTOCOL-ACCEPTANCE.md)为准。本次没有观测或证明自然样本必然发生 missed-event，不替代自然过期、迟到 refresh、完整权限或正式 Windows IPC 认证。

## 前置条件与实际操作

链路为同一真实 TypeScript Core 的 Vue HTTP 测试入口 `http://127.0.0.1:4180`，核心端口8180，生产 auth transport SHA `f0fe75466a593c282c8b30d99c245a87b03e04093f4ad796dbd8a2d9fc59abfb`。数据目录 `/tmp/marlin-auth-e2e-rSfVxq/data` 是本轮新建空数据，两个合成账号使用正常注册；没有预置 token、绕过认证或使用模型配置。[启动与来源](../refactor-evidence/20261013-root-shared-tab-orca/environment-start.json)。这是浏览器开发/测试链路，不能当作安装版交付版本证明。

两页共享 profile `ca135ec0-9162-4866-8205-cda36de49368`：A 为 `7fcd3a18-220a-4183-927d-d06c23c66416`，B 为 `33677510-4043-401d-9072-76283753258a`。Root 通过真实表单输入与 `mouse move/down/up` 操作，eval 只读坐标、页面身份和真实 `GET auth/me`，没有用 DOM 点击、Vue 调用、路由赋值或认证写入代替业务操作。

| 操作与预期 | 实际结果及证据 |
| --- | --- |
| A 打开注册表单、填写专门邮箱及密码，鼠标提交 | 004–014实际鼠标与输入；[015新状态](../refactor-evidence/20261013-root-shared-tab-orca/015-a-platform.json)进入platform，显示 `orca-handoff-a-20261013`、0库 |
| A 创建私有知识库作为隔离资料 | 017–029实际打开、填写并提交；[030新状态](../refactor-evidence/20261013-root-shared-tab-orca/030-a-private-library.json)显示“A私有库 Handoff QA 20261013”、1库、0条目/摘录/处理中 |
| 同一profile新开B登录页，正常注册B | 035–045实际鼠标与表单；[046B新状态](../refactor-evidence/20261013-root-shared-tab-orca/046-b-new-account.json)自动进入platform，显示 `orca-handoff-b-20261013`、0库 |
| 不刷新或重新导航旧A，检查账号交接 | 045之后仅观察；[047旧A新状态](../refactor-evidence/20261013-root-shared-tab-orca/047-a-auto-new-account.json)也自动进入platform、身份B、A私有库不可见；Root实际查看[050稳定截图](../refactor-evidence/20261013-root-shared-tab-orca/050-a-restored-frame.png) |
| 验证服务端身份、缓存与凭据隔离 | [048A](../refactor-evidence/20261013-root-shared-tab-orca/048-a-server-proof.json)、[049B](../refactor-evidence/20261013-root-shared-tab-orca/049-b-server-proof.json)真实me200、server/cache均B；JS不能读取HttpOnly access/refresh，本地storage无这两类凭据，A交接marker已消费 |
| 确认A资料没有被删除来制造隔离成功 | [只读SQL补证](../refactor-evidence/20261013-root-shared-tab-orca/fixture-readonly-audit.json)：A私有库仍未删除、2用户、models/model_usage/model_rate_limit_state均0、FK0；不打开原Source数据库，不写夹具数据库 |

## 观察、错误与耗时边界

[023坐标观察](../refactor-evidence/20261013-root-shared-tab-orca/023-a-create-submit-bounds.json)得到约0.6×0.32按钮尺寸，未按此坐标点击。Root正常聚焦并查看[025弹窗PNG](../refactor-evidence/20261013-root-shared-tab-orca/025-a-kb-dialog-frame.png)后，[026](../refactor-evidence/20261013-root-shared-tab-orca/026-a-create-final-bounds.json)取得实际60×32尺寸，027–029才提交。此早期观察不计产品失败，也不当作一次成功点击。

初次只读审计夹具直接调用better-sqlite3，选中了需要GLIBC_2.33的预编译库，actual exit1且尚未查询。Root核查Core数据库接口后改用既有 `openNativeDatabase` 选择本机编译binding，补证命令chunk a7269d实际exit0；没有改产品或降低断言。[初始源码](../refactor-evidence/20261013-root-shared-tab-orca/fixture-audit-initial.source.txt)、[初始错误](../refactor-evidence/20261013-root-shared-tab-orca/fixture-audit-initial-tool-error.json)、[修正后只读助手](../refactor-evidence/20261013-root-shared-tab-orca/consumed-scripts/marlin-root-shared-tab-fixture-audit-20261013.mjs.source.txt)。

B注册请求的单次ResourceTiming为184.5ms；me只读验证观察为6.2/7.1/7.2ms。[原始网络观测](../refactor-evidence/20261013-root-shared-tab-orca/049-b-server-proof.json)。这些是HTTP往返，不能包装为完整UI交接、冷启动、P95或生产并发性能。002–052工具的操作/等待耗时也不作产品延迟。

## 清理与剩余验收

Root仅关闭[自有B页](../refactor-evidence/20261013-root-shared-tab-orca/051-close-b.json)和[自有A页](../refactor-evidence/20261013-root-shared-tab-orca/052-close-a.json)，随后删除自有profile并核列表已无该ID。经原生pidfd核helper2709679/startTicks25869628的exe/cwd/argv后，唯一SIGTERM正常停止；[停止请求](../refactor-evidence/20261013-root-shared-tab-orca/helper-stop-request.json)本身尚不声明终态，最终[acceptance](../refactor-evidence/20261013-root-shared-tab-orca/acceptance.json)取得session15069 actual exit0/chunk9eed79、Core close0、准确helper/Core PID消失、随机data/cache全部删除、4180/8180无监听。

两个合成用户和设备仅存在于已删除的随机数据中；私人口令文件已精确删除，Root检查所有公开文本不含两个secret。四份自有助手按SHA归档并精确消费删除，[清理回执](../refactor-evidence/20261013-root-shared-tab-orca/consumed-scripts/cleanup.json)保留。原main Source8000/5173仍未恢复，新验收服务也已清理；没有触碰真实管理员、Key、其他设备或模型，没有付费请求。

本轮完成“正常共享profile账号切换、旧私有内容消失、真实身份一致”的Orca子项；A整组仍partial。38组/69UI编号不变，只有M-01/M-02整组通过。整Orca进程重启、迟到refresh、完整权限、最新安装版认证及其他页面继续；历史6e/aabd包不含这次auth生产修复或后续知识库分类变化，须另做最新源码检查与正式打包。旧b99 checkpoint和原失败不改写，Goal保持active。
