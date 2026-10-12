# 核心发布响应性实施计划

依据 [实际架构评审](LOCAL-PUBLICATION-RESPONSIVENESS-REVIEW.md)、无模型大文件发布与真实健康超时证据。Goal 第二节第3–5项已授权普通模块拆分和独立协作，本计划记录后继续实施。保留现有业务和单写事务，不提交。

## 交付边界

先实现唯一完整应用 owner Worker 与真实传输桥，再实现只读 WAL 路由和同步发布取消检查点。仅健康接口独立或测试通过不能结束响应性修复。最终仍需真实 Orca、Electron、Windows 正式构建和安装复测。

1. owner Worker 独占 `CoreApplication`、`CoreIpcAdapter`、业务写连接、初始化、队列、恢复和 hooks。外层 HTTP/fork 保留传输校验及生命周期，不再创建写数据库。
2. 使用受控的内部 typed messages，桥接 AbortSignal、二进制、cookie、私有 Langfuse 与有界流；不跨 Worker 发送函数、数据库或 AsyncIterable，不给 renderer 暴露私有凭据。
3. 明确审查过的 DB GET 在独立 WAL 只读 Worker 的同步读快照中重新认证。IPC 认证切换采用 epoch fence；未知或有副作用的 GET 仍进入 owner。
4. 发布中的实际取消通过 claim/attempt 绑定的共享原子控制状态触发检查点；整个原事务回滚后才持久化取消并返回成功。取消与提交资格通过 CAS 仲裁，保留恢复和付费请求不盲重放。

## 阶段1接口与文件归属

root 协调接口与最终集成，负责现有 `adapters/http.ts`、`tools/dev-server.ts`、`tools/desktop-process.ts` 及相关传输回归。独立协作者只创建 `src/runtime/owner-contracts.ts`、`owner-client.ts`、`owner-worker.ts`、独立 owner 测试及独立证据，不修改其他产品文件、实时数据或 GUI。

`CoreOwner.start(config)` 异步启动，config 只包含 dataRoot、allowAutoSetup、parser/evaluation 可执行文件与 worker 路径等可序列化可信配置；类对象在 owner 内构造。ready 返回 serviceId。客户端提供现有签名的 `dispatch(request,binding,signal?)`、`invoke(input,options?,signal?)`、`openStream(input,options?,signal?)`、`nativeLangfuse(input,signal?)`、`startupLog(level,event)`、`close()`。

`httpTransport()` 返回可信内部 `{ serviceId, csrfKey, dispatch, preflightUpload }` facade。CSRF 密钥仍通过 owner 的 vault/数据库惰性初始化，不能由协调线程写。`preflightUpload(binding,kind,resourceId)` 在 owner 重新认证、检查原 write/document.write 权限和 KB/会话范围，完成后外层才读取有界 multipart；最终 dispatch 仍重验权限。`kind` 仅允许 document/chat，不能发送任意 SQL/函数或 AuthContext。

流保留事件、sequence、一次至多一个未确认 frame、ACK 与 disconnect/return；客户端在消费端推进前才 ACK。取消/关闭必须释放 pending ACK、iterator 和拥有的进程；请求并发与队列有界。HTTP 私有 authChange/cookies 只在可信 facade 中返回，IPC invoke 仍由 owner adapter 清理，不能输出秘密到报告。

## 回归与阶段状态

- [x] 阶段1 RED/GREEN：真实 Worker 和 SQLite/FTS/vec、认证与重开、上传/二进制、流/ACK/abort、Langfuse 私有边界、并发界限及失败/close；源码与编译 `.js` 入口都验证。强制崩溃在途Python清理尚未证明。
- [x] root 接入 HTTP 和正式 fork 两入口，运行原相关传输、生命周期、权限回归与 typecheck/build；旧直接实例化单测继续用真实核心。
- [ ] 阶段2形成精确只读能力/路由与 epoch/snapshot 回归，然后实现，不用强制类型转换冒充可写数据库。
- [ ] 阶段3形成发布取消/提交/失联恢复回归，然后实现；不使用终止 Worker 冒充正常业务取消。
- [ ] 阶段4正式 Windows 清单、安装与双链路真实大文件读页/取消采样；继续完成全部页面验收。

计数、分块刷新及owner阶段1已实现并有真实Orca上传证据；query/cancel尚未实现，约6.7秒同步发布仍未通过。[阶段1验收](CORE-OWNER-TRANSPORT-ACCEPTANCE.md)。

## root 传输接入步骤

- [x] 新建 `packages/core/test/owner-transports.test.ts`，用真实 `CoreOwner` facade 接入原 HTTP adapter；运行 `node --import tsx --test test/owner-transports.test.ts`，先确认缺少 facade 支持导致 RED。覆盖签名 CSRF、HttpOnly 账户会话、跨空间上传预检、真实 Python 上传/下载、重开保留身份。
- [x] `adapters/http.ts` 接受 `CoreApplication | CoreHttpTransport`，原直接实例测试保留；正式开发入口只传 owner facade。原实例的 CSRF 初始化及上传认证封装为同样的可信接口，HTTP 请求处理不再要求数据库实例。先 `await preflightUpload(...)` 再读取 multipart，最终 dispatch 重验。
- [x] `tools/dev-server.ts` 改为 `await CoreOwner.start({dataRoot, allowAutoSetup:true, parser: options, evaluation})`，日志、HTTP facade 和退出均异步，初始化 HTTP 失败也关闭已创建 owner。
- [x] `tools/desktop-process.ts` 改为相同 owner，保留原 JSON 私有字节编解码、64 请求界限、ACK、AbortSignal 和 ready/stopped 协议；窗口断开先取消再关闭 owner，禁止外层新建写数据库。
- [x] 运行新增 RED/GREEN 和原 `http*.test.ts`、`ipc*.test.ts`、`desktop-process.test.ts`、`system-diagnostics.test.ts`，执行 typecheck/build 并核对差异。测试与源码哈希保存到独立证据，检查纯编译入口。
- [x] 仅在相关检查通过后正常停止已知浏览器服务进程并启动同一数据目录的新入口；用 Orca 页面实际重验登录恢复、知识库列表、上传/分块和读页延迟。阶段2/3完成前不宣称同步发布期间读页及取消问题已修复，不提交、不发布。
