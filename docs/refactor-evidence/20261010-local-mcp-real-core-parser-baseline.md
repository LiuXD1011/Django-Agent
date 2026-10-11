# 真实本地 MCP 与生产 TS Core 集成验收（2026-10-10）

本轮实际结果 **verified，23 项检查通过，exit 0**。使用官方 SDK 1.32.1 的 root-owned Linux fixture `http://127.0.0.1:44702/mcp`，生产已编译 TS CoreApplication、CoreIpcAdapter、IntegrationService 与实际 Node HTTP fetch；服务、客户端和 transport 均未 mock。没有操作 GUI、执行 Agent 模型或读取 root / 用户数据库、密码、Key，也没有停止 root 的 fixture 服务。

[机器证据 JSON](20261010-local-mcp-real-core-parser-baseline.json) SHA256：`0d8410b458cb990565ac67faa3656701fbe03900e6630aa3fd29b41846e0d19d`。

## 实际认证与路由

独占 `/dev/shm/marlin-real-mcp-core-parser-baseline-20261010-*` 临时目录，0700 权限及唯一 owner marker；全新真实 SQLite。随机私有测试账户通过正式 CoreIpcAdapter 注册、登录，实际 user/tenant 所有权正确；创建自己的无 API Key MCP provider，正常 catalog 仅包含该 provider。直接工具调用的 ctx 来自同账户真实 AuthService.login → authenticateAccess，不构造 AuthContext、修改用户角色或提升系统管理员，个人空间 owner 按正常权限执行。

| 正式 Core 路由 | 实际结果 |
| --- | --- |
| POST `/api/v1/auth/register` | 200 |
| POST `/api/v1/auth/login` | 200，public auth_mode=ipc |
| POST `/api/v1/mcp-services` | 200，无凭据配置 |
| GET `/api/v1/mcp-services` | 200，仅自己的 provider |
| GET `/api/v1/mcp-services/:id/tools` | 200，connected，两个工具及 untrusted=true |
| POST `/api/v1/mcp-services/:id/test` | 200，connected，tool_count=2，此时未调用任何工具 |
| DELETE 自己的 provider | 200，实际 scoped tombstone |
| GET 已删除 provider | 404，provider_not_found |

这是实际正式 Core 路由调用；未启动额外 Core HTTP listener，不把本次私有 adapter runner 当作 Electron renderer 或 GUI 验收。

## 官方协议与两次真实工具

发现结果检查了实际 inputSchema：加法两个 required integer、±1,000,000 边界；echo required string、maxLength=1024；两者 additionalProperties=false。readOnlyHint=true、destructiveHint=false、idempotentHint=true、openWorldHint=false 全部保留。服务工具返回未显式携带 isError 时，Core 按生产合同提供 isError=false，原 wire 事实和 Core 结果分别保存，未伪造错误分支测试。

| 真正执行 | content | structuredContent | Core isError / untrusted | 本次耗时 |
| --- | --- | --- | --- | --- |
| `qa_add({a:20,b:22})`，恰一次 | text `42` | `{sum:42}` | false / true | 49.344 ms |
| `qa_echo({text:'MCP-QA 中文 😀'})`，恰一次 | 原样中文及非 BMP 😀 | `{text:'MCP-QA 中文 😀'}` | false / true | 56.953 ms |

透明网络观察器调用真正原生 fetch，仅允许固定 fixture `/mcp` 地址与 GET/POST/DELETE；不改变任何服务或协议响应，不采集认证 headers。实际观察 initialize=4、notifications/initialized=4、tools/list=2、tools/call=2；四个生产 session 均发送 DELETE 并取得成功状态，随后四次真实 GET 携带旧 session header 全部 404，证明终止后不能复用。session ID 仅以内存处理和 SHA256 摘要留证，不输出原值。

两次工具前无模型、无 model_usage，完成后实际 model_usage 仍为 0。network_denied_outside_fixture=0，paid_model_calls=0；没有额外工具、自动工具 retry 或厂商请求。

## 脚本纠正、源身份与清理

初期临时 runner 的两次运行止于 provider 创建后的严格类型断言：实际创建 route 已返回 200，但 tenant_id 的普通 row DTO 是安全数值 `1`，真实 AuthContext tenantId 是十进制字符串 `'1'`。将 runner 比较改为 `String(saved.tenant_id) === context.tenantId`，精确保留实际租户相等条件；未改变产品、数据类型或权限。两次失败均 **0 MCP 网络、0 工具**，各自 app.close 与临时数据删除成功。原始失败证据 SHA `3662777556a708a6aca4c3cc2170c63ace6be9717a302d66b35de58d7e82e210` 及完整安全失败 metadata 已嵌入最终 JSON 的 `prior_pre_network_runner_failures`，不把它们计作协议通过。

真实 runner 的 command：

```sh
node --check /tmp/marlin-real-mcp-core-parser-baseline-20261010.cjs
TMPDIR=/dev/shm node /tmp/marlin-real-mcp-core-parser-baseline-20261010.cjs
```

实际 Node v22.23.2 / Linux，最终运行总耗时 3681.308 ms；这是私有 tmpfs fixture 的测试耗时，不能当作 Windows/GUI/真实磁盘耐久或产品延迟结论。runner SHA `1a87675cb9f64f849382b067d3dd107c0869bc191f507ba1f87e5bca60303e74`，仅为一次性证据身份，任务结束删除。官方 SDK fixture 原脚本 SHA 保持 `119b82144b13172967ea1f7255099e99a1b3c27bd4d83818393c088ebbaa17bf`。

检查范围内八个生产 source/compiled 文件的实际 before/after SHA 全部一致，完整映射见 JSON。Core 正常 close 完成；私有 provider 正常删除；专属临时 SQLite、`.secrets`、所有 fixture 文件已清除，未触碰其它数据目录。临时 diagnosis JSON 和 runner 在证据核验后精确删除，没有修改产品、正式 stage、浏览器 QA DB、root provider 或服务器脚本。

本次结果只证明生产 Core 与真实受控 SDK fixture 的发现、连接测试、两个工具结果和 session 清理。GUI 配置/选择服务、Agent 真正调用工具和真实外部 MCP 服务仍是独立验收项，未记 PASS。
