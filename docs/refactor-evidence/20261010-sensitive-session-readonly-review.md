# 敏感操作 access 过期行为独立只读审查

日期：2026-10-10。审查者：auth_core 子代理。

范围：只读源码、已有脱敏证据和离线模拟单元测试。未操作 GUI、Windows、数据库或真实 API；未读取密码、token、digest、Cookie 值；未修改冻结源码、安装生命周期或依赖；没有厂商付费调用，也没有提交。

## 结论与证据边界

两次真实失败请求都发生在各自 access 到期后。当前敏感操作没有发送前续期，携带 `skipAuthRefresh` 的请求收到当前 generation 的 401 后，会立即清除前端登录并整页进入 `/login`。这是可确认的续期设计缺口；不能通过去掉 `skipAuthRefresh` 修复，因为敏感操作持有的 Cookie origin 锁与 `refresh()` 请求的是同一把锁。

以下时间均为 UTC，取自现有脱敏网络与数据库证据文件，独立审查未访问数据库：

| 事件 | 实际 access 到期 | 实际请求及状态 | 已过期时长 |
| --- | --- | --- | --- |
| 首次改密失败 | 13:42:35.020Z | POST change-password，13:45:06.896Z，401 | 2 分 31.876 秒 |
| 非当前第二设备撤销失败 | 14:03:38.516Z | DELETE devices，14:04:48.043Z，401 | 1 分 9.527 秒 |

撤销失败时当前 browser 的记录未被 revoked；独立第二设备随后 `GET me` 为 200。因此这次 UI 跳转不构成撤销成功，且与当前 browser 自然 access 过期后的拒绝路径一致。首次改密后的原设备最终撤销时间为后来成功改密的时间，不能倒推为首次 401 已写入密码。

证据文件：

- [脱敏网络状态与时间](20261010-root-orca-safe-auth-network-697dad55-1d75-4fc7-ba1d-c529df74ac91.json)：两次 401、后来改密 200、随后登录 401/200，以及撤销前 devices GET 200。
- [已有数据库只读到期观察](20261010-root-orca-sensitive-operation-expiry-db.json)：上述实际 access 到期与 revocation 时间。
- [第二设备仍有效](20261010-root-orca-other-device-observe-active.json)：失败撤销后独立设备 me 200。
- [真实确认点击及跳转](20261010-root-orca-owned-field-2d3cf855-ae69-4fc5-aff1-9498b73be2ff.json)：点击确认与跳转登录页；单独不能证明业务成功或 401 原因。

网络证据没有保存 Cookie、认证错误 body、完整 Set-Cookie 或 token 状态。到期证据没有包含 refresh 的 consumed、idle、absolute 状态；不能据此声称两次 refresh 必定可成功，也不能区分浏览器已删除到期 access Cookie与服务器收到过期 access。两种情况都会在当前服务器认证入口被拒绝。修复验收须单独证明“有效 refresh + 到期 access”可恢复，以及“无效 refresh”仍拒绝。

## 现有实现

完整阅读 DeviceSessions.vue、stores/auth.ts、auth-transport.mjs、client.ts 及对应 client、transport、router/store、device、Settings、storage 单元测试，并核对核心认证、HTTP Cookie 和应用认证分发。

| 位置 | 行为与影响 |
| --- | --- |
| [DeviceSessions.vue](../../frontend/src/views/settings/DeviceSessions.vue) revoke 35–40、logoutAll 55–59 | 持 Cookie origin 锁发送一次敏感请求，`skipAuthRefresh: true`；成功后 `check()`，再清理或刷新。没有访问会话预检或续期。 |
| [auth.ts](../../frontend/src/stores/auth.ts) changePassword 113–123 | 同样持锁、跳过响应式续期；仅确认成功后 invalidate。 |
| [client.ts](../../frontend/src/api/client.ts) 34–36 | 当前 generation 的 `skipAuthRefresh` 请求收到 401，立即 invalidate 并 `location.href='/login'`。 |
| [client.ts](../../frontend/src/api/client.ts) 38–50 | 普通请求收到 401，可 refresh 后重试一次。因此 devices GET 能正常工作，而稍后敏感 mutation 仍可能失败。 |
| [auth-transport.mjs](../../frontend/src/api/auth-transport.mjs) 112–123、126–158 | sessionOperation 与 refresh 共用 `personal-kb-refresh:<origin>` 锁；fallback Promise tail 也无法重入。refreshInFlight 可在锁取得前建立。 |
| [auth-transport.mjs](../../frontend/src/api/auth-transport.mjs) 70–99、133–149 | refresh 先核对 epoch，再 persist；persist 发现身份变化会递增 epoch，但已经替换本地身份。新的敏感预检须在授权发送 mutation 前校验预期身份，不能只依赖 persist 的事后变化。 |
| [auth.ts](../../frontend/src/stores/auth.ts) 50–56、58–87 | restore 有刷新路径，但已 restored 时不再验证；applySession 不保留 access_expires_at，页面长时间停留不会触发敏感操作前续期。 |
| [核心 auth](../../packages/core/src/auth/index.ts) 13、56–57、82–87、130、181–185 | device access TTL 10 分钟、idle 30 天、absolute 90 天；refresh 保持 stable device，轮换 access/refresh；access 过期由 authenticateAccess 拒绝。旧 bearer 的 8 小时有效期是不同模式。 |
| [HTTP adapter](../../packages/core/src/adapters/http.ts) 199–204 | access HttpOnly Cookie Expires 与核心 access 到期一致；仅登录/refresh 等 issue 响应设置新 Cookie。普通 me/devices 成功不延长 access。 |
| [application.ts](../../packages/core/src/application.ts) context 与 auth routes | change-password/logout-all/revoke 先从 access 建立 context，失败时不进入修改方法。普通 logout 有 refresh 撤销回退；不要无故把敏感操作续期方案套到该退出语义上。 |

refresh 会消费旧 refresh；消费后的重放会撤销 family。未知响应不能当成“没消费”，也不能盲目重试旧 refresh。device 列表 `expires_at` 是 idle 到期，`absolute_expires_at` 是最长到期，不是 10 分钟 access 到期；无需改变现有标签含义。

## 最小可验证修复建议，尚未实施

建议只在前端增加一个共享的“敏感操作前认证”入口，并让改密、撤销设备、退出所有设备使用它。服务器 TTL、refresh rotation、ACL、Cookie/CSRF 规则和普通 logout 语义保持现状。以下是待批准设计，不是已完成修复。

1. 用户确认时同步捕获 generation、mode、service/user/tenant 身份和已知 stable current device。保持现有 busy 防重复；未认证直接拒绝。
2. Cookie 模式只取得一次现有 origin 锁。在锁内重新核对 generation 与存储身份，不能只相信跨 tab 的 storage event 已处理。
3. 在发送 mutation 前进行只读认证预检。预检不得走会自动注销的 `skipAuthRefresh` Axios 401 分支，也不得走会自行再次获取锁的 `request()` 自动刷新路径。只在预检得到确定的 access 401 时调用内部“锁已持有”的刷新执行单元；成功后重新验证所选 tenant 的 me 身份，再决定是否发送 mutation。
4. 将现有 refresh 的网络轮换与 epoch/abort 校验提取为私有执行单元，公开 refresh 继续负责锁。私有执行单元必须拥有受限的锁持有证明或仅在该闭包内部调用，不能对组件暴露“跳过锁”的任意选项。不得在已持锁时调用公开 refresh；也不得 await 一个正在等待本锁的 refreshInFlight。共用 singleflight 需区分“已在本锁中执行”和“正在排队”，排队任务进锁后须重新检查当前有效会话，避免重复轮换。
5. 每个 await 后以及真正发送 mutation 前执行 generation 检查；预检和刷新返回的 user、service、tenant、stable device 必须符合原始 intent。不同用户绝不续接旧操作；刷新响应不可先 persist 新用户再把旧操作继续下去。刷新返回 primary tenant 与原选择不一致时，需在原选择 tenant 下重新 me 验证；禁止隐式切换操作 scope。
6. mutation 继续携带 `skipAuthRefresh: true` 和原 `_authGeneration`，最多发送一次。CSRF 与 headers 在锁内、续期之后读取；等待实际响应及 Cookie 处理结束后才释放锁。确认成功后继续现有 `check()` 再 invalidate 或 reload。

可使用 `access_expires_at` 作为内存中的到期提示，减少不必要预检或在马上过期时先续期，但本地时钟/缓存不是认证证明。预检 200 后如果仍在极窄边界过期，首次 mutation 的确定 401 可以安全停止并要求重新登录，不能为追求无感而自动重发 mutation。是否增加临近到期窗口应由测试证明确有必要，不能把延长 TTL、后台无限续期或新权限语义混入此修复。

“先公开 refresh，之后再取 mutation 锁”虽然避免重入，但单独这样做留下两次锁之间的跨 tab 换用户窗口；若采用此变体，必须在 mutation 锁内再次核对预期身份及服务端 me，因此不能作为省略身份围栏的简化。“在已有 sessionOperation 回调里直接 await refresh”会重入锁；“把 skipAuthRefresh 删掉”会在 401 响应拦截器中触发同一死锁，也改变一次 mutation 的发送语义，均不建议。

## 必须保留的围栏与未知结果

- generation：旧请求、排队请求、迟到响应不得复活已退出登录或清除新登录。
- 身份：service/user/tenant（以及已知 stable current device）须绑定原操作意图；存储变化不能成为替旧用户授权的凭据。跨 tab 事件仍保留。
- origin Cookie 锁：登录、刷新、退出和敏感操作共用，含响应 Cookie 处理；不得改成每个页面/每个 user 各一把锁。无 Web Locks 时现有 fallback 只保证同页，不能声称已解决跨 tab。
- refresh rotation：每次确定刷新只消费一次；无效/replayed/revoked refresh 不能恢复会话；unknown 响应不得自动重放旧 refresh。
- 修改请求：网络 timeout、断连、非 JSON 响应、未知服务器结果都不能自动重发；不显示未经确认的成功。可提示“操作结果尚未确认，请重新登录后核对”，撤销可显式重新读设备列表核对，改密不能靠自动再次提交核对。确定的密码校验 400 仍保留当前登录与原验证提示。
- 首次 mutation 的 401/403 不视为成功；只有当前 generation 的确定认证失效才影响当前登录。旧 generation 的迟到错误不得注销后来的登录。

## 验证结果与补充验收

仅运行离线模拟测试，没有真实 HTTP/IPC/数据库调用：

```sh
cd frontend
node --test src/api/client.behavior.test.mjs src/api/auth-transport.test.mjs src/router/auth-guard.test.mjs src/views/settings/device-sessions.test.mjs src/views/Settings.behavior.test.mjs src/stores/auth-storage.test.mjs
```

结果：53 tests，53 pass，0 fail，exit 0。现有 client 测试明确断言敏感 401 不进入 refresh、直接登录页；这是现状验证，不证明拟议修复。相关真实跨设备 E2E 文件还使用旧 Django `pkb_access/pkb_refresh` 名称，不能代替当前 Marlin Cookie 敏感操作验收；本审查没有运行这些 E2E。

冻结解除后，应先在隔离副本新增针对真实 client/transport/store/component 组合的离线回归，使用可推进时钟和真正串行的非重入锁模拟器；现有 client 测试锁回调立即运行，只能检查有没有第二次 lock 请求，不能覆盖真正排队死锁。最少覆盖：

| 用例 | 必须观察到的结果 |
| --- | --- |
| 三种敏感操作：access 到期、refresh 有效 | 同锁内预检/必要 refresh 完成，stable device 不变，首次 mutation 只发送一次并成功；撤销其他设备不退出当前设备。 |
| access 到期、refresh revoked/replayed/idle/absolute 到期 | 不发送 mutation；保持确定失效退出规则，不建立新用户会话。 |
| 已有 refresh 排在持有的敏感锁后；另 tab refresh 同时排队 | 完成而非死锁，轮换与 Set-Cookie 串行；不盲等锁后的 singleflight，不重复消费旧 refresh。 |
| 锁排队及预检期间 logout/new login/service/tenant 更换；跨 tab 事件尚未处理 | 旧操作在发送前拒绝；不同用户 mutation 为零；迟到结果不污染新身份。 |
| refresh 返回不同用户或不同 stable device | 不 persist 成可继续旧 intent 的会话，不发送 mutation；明确重新登录。 |
| 续期后 CSRF 更新；随后 mutation 成功/400/401 | 使用最新 CSRF；成功后既有清理规则，400 不注销，401 不自动重发。 |
| refresh 或 mutation timeout/unknown；mutation 已成功但响应丢失 | mutation 最多一次；unknown 不重放 token 或修改、不假报成功、不丢未提交本地草稿。 |
| 无 Web Locks | 同页依然无重入/死锁；跨 tab 保证边界明确，不虚构已提供跨 tab 串行。 |

最小拟议源文件范围：`frontend/src/api/auth-transport.mjs`（私有锁内执行/认证准备）、`frontend/src/stores/auth.ts`（改密调用）、`frontend/src/views/settings/DeviceSessions.vue`（两个敏感调用）；如让预检复用 Axios，则还须在 `client.ts` 明确区分预检 401 与 mutation 401，但低层预检可避免扩大拦截器语义。对应上述单元测试更新；只有未知结果提示需要调整时涉及 `Settings.vue`。不需要修改 core/auth、HTTP adapter、storage、依赖或安装产物。

此次新增文件只有本独立审查文档。正式源码仍冻结，未实施修复，也没有声称真实敏感操作已修复。
