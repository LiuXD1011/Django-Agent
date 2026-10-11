# 本地 MCP GUI 验收准备（未启动）

2026-10-10，parser_worker。此次仅准备一个一次性真实官方 SDK 服务脚本；没有监听端口、运行 MCP 握手、调用模型、访问用户配置或操作 GUI。语法与未连接 SDK 注册检查不算 MCP 协议或产品 GUI 通过。生产源码与依赖未修改。

## 冻结脚本与依赖

- 临时脚本：[marlin-local-mcp-20261010.cjs](/tmp/marlin-local-mcp-20261010.cjs)。SHA256：`119b82144b13172967ea1f7255099e99a1b3c27bd4d83818393c088ebbaa17bf`。
- Node 实测版本 `v22.23.2`；使用现已安装的官方 `@modelcontextprotocol/sdk@1.32.1`、`zod@4.6.5`，不安装依赖。
- SDK 实际检查了 `McpServer.registerTool/connect/close`、`StreamableHTTPServerTransport.handleRequest` 与 session 回调的已安装类型。脚本通过 `createRequire(<core-root>/package.json)` 使用此 Core 目录的依赖，版本不匹配会拒绝启动。
- 参考已有真实协议 fixture：[integrations.test.ts](../../packages/core/test/integrations.test.ts:255)。新脚本使用官方高层 `McpServer` 和有状态 Streamable HTTP，工具回调是工具本身的实际实现，没有 mock MCP 客户端或传输。

服务仅绑定 `127.0.0.1`、端口 `0`，启动成功时打印 JSON `ready.url`（完整 `/mcp` 地址）与本进程 PID。不得把 Linux loopback 地址直接用于 Windows 原生应用：服务必须与实际 Core 在同一主机运行，或由 root 先明确受控网络方案；此脚本不增加远程监听。

只有两个工具：

| 工具 | 输入 | 实际返回 | 边界 |
| --- | --- | --- | --- |
| `qa_echo` | `{text:string}`，最多 1024 UTF-16 code units | text content 与 `{text}` structuredContent | 原样返回；拒额外字段 |
| `qa_add` | `{a:integer,b:integer}`，各在 ±1000000 内 | text sum 与 `{sum}` structuredContent | 纯整数加法；拒额外字段 |

两者声明 read-only、非 destructive、idempotent、非 open-world。不访问文件、DB、模型或外部网络。服务日志只打印固定协议方法、工具名和计数，不打印输入、请求头、凭据、session ID 或模型信息。

边界：仅 `/mcp` 的 GET/POST/DELETE；Host 必须等于实际 loopback authority，带 Origin 时须等于服务自己的 origin；无 CORS、无重定向、无认证密钥需求。POST 上限 16 KiB、session 上限 16、socket 上限 32，空闲 session 60 秒回收。SDK 支持真实 initialize、notifications/initialized、tools/list、tools/call 与 session DELETE。日志 `protocol_received` 是接收事实，不是请求成功证据；只有工具 handler 完成才打印 `tool_completed`。

## 由 root 决定启动时点

以下命令是后续执行说明，本轮未执行 `--start`：

```bash
node /tmp/marlin-local-mcp-20261010.cjs --start \
  --core-root /home/liuxuedeng/Django-Agent/packages/core \
  --lifetime-seconds 900
```

Windows 需先把这个相同 SHA 的脚本复制到 root 自有临时目录，使用明确的受控 Node 路径，`--core-root` 指向具有该版本官方 SDK/Zod 的实际独立 Core 目录。不应更改 formal payload 安装依赖或假设 ASAR 内依赖能被外部脚本直接解析。

保持启动终端或由 root 的 owned process supervisor 管理确切此子进程。POSIX 前台 Ctrl+C/SIGINT/SIGTERM 会关闭其 sessions、transport 和 sockets，最多 5 秒结束清理；达到 lifetime 自动关闭。Windows 控制台 Ctrl+C 可用；需要强制关闭时使用 root 已验证的 owned Job supervisor，而非按进程名/端口批量 kill。脚本不产生后代进程。最终 `closed` 只包含安全计数；root 应保存实际 receipt、返回结果和服务退出证据。完成后按上述 SHA 核对并删除精确临时脚本及 root 自有副本，不删除未知 fixture。

## 现有 GUI 与正式 Core 的实际路径

完整核对当前 Settings/ChatInput 模板以及对应 Core routes/SDK 调用，发现以下准确边界：

1. **GUI CRUD 可用**：设置 → MCP →「+ 添加服务」，名称填 `MCP QA parser-worker 20261010`；URL 填此次 `ready.url`；API Key 留空；描述填“本机受控 QA echo/add，无外部副作用”；保持启用后保存。刷新页面确认名称、描述、启用状态，编辑后再次刷新；删除只操作此唯一新 fixture。
2. **transport 默认**：当前表单无 transport 选择，保存不带该字段；Core 明确默认 `streamable_http`，与脚本一致。不要选 SSE URL 或依赖猜测的端口。
3. **设置页尚无发现/测试按钮**：[Settings.vue](../../frontend/src/views/Settings.vue:885) 只渲染添加/编辑/删除；[api/index.ts](../../frontend/src/api/index.ts:295) 也只有 MCP 四个 CRUD bindings。此轮不修改冻结 UI，不宣称能在该页点击发现或测试。正式 Core 已有下述认证路由，可独立验证；其结果不能当 GUI 点击通过。
4. **GUI 选择服务不调用模型**：进入新对话，Chat 会重新加载 MCP catalog；点输入栏的「MCP」按钮，选中此服务，确认 chip/勾选。不发送即可验证已保存配置进入正常 Chat UI。
5. **GUI 真正 tool call 会调用模型**：[ChatInput.vue](../../frontend/src/views/chat/components/ChatInput.vue:210) 提交固定 `agent_enabled:true` 和所选 `mcp_service_ids`；[AgentService](../../packages/core/src/agents/index.ts:71) 调用真实 SDK 发现，并向模型提供工具 schema，按模型返回的 tool call 调用集成。只有 root 在后续已授权模型阶段决定发送一次提示：“调用已选 MCP 服务的加法工具计算 20+22，并调用 echo 工具原样返回 MCP-QA 中文 😀，根据工具实际结果回答。”预期 sum 42 与准确 echo，但模型是否选择工具必须观察实际 `tool_completed` 和应用 tool result，不能仅看自然语言答案。
6. **付费边界**：CRUD、选服务、下述工具发现/连接测试和 trusted Core-only call 本身不需要模型。GUI Agent 完成一次工具任务通常需要工具选择与结果续答的多轮模型请求，可能更多（默认最多 8 轮以及应用正常后续处理），不承诺“一条消息等于一次计费”。0 模型配置的 BrowserQA 不能算 GUI tool call 成功，不搬 Windows 密钥、不重复发送 vendor 提示来凑结果。

正式 route/服务合同，全部保留真实认证和 tenant scope：

| 入口 | 真实结果及权限 | 是否模型 |
| --- | --- | --- |
| `POST /api/v1/mcp-services`，body `{name,url,description,api_key:'',enabled:true}` | settings provider 保存；admin | 否 |
| `GET /api/v1/mcp-services` | `{items,total}` public projection；read | 否 |
| `GET /api/v1/mcp-services/:id/tools` | `{state:'connected',tools:[{name,description,inputSchema,annotations}],untrusted:true}`；read | 否 |
| `POST /api/v1/mcp-services/:id/test`，body `{}` | `{state:'connected',tool_count:2}`；admin | 否 |
| trusted `IntegrationService.callMcpTool(ctx,id,'qa_add',{a:20,b:22},{timeoutMs:5000})` | `{state:'connected',content:[{type:'text',text:'42'}],structuredContent:{sum:42},isError:false,untrusted:true}`；admin | 否 |
| trusted `callMcpTool(ctx,id,'qa_echo',{text:'MCP-QA 中文 😀'})` | 同上，content/structuredContent 是准确自编 fixture text；admin | 否 |

`callMcpTool` 是 core-only 方法，当前无 HTTP/IPC tools/call route。不要增加临时 renderer 权限、伪造 AuthContext、读取私有 saved token 或以 DOM/内部 handler 调用代替 GUI。独立 Core 协议测试可用一次性 SQLite fixture 的正常注册/登录授权上下文；现有产品 route 应使用正常已登录 HTTP/IPC 认证。

IPC 请求采用真实 `CoreRequest`：`{protocol:1,id:<request UUID>,method:'GET',path:'/api/v1/mcp-services/<encoded id>/tools'}`；通过现有 `CoreIpcAdapter.invoke`/正式 preload invoke，公开结果在 `response.body.data`。正常会话恢复/refresh 保持原机制；不得向 request body 塞 bearer、Core 私有 ctx 或从 fixture 脚本注入用户认证。HTTP 对应 route 保留既有 host/origin/CSRF guard。仅记录自己的 fixture ID 与 public DTO。

Core 每次发现/调用建立官方 client transport、重新核验授权和 saved config，成功后尝试真实 session DELETE，并 finally 关闭 client/transport：[IntegrationService](../../packages/core/src/integrations/index.ts:292)。后续验收应同时看到：工具集合恰为两项、test 计数 2、实际 tool content/structuredContent、`isError:false`、SDK initialize/list/call 的安全 receipts，以及 shutdown 清理；不能用工具列表或 HTTP 200 代替实际调用结果。

## 此次实际检查（全未监听）

1. `node --check /tmp/marlin-local-mcp-20261010.cjs`：exit 0。
2. `node /tmp/marlin-local-mcp-20261010.cjs --check-only --core-root /home/liuxuedeng/Django-Agent/packages/core`：exit 0；实际官方 McpServer 注册两个 schema，确认 disconnected；合法 Unicode echo input 通过，小数/越界加法和 echo 额外字段被拒。
3. 同一 `--check-only` 在独立 Node 调用中预先把 net Server.listen/Socket.connect、tls.connect、http(s).request 与 global fetch 替换为立即拒绝的 guard：exit 0、`attempts:0`。此 guard 只证明准备模式没有尝试监听或请求，不冒充协议测试。

准确 stdout：

```json
{"fixture":"marlin-local-mcp-qa-20261010","event":"prep_checked","sdk":"1.32.1","transport":"streamable_http","tools":["qa_echo","qa_add"],"listening":false,"tool_calls":0}
{"event":"prep_network_guard","attempts":0,"success":true}
```

未启动本服务、未创建 provider、未发生 MCP handshake/tool call，真实 GUI 与正式 Core 运行验收均留待 root 决定执行。已有 integrations 官方协议测试只作为结构参考，本轮没有重复跑产品 suite。

此次读到的源码 SHA256（未编辑）：

- IntegrationService：`c03186a558d9dd15c87045eff0f32d3f431f5813d4ed59772fe93289dbd1a44a`
- settings routes：`3f75109e964b58c316714873fa2297c875b46f83fad2d108f059dbdd63b58fb1`
- Settings.vue：`d65a2ff9262be9dd5a7ca9ebd624ddbf13f7a5f88c7e7f082edce770ac869390`
- ChatInput.vue：`343b8aca9b6e467d41a5f66ec72655637d455f16a31981ad588356fd238ce65f`
- 官方 SDK package.json：`0216319ea53177f7ed419d660b2f52ccc7e3327e57f9ee2ef03225ff543aeae4`

Ragas 两条已冻结源码 SHA 仍为 `6a849aef12774646e330ef1c5490fbf7bea815647ebe2f544b4ee19695bee3a7` 与 `9330ae6fdb68f7c167616c4c7fd0f658bd5b839e617c507d81b7e106094db9a7`。
