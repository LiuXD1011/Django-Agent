# 密码与登录表单错误文案只读审查

日期：2026-10-10。审查对象为当前工作区源码，而非 HEAD。本报告记录最初只读审查及后续 root 网络证据补充；该只读阶段没有修改源码、运行测试或构建、操作 GUI、调用模型或读取用户数据库。后续已授权的隔离副本文案验证记录单独保存在副本中，产品源码与安装生命周期仍冻结。

结论：建议在 `Settings.vue` 的密码提交 catch 中，仅按两个已存在的密码错误码显示中文；在 `Login.vue` 普通登录提交 catch 中，仅映射 `invalid_credentials`。两处分别保留当前未知错误消息提取顺序。认证、会话撤销、自动刷新及提交次数均无需改变。此建议尚未实施或验证通过。

## 已确认的问题

**P2：当前密码错误时，中文密码弹窗显示英文。** 触发条件是当前密码不正确、新密码及确认值一致且非空。root 在自建专用账号的实际 Orca 页面操作已观察到 `Old password mismatch`；本轮安全核对原始 receipt 的 `/after_observation/result/snapshot` 确实包含该文案。receipt 标明 `credential_value_emitted=false`、`paid_model_calls=0`，本报告不复制输入值。

原始证据：[20261010-root-orca-owned-field-67bd1232-f71c-41d5-83ef-e3987d535274.json](20261010-root-orca-owned-field-67bd1232-f71c-41d5-83ef-e3987d535274.json)，9696 bytes，SHA-256 `e749970b4c3285c890b864a7a4b60468d290846b7054c122a72f0703ef1aed40`。该 GUI 证据由 root 执行；本轮没有重复 GUI 用例。

实际链路如下：

1. [Settings.vue:473](../../frontend/src/views/Settings.vue#L473) 已用中文检查三个空值及两次新密码是否一致。通过后调用 `auth.changePassword`。
2. [auth.ts:113](../../frontend/src/stores/auth.ts#L113) 调用真实 API，明确传入 `skipAuthRefresh: true` 和当前会话 generation；失败向组件传播，成功才清除本地会话。
3. [api/index.ts:231](../../frontend/src/api/index.ts#L231) 请求 `POST /api/v1/auth/change-password`。[application.ts:314](../../packages/core/src/application.ts#L314) 先获得真实认证上下文，再调用认证服务。
4. [auth/index.ts:233](../../packages/core/src/auth/index.ts#L233) 抛出 HTTP 400 `old_password_mismatch`，message 为 `Old password mismatch`。密码修改和设备撤销在此检查之后，位于同一事务。
5. [application.ts:113](../../packages/core/src/application.ts#L113) 返回 `{ success: false, message, error: { code, message, details: {} } }`。[client.ts:54](../../frontend/src/api/client.ts#L54) 将响应 body 和 status 组成拒绝值，所以组件实际读取应用错误码应使用 `e.error.code`。
6. [Settings.vue:495](../../frontend/src/views/Settings.vue#L495) 目前直接采用 `e.error.message`，再依次尝试 `e.message`、`e.response.data.message` 和通用中文失败提示。模板 [Settings.vue:975](../../frontend/src/views/Settings.vue#L975) 将其显示在 `role="alert"` 中。

桌面也保留同一错误 body：[desktop-transport.mjs](../../frontend/src/api/desktop-transport.mjs) 将 IPC body 转为响应，再由桌面 Axios adapter 交给同一 client 拦截器；[adapters/ipc.ts](../../packages/core/src/adapters/ipc.ts) 使用同一 `errorResponse`。已核对安装的 Axios 类型 `AxiosError.response.data` 与 `AxiosError.code`：顶层 Axios code 是传输分类，例如 `ERR_BAD_REQUEST`，不能作为密码业务码进行映射。此问题属于局部文案问题，未发现错误密码被接受的证据。

## 最小修复建议

仅修改 `Settings.vue` 密码 catch，并增加对应 `Settings.behavior.test.mjs` 用例；不改通用 client、auth store、core 认证服务或其他设置表单。先精确匹配 `e?.error?.code`，再沿用目前的消息 fallback。不通过英文消息内容或所有 400 状态推断“当前密码错误”。

| 实际错误码 | 建议中文提示 | 依据 |
| --- | --- | --- |
| `old_password_mismatch` | 当前密码不正确 | 已确认实际 GUI 缺陷；与现有表单测试中文一致 |
| `invalid_password` | 新密码不能为空或过长，请重新输入 | `changePassword` 调用现有新密码校验；同范围的另一个英文错误路径 |
| 未知码、无码或传输错误 | 保留原 `e.error.message` → `e.message` → `e.response.data.message` → `密码修改失败，请重试` | 避免遮蔽具体服务消息及登录状态提示 |

上述两个 400 验证失败时保持弹窗、新密码值和当前会话既有行为，不新增重试、不显示成功提示、不跳转登录页；成功时仍清空三个密码、提示全部设备退出、跳转登录页。输入时清除旧提示及关闭/重开时清空敏感字段的行为已存在，保持原样。其他状态的既有会话处理不改变。

**值得同范围处理的直接相关问题：`invalid_password` 也会显示英文且可能误导。** [auth/index.ts:137](../../packages/core/src/auth/index.ts#L137) 实际规则是 string、非空、JS `length <= 4096`；同一个码的原文 `Password is required` 也覆盖过长密码。前端目前只检查非空与一致，因此 4097 个 ASCII 字符的新密码可到达该服务分支。上述中文同时覆盖空值和过长，不擅自增加最小长度、强度规则、trim 或截断。4096 是 UTF-16 单元界限，不能凭猜测将规则替换成“至少 8 个字符”。本轮仅从真实源码确认此路径，未执行该请求或 GUI。

没有建议扩大到整个 Settings 错误框架，也没有发现需要在此次局部修复中改变的其他认证行为。确认密码由前端校验，当前 core 修改密码接口没有独立的 `confirm_password` 错误码，不新增虚构映射。

## 现有测试为何漏掉，以及后续回归

已完整阅读 [Settings.behavior.test.mjs](../../frontend/src/views/Settings.behavior.test.mjs)：它执行真实 Vue SFC 编译出的 setup 和 Vue ref，API/store 边界用夹具替代。[第 16 行](../../frontend/src/views/Settings.behavior.test.mjs#L16) 的默认失败夹具只有中文 `error.message='当前密码不正确'`，没有真实 code；[第 108 行](../../frontend/src/views/Settings.behavior.test.mjs#L108) 用该夹具断言中文。因此现有测试没有覆盖真实英文响应经业务码本地化的要求。它没有渲染弹窗 DOM，不能称为实际点击验收。

解除冻结后，建议先按当前真实 body 形状写 RED，再实现上述局部映射：

| 稳定用例编号 | 输入/响应 | 必须断言 |
| --- | --- | --- |
| PWD-UI-01 | 合法表单，400 `{error:{code:'old_password_mismatch',message:'Old password mismatch'}}` | 中文“当前密码不正确”；弹窗保留、saving 结束、恰一次调用、无成功提示或跳转 |
| PWD-UI-02 | 一致且过长的新密码，400 `{error:{code:'invalid_password',message:'Password is required'}}` | 中文新密码提示；不截断、不重试、不更改认证策略 |
| PWD-UI-03 | 未知 code 携带具体安全消息，或无码 `Error` | 原消息继续显示，不映射为密码不正确 |
| PWD-UI-04 | 无可用消息的错误 | 显示“密码修改失败，请重试” |
| PWD-UI-05 | 现有空值、不一致、pending 重复点击/关闭及成功场景 | 现有字段提示、零/单次调用、关闭与清空、成功退出提示及登录导航均保留 |

相关既有认证覆盖已完整读过，但本轮未运行：[auth-guard.test.mjs:272](../../frontend/src/router/auth-guard.test.mjs#L272) 验证成功才清会话、验证失败保留会话、迟到响应不能结束更新登录；[client.behavior.test.mjs:13](../../frontend/src/api/client.behavior.test.mjs#L13) 验证 Cookie mutation 内的 401 不递归刷新；[core/test/auth.test.ts](../../packages/core/test/auth.test.ts) 验证改密后所有该用户设备及旧 token 撤销，其他用户不受影响。实施后按规则运行相关回归，并在 `frontend` 目录运行完整 `npm run test:unit`；如需更新正式交付产物，再按 root 的冻结与构建流程处理。GUI 复测只由 root 协调，不以单测代替。

## 已确认的普通登录文案问题与最小计划

**P2：普通登录被正确拒绝时，中文登录页显示英文 `Invalid credentials`。** root 已在重新登录后确认第二次改密请求确实得到 200，数据库新密码有效、旧密码无效，两个设备都记录为 `password_changed`。随后 root 使用旧密码在登录页点击登录，被拒绝但看到英文。上述改密与数据库结果是 root 回报的实际事实；本轮没有查询该用户数据。首次改密提交的根因仍未知，不被后续成功事实覆盖。

登录原始 receipt：[20261010-root-orca-owned-field-525fdfca-c21d-4488-aaf5-5ececc13d337.json](20261010-root-orca-owned-field-525fdfca-c21d-4488-aaf5-5ececc13d337.json)，3219 bytes，SHA-256 `a9275a05c5e6069f73c5df775d3a200290ab366ef2979f5e114b30876538c09b`。已安全核对 `/after_observation/result/snapshot` 包含 `Invalid credentials`，且 `credential_value_emitted=false`、`paid_model_calls=0`；没有复制输入值或重复执行登录。

已完整阅读 [Login.vue](../../frontend/src/views/Login.vue) 的全部 130 行及 [Login.behavior.test.mjs](../../frontend/src/views/Login.behavior.test.mjs)。实际链路为普通 `submit` 调用 `auth.login` → store 的 `authenticate('login')` → `api.login` → `AuthService.login`。[auth/index.ts:162](../../packages/core/src/auth/index.ts#L162) 对不存在/停用账号、密码不符及无法使用当前空间的登录统一抛出 401 `invalid_credentials`，message 为 `Invalid credentials`；只有通过校验才创建会话。仍经上述 `errorResponse` 和 client 规范化，应用错误码在 `e.error.code`。

[Login.vue:45](../../frontend/src/views/Login.vue#L45) 目前直接采用 `e.message || e.error.message || '登录失败'`；这里顶层 message 和嵌套 message 都是相同英文，所以 [Login.vue:114](../../frontend/src/views/Login.vue#L114) 的 `t-alert` 显示英文。不能把所有 401 翻译为密码错误，也不依据返回消息包含某个英文词进行推断。

新增实施范围仅为 `Login.vue` 的普通登录 catch 与 `Login.behavior.test.mjs`：在非注册、非初始化的普通登录分支精确匹配 `e?.error?.code === 'invalid_credentials'`，提示 **“邮箱或密码错误”**。这与现有失败测试的中文一致，继续使用概括文案，不透露账号是否存在或停用、也不区分邮箱与密码哪个不正确。除此以外沿用登录页自己的原顺序 `e.message` → `e.error.message` → `登录失败`；与 Settings 的 fallback 顺序不混用。

不修改 `SETUP_ERROR_MESSAGES`、`quickStart`、注册/初始化分支、密码匹配检查、loading 防重复提交、登录后的工作台导航、认证 generation、会话操作锁、存储或凭据处理。登录失败仍留在当前页，恰一次请求、无工作台导航；有效登录继续走当前成功路径。无需通用错误模块或 auth/core 修改。

当前 `Login.behavior.test.mjs` 的普通登录失败用例同样采用无业务 code 的中文夹具 `{message:'邮箱或密码错误'}`，只证明中文原消息可展示；没有覆盖实际 `invalid_credentials` 英文 body 经本地映射的行为。其网络/未知错误用例属于 `quickStart`，不能替代普通 `submit` 的 fallback 回归。它执行真实 SFC 编译 setup，但没有实际 DOM/按钮操作。

解除冻结后在相同文件内先写以下 RED，再最小实现；保留原有初始化和注册测试：

| 稳定用例编号 | 输入/响应 | 必须断言 |
| --- | --- | --- |
| LOGIN-UI-01 | 普通登录，401 `{message:'Invalid credentials',error:{code:'invalid_credentials',message:'Invalid credentials'}}` | 显示“邮箱或密码错误”；loading 结束、恰一次登录调用、不导航、不重试 |
| LOGIN-UI-02 | 普通登录，未知业务码或无码错误，分别提供顶层/嵌套具体消息 | 保留原顺序及具体消息，不误报密码错误 |
| LOGIN-UI-03 | 普通登录，没有可用消息 | 显示“登录失败” |
| LOGIN-UI-04 | 已有正常成功、pending Enter+点击、注册确认密码、管理员初始化及 quickStart 场景 | 调用次数、成功导航、匹配检查、现有初始化文案及凭据边界原样保留 |

已知码测试必须让原始顶层与嵌套英文消息同时存在，防止仍优先读取顶层 message 而绕过映射。后续相关回归与完整前端单测需实际运行；本轮没有运行它们。root 正在执行新密码真实登录，本报告不预先声明其结果。

## 首次改密提交的网络事实与根因边界

初次审查时，root 已确认数据库密码及 devices 未变、后来旧密码登录成功，以及导航 `/login`；当时尚未找到原始 HTTP 401 证据。这是当时的观察范围，保留该历史事实。

后续 root 找到跨导航保留的 typed Orca network 历史，并保存安全摘要：[20261010-root-orca-safe-auth-network-697dad55-1d75-4fc7-ba1d-c529df74ac91.json](20261010-root-orca-safe-auth-network-697dad55-1d75-4fc7-ba1d-c529df74ac91.json)，7105 bytes，SHA-256 `0196aba83eddb6446661c81720b787f64bda512e9bf60300b438129271afebf8`。本轮已只读核对其中路径、方法、状态与时间戳：首次 `POST /api/v1/auth/change-password` 确实为 **401 / timestamp 1791639906896**；后续改密为 **200 / 1791640320341**，旧密码登录为 **401 / 1791640379677**，新密码登录为 **200 / 1791640424439**。摘要标明没有输出 headers、body 或 cookies 值，辅助提取请求的付费模型调用为 0。后续改密的数据库变化由 root 单独核对；网络状态本身不替代数据库或业务结果验证。

现在可以确认首次改密请求返回 401，但不能仅凭该状态断定是 access 自然过期或其他认证失效原因；根因仍由独立认证审查核实。root 还报告设备撤销有真实 DELETE 401、目标独立 me 仍为 200，这不纳入四文件中文文案补丁。

[client.ts:34](../../frontend/src/api/client.ts#L34) 在当前 generation 的 `skipAuthRefresh` 请求得到 401 时，会结束本地会话并导航登录，而组件改密成功路径并未执行。该分支已有防止 Cookie 锁内刷新死锁与会话竞争的测试。已确认的 401 与该客户端分支相符，但不证明其服务器侧原因；不建议在此次文案补丁中删 `skipAuthRefresh`、自动重发改密、修改会话围栏或将 `unauthorized` 翻译成密码错误。

## 本轮源码快照与验证限度

| 文件 | SHA-256 |
| --- | --- |
| `frontend/src/views/Settings.vue` | `d65a2ff9262be9dd5a7ca9ebd624ddbf13f7a5f88c7e7f082edce770ac869390` |
| `frontend/src/views/Settings.behavior.test.mjs` | `8b6165f2447085aad178d6bba865d3b76a098d22f51adbbd8b64fd7901600748` |
| `frontend/src/views/Login.vue` | `39f0d8fb04fa6aa6485b1d918f449f6187062b5fb2cc6549788f5a6a6be5e7cd` |
| `frontend/src/views/Login.behavior.test.mjs` | `35eda79b93f4490bf1107efee24b1aefb5bc96a76964d557ba91d9d596d3186a` |
| `frontend/src/api/client.ts` | `8fb1397992d92817ea0593bf6cef62461bb13f276fd88371d805818a7f5c92b4` |
| `frontend/src/stores/auth.ts` | `6b4bdd30b91b4d3aa75ec6426d336e0624b68d17bee382f12beea3bd9b8bbecd` |
| `packages/core/src/auth/index.ts` | `94720753c4d47edb4dde3bfa9f99467000b54c2a027e9c9f5f3b9777ef0d89ff` |
| `packages/core/src/application.ts` | `9d3bf76ed26e169f09cda55662bd44f25e4e9516b0ba19556f60506380f3ee42` |

本轮已完整读 Settings、Login、上述实际传输/认证链路及对应现有测试，核对安装的 Axios 类型和两个原始 receipt 的安全摘要；只做文档链接/差异和源码哈希复核。没有新增源码、测试或构建运行，也没有安装、GUI 操作、付费重放或秘密输出。该报告是修复建议，等待 root 释放产品源码冻结后才可实施。
