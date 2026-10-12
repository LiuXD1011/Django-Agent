# 联网搜索 Provider 设置设计与实施计划

本设计基于 2026-10-12 的实际源码只读核查，随后经 Root 完整审阅并授权实施。Root 负责核心实现、真实 Orca 验收和最终 Windows 集成；本代理负责新增前端组件、父设置/API 接线及 MCP 编辑修复。最新检查范围与原失败保留在文末。

## 缺口与现有契约

- [Settings.vue](../../frontend/src/views/Settings.vue:820) 只列出四种类型和 `enabled/notes`，没有已保存服务列表、URL、API Key、编辑、默认选择或测试入口。
- [API 客户端](../../frontend/src/api/index.ts:290) 只有类型查询，没有 Provider CRUD 包装。
- [SettingsService](../../packages/core/src/settings/settings.ts:120) 已有真实租户范围 CRUD、软删除、加密凭据和配置状态投影；写入需要租户 owner/admin，普通读权限可查看安全投影。未知业务字段由现有 merge 保留。
- [实际注册路由](../../packages/core/src/adapters/settings-routes.ts:51) 的测试入口调用 `IntegrationService.testProvider`。不能依据 SettingsService 自身旧 `testProvider` 的 501 或 README 的历史说明判断当前注册入口不可用。
- [IntegrationService](../../packages/core/src/integrations/index.ts:282) 的搜索测试发送一次固定查询，返回 `{state,result_count}`；[网络层](../../packages/core/src/integrations/network.ts:25) 默认限制 5 秒，并保留取消、重定向与大小限制。
- [BuiltinToolRunner](../../packages/core/src/agents/tools.ts:127) 只选择当前租户 `status=active` 且未删除记录，按 `updated_at DESC,id` 取首项；没有读取 `web_search_config`。因此现页面的全局开关不控制实际工具，编辑任一服务会隐式改变默认服务。
- [Agent 执行入口](../../packages/core/src/agents/index.ts:67) 的每轮 `web_search_enabled` 授权继续保留。全局设置允许使用并不自动替用户开启本轮联网搜索，也不扩大 `web_fetch` 的权限。

## 选择与范围

推荐新增独立 `settings/WebSearchSettings.vue`，父 Settings 只接入该组件。直接将所有功能继续添加进 1320 行的父组件会扩大修改范围；仅添加 Provider CRUD 而沿用假的全局开关不能完成需求；新增另一套服务和凭据存储则重复现有安全契约。采用独立组件和现有核心 API。

仅支持已有 `duckduckgo/searxng/google/bing` 适配器，不增加厂商、后台服务、依赖、数据库表或迁移，不删除旧 Provider 数据及 opaque 配置。没有 `provider_id` 的旧配置保留原最近更新选择规则；明确 `enabled=false` 拒绝工具搜索。存在非空 `provider_id` 时只使用该 ID，无效、停用、删除、其他租户记录均不得回退到另一服务。

## 核心接口约定（Root 实现）

保持原 `GET/PUT /api/v1/tenants/kv/web-search-config` 外层 `{value:...}`，新增安全的非敏感选择字段：

```json
{"value":{"enabled":true,"provider_id":"当前租户实际 Provider UUID"}}
```

1. 保存时在原同步事务内验证 `enabled` 的布尔类型；非空 `provider_id` 必须为字符串，并精确匹配同租户 `web_search_providers/status=active/deleted_at IS NULL` 记录。保留其他现有字段和凭据 merge 行为。
2. 工具调用在原 `e.assert()` 后读取当前租户的设置；`enabled===false` 返回不可用且发出零搜索 HTTP 请求。
3. 非空选中 ID 按上述范围检查后使用；不受其他服务的更新时间影响。单 Provider 的 `enabled=false` 仍由现有 IntegrationService 拒绝。
4. 缺失或空 `provider_id` 沿用原有排序选择，不能因新 UI 默认值重写所有已有配置。非法非字符串 ID 不转换成另一个服务 ID。
5. 保留原当前身份重新授权、工具白名单、本轮显式启用、signal 和外部调用约束。测试按钮是管理员显式测试已保存的单服务，不自动开启全局或本轮搜索。

## 前端行为

组件独立加载类型目录、已保存服务列表、搜索 KV、`api.me()` 的安全身份投影。配置读取失败时显示错误和重试，并禁止把空默认值保存回服务器；不自动创建匿名服务，不发连接测试。

页面包含租户启用开关、默认服务选择和显式“保存搜索设置”，保留原备注字段；下方显示已配置服务卡片及“添加服务”。卡片展示名称、类型、非敏感 URL、启停状态、凭据是否配置、默认标记和编辑/测试/清除凭据/删除按钮。停用或删除当前默认服务后提示重新选择，不替用户切换到另一家。

新增/编辑使用响应式 TDesign 弹窗，字段为名称、类型、服务 URL、Google 搜索引擎 ID `cx`、API Key 和服务启用。仅提交可编辑字段，不把整个 GET 投影回写。新行 `status` 与启用状态一致；对旧 inactive 行，启用是明确用户操作，不在读取时激活。

| 类型 | URL / 字段 | 凭据 |
| --- | --- | --- |
| DuckDuckGo | URL 可留空，沿用实际适配器默认 HTML 地址 | 匿名，不要求 API Key |
| SearXNG | 必填 HTTP(S) 搜索 URL | API Key 可选 |
| Google | 必填 HTTP(S) URL 和 `cx` | 新服务需 API Key；编辑已配置凭据允许留空 |
| Bing | 必填明确兼容 URL；说明旧公共 API 已停用 | 新服务需 API Key；不填充已退役公共地址 |

URL 校验遵循现有核心规则：不接受用户名密码、query、fragment、反斜线或空白。不创造新的 provider URL 默认值。对已有未知类型显示原名称及未支持提示，不默默替换为 DuckDuckGo。

API Key 只使用 password 输入和组件内存，不回显已存值或 ciphertext，不写 local/session storage、日志或提示。编辑留空时 payload 省略 `api_key`，保留原凭据。关闭、保存成功或卸载清除临时密码；改类型清掉刚输入的临时 key。实际跨 origin 修改仍由核心 `credential_endpoint_changed` 拒绝，提示重新输入或先清除。

旧 `token` 或其他真实 credential_fields 不因新表单丢失。清除以实际字段名逐项确认，API Key 别名由现有 canonical 清除方法处理，token 必须明确清除 token，不能误报“凭据已清空”。删除需确认；清除、删除和测试均针对已保存 ID。

测试结果仅在显式 POST 完成后显示：`connected` 表示本次成功并显示结果数（0 也是合法成功）；`disabled/not_configured` 显示对应原因；失败显示核心错误，并允许用户再次点击。保存成功只称“已保存”，不称“已连接”，不自动测试或重试。

读取时显示服务和配置；写控件根据 `me()` 的当前租户 membership/personal owner/admin 安全投影提供只读提示。此提示不是授权依据，核心仍逐次校验。请求中保持 busy 和关闭限制，防止重复保存、误换目标或对已关闭表单显示迟到结果。

已完整核对实际安装 TDesign 1.20.2 的 `dialog/select/input/button` 类型：弹窗使用 `visible/confirmLoading/footer/attach/destroyOnClose/onClose/onClosed`，输入支持 `type=password/autocomplete/disabled`，选择支持 `options/modelValue/disabled`，按钮支持 `loading/type`；不猜测第三方组件属性。

## 文件归属与接线

本代理经 Root 授权后修改：

- 新增 `frontend/src/views/settings/WebSearchSettings.vue`，包含上述单一设置能力。
- 修改 `frontend/src/views/Settings.vue`：顶层导入并替换旧 websearch 分支；移除仅此分支使用的类型/KV加载和状态，避免父子重复读取。保留其他设置、导航和已有用户行为。
- 修改 `frontend/src/api/index.ts`：增加实际消费的 `listWebSearchProviders/createWebSearchProvider/updateWebSearchProvider/deleteWebSearchProvider/testWebSearchProvider/clearWebSearchProviderCredential`；ID 和字段用 `encodeURIComponent`。复用已有类型查询、租户 KV 和 `me`。
- 新增 `frontend/src/views/settings/web-search-settings.test.mjs`。

Root 独占 `packages/core/src/settings/settings.ts`、`packages/core/src/agents/tools.ts` 及必要新的核心回归。不要为前端新增假的 authority、SQL、秘密回显或第二种凭据存储。

## 回归与实施顺序

1. 先写 RED：测试实际编译父 Settings，切到联网搜索，确认能进入 Provider 管理；当前四类型占位卡不能满足新增/编辑入口断言。缺模块编译错误不算业务 RED。
2. 新组件实现前再保留实际编译 DOM 回归，API 仅用受控本地响应夹具；使用真实 Vue、TDesign 与 CSS、真实点击和网络方法/路径/body 断言，不用静态 regex 或复制业务函数验证。
3. 夹具覆盖以下独立业务断言：
   - 空列表显示添加和明确默认选择；创建 SearXNG 发送一次真实 POST，并呈现返回卡片，保存不发送 test 请求。
   - Google 的 URL/cx/key 必填、DuckDuckGo 匿名及 Bing 兼容 URL 提示；非法配置不发写请求。
   - 编辑已配置 key 输入保持空；空 key 的 PUT 不含 api_key，已有 opaque/token 未回写或删除；新增 key 只提交一次，关闭重开无残留。
   - 默认选择保存 `{value:{...保留配置,enabled,provider_id}}`；失败保留用户输入和错误，不假标记保存成功。
   - 显式测试一次 POST，分别显示 connected/0结果、disabled/not_configured、502失败；正在测试时防重复，保存不触发测试。
   - 清除指定 api_key/token 和删除都先确认；取消零请求，确认一次正确编码 DELETE，刷新真实配置状态；失败不先删除卡片或默认标记。
   - 403/读取失败只读与重试，不把未知服务配置写成空对象；页面和弹窗在 1440/1024/390 宽度可见且无横向裁切。
4. Root 核心 RED/GREEN 使用真实 Auth/SQLite、SettingsService、BuiltinToolRunner 与 IntegrationService+本地搜索 HTTP：选中旧 Provider 后编辑另一服务仍选中旧 ID；false 零外部请求；跨租户/停用/已删 ID 不 fallback；无选择保留原排序；真实凭据保留/清除和非敏感投影不回显。
5. 定向前端：`cd frontend && node --test src/views/settings/web-search-settings.test.mjs src/views/Settings.behavior.test.mjs src/views/Settings.layout.test.mjs src/views/settings/credentials.test.mjs src/api/index.cleanup.test.mjs`。记录真实 RED/GREEN、源 SHA 和日志。
6. 本轮 Goal 已授权完整前端检查：`cd frontend && npm run test:unit`，并执行 `npm run build`；Root 统一核心 typecheck/相关测试和源码冻结。没有依赖或锁文件变更，不提交。
7. Root 真 Orca 使用独立本地 SearXNG 协议夹具和合成 key 完成创建、默认选择、编辑保留 key、测试、停用、清除、取消/确认删除，并核当前租户设置与原四模型/key不变。外部真实搜索服务暂缺时不能将夹具当 vendor 通过。最终正式新版 Windows prepare/package/安装验收另行绑定新 freeze；46a 历史 prepare 失败不能冒充完成。

## 验收边界

前端隔离 Chromium 回归只证明实际编译页面和受控 API 边界行为；核心真实 Auth/SQLite/搜索适配器、Orca 以及 Windows 验收由 Root 单独记录。未调用厂商、真实用户模型或 GUI，也未生成最新版安装产物。最终成功需真实源码验证、GUI 和新的 Windows 包验收。

## 同轮 MCP 编辑修复（Root 已授权）

原设计 SHA `3c23cb937c9c7eaa3362bc657c295199ecb85dc2ecb812ddf1db7bc7af8600ea` 保留于原只读 validation，不覆盖历史。Root 实际 Orca [编辑观察](../refactor-evidence/20261012-mcp-real-agent/browser/026-mcp-edit-first-click-network-dom.json) 中 PUT 返回 400，原四模型和凭据未变。

已完整读 DTO、SettingsService merge、父 Settings。`editMcpService` 将整个 GET 投影展开到表单，包含 `credential_fields: {api_key:{configured:true}}`；保存再次展开，把这一状态树回传。现有 merge 递归访问 api_key，将对象当作秘密值拒绝，符合核心契约，问题在前端回写安全投影。

最小修改只在父组件：编辑表单明确取 `id/name/description/url/enabled`，api_key 恒为空；创建与编辑 payload 明确取 `name/description/url/enabled`，只在实际输入非空字符串时附加 api_key。id 只用于路径，credential_fields/status/tenant/timestamps/opaque 不回传，核心原 merge 保留旧扩展配置。保存中防重复、限制关闭，保存成功或关闭后清除临时 key；失败保留原表单供修正，不误报已保存。

新增同一 DOM 测试编译实际父组件和 API，提供完整 protected GET DTO，真实打开编辑并留空 key 保存，断言发送的 PUT 仅四字段。另验证新 key 单次提交、取消与重开无临时 key、错误保留表单。核心不放宽凭据类型规则，不删 credential_fields 投影。该原 GUI 失败仍保留，Root 之后真实重测。

## 已实施与当前验证

已经新增独立 WebSearchSettings、六个实际消费的 API 包装并替换原占位入口；父组件停止重复加载搜索类型/KV。MCP 编辑和写入均改为明确 allowlist，密码关闭/成功清除，保存中防重复并禁用编辑控件。原读取、导航及其他设置能力保留。

实际 DOM 回归另发现并修复两处边界：

- `base_url`-only 旧服务不能编辑时强转 `url`。表单记住实际生效字段，更新继续使用原字段，保留核心 host-change guard；真实 DOM 请求字段回归先 RED 后 GREEN。Root 另已独立证实核心跨 alias 风险，核心最小防护由 Root 所有，不能把前端字段保持当作核心漏洞已修复。
- 实际 TDesign 1.20.2 的旧关闭 `afterLeave` 会无条件清除复用实例 card 状态；快速保存重开出现无 editor 的真实失败。编辑弹窗改为可见时独立挂载，沿用已有模型思考弹窗模式；不增加固定 sleep 或强制动画。快速重开回归 GREEN。
- 旧 KV 缺 `enabled` 时核心保留允许行为；原新 UI 默认为未勾选，出现真实 `false != true` RED。现在只在读取投影中使用 `enabled !== false`，不自动保存或修改旧配置；回归在最终相关组通过。

检查日志位于 [独立实施证据目录](../refactor-evidence/20261012-web-search-provider-ui-implementation)：

- 初次 fixture 错误等待不存在的用户名，原 timeout 日志保留为 `initial-red.log`，不计业务 RED。已改为真实 me 响应 barrier。
- `business-red.log`：原搜索缺入口、MCP 回传 protected DTO 两项真实失败，0/2；`first-green.log`：2/2。
- `expanded-check.log`：8/10，保留快速重开真实失败和关闭后读取已卸载输入的夹具错误；后者改为 DOM 不含临时 key、重开为空，而非修改产品条件绕过。
- `endpoint-reopen-red.log`：两个专门失败；`endpoint-reopen-green.log`：3/3，包含 MCP 临时密码回归。
- `related.log`：27/27；随后 `default-flag-red.log`：1 项真实失败；`related-final.log`：28/28、0 fail/skip/cancel，TAP 总 duration `50677.034914 ms`。
- 首次完整前端 `frontend-full.log`：359/360，保留唯一 SEARCH-UI-06 失败。清除消息在重新加载完成前已出现，测试立即 count 了暂隐藏的卡片；只增加真实刷新卡片呈现等待，保留原 API Key=0、Token=1 和删除请求断言，没有固定 sleep 或扩大 timeout。
- 修正后 `related-final2.log`：28/28、0 fail/skip/cancel，TAP 总 duration `49144.567773 ms`。
- 完整前端 `frontend-full-final.log`：`npm run test:unit` exit 0，360/360、0 fail/skip/cancel，TAP 总 duration `114486.299607 ms`。
- `frontend-build.log`：`npm run build` exit 0，Vite 生产构建 41.87 秒；保留主 bundle 大于 500 kB 的既有构建警告，没有为此扩大改动。

上述测试数字为实际 TAP 总耗时，不是 GUI 延迟或 P95。构建时间为 Vite 记录的构建阶段，不混同命令墙钟。最终四个源文件 SHA 与执行前快照相同；[freeze.json](../refactor-evidence/20261012-web-search-provider-ui-implementation/freeze.json) 保存源、日志、精确 diff、来源 baseline、命令终态和验证边界。

所有新增测试编译实际父 Settings、实际 API 包装、实际 WebSearchSettings、Vue/TDesign 和应用 CSS。只有认证传输与无关设置子组件被隔离，所有 HTTP 方法/路径/payload 和可见结果来自真实组件操作。新增 13 项 DOM 回归不读取真实用户凭据、不中断任何核心或 Windows 应用。
