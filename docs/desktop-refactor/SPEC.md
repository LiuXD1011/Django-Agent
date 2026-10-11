# Marlin 桌面重构设计

日期：2026-10-10。范围和技术方向已由 Goal 提示词批准。当前工作区（包含未提交文件）是唯一实现基线。此文档描述目标，不表示功能已经实现或通过。

## 交付约束

- Windows x64 安装版必须真实运行、真实验收；正常启动和包内业务不依赖 Django、DRF、Waitress、Gunicorn。
- Electron 44.7.0、Vue 3、TypeScript、Vite、Pinia；SQLite、better-sqlite3、Drizzle、FTS5、sqlite-vec。依赖精确版本以安装锁文件为准。
- Python 仅承担文档解析/OCR/Ragas；不导入 Django、不写业务数据库。用户不需要系统 Python/Node。
- 不删除既有业务能力，不发布、不提交、不推送、不创建标签。修改无关文件前先重新检查范围。
- 用户原始数据库、管理员密码、密钥、真实设备不作为破坏性测试对象。

## 基线与隔离

仓库当前已有 Electron 壳，但 `desktop/main.cjs` → `runtime.cjs` → `scripts/start_desktop.py` 仍启动 Django。现有 `frontend` 连接 HTTP/SSE，包含账户、个人空间、PWA 和设备会话实现。主工作区有大量已修改及新增文件，直接从 HEAD 创建工作树会丢失这部分基线。

本次在当前工作区新增 `packages/core`、`workers` 和桌面新入口；旧实现保留到功能替换且验证后再清理。源码私有快照位于 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-baseline/source`，包含 452 个文件及原始差异。测试数据独立于源码、安装目录和用户原始数据。

已通过 SQLite backup API 复制旧数据库，连同媒体、`.settings`、`.secrets` 保存在上述目录的 `legacy-data`；目录权限 0700。快照不是运行目录，测试在新的独立目录进行。真实凭据只允许业务内部使用，不写入文档或证据。

## 模块与数据流

| 模块 | 责任 | 禁止依赖 |
| --- | --- | --- |
| `frontend/src` | 页面、组件、用户输入、展示状态 | 数据库、存储凭据读取、任意系统命令 |
| `desktop/src` | 窗口、托盘、文件选择、受控 preload、IPC、生命周期 | Django、业务 SQL |
| `packages/core/src` | 账户/空间权限、文档、检索、聊天/Agent、记忆、Wiki、集成、评测、任务 | Vue、Electron 窗口对象 |
| `packages/core/src/storage` | 版本化数据库、关系约束、写入协调、加密、备份、导入 | 渲染进程访问 |
| `packages/core/src/adapters` | 浏览器 HTTP/SSE 与 IPC 对业务核心的传输适配 | 旧 Django 服务、模拟成功 |
| `workers/document` | 独立解析，输出正文/表格/图片/来源 | Django、业务数据库写入 |
| `workers/evaluation` | Ragas 对显式样本计算指标 | 账户业务、业务数据库写入 |

正式版由 Electron 启动核心 utilityProcess，后者持有唯一业务写连接。preload 暴露经过校验的请求、订阅、取消、文件选择等有限能力；消息包含协议版本、调用 ID 和业务范围。HTTP 入口仅供开发/Orca 或明确选用的远程模式，并调用同一个核心。Electron 的业务调用走 IPC；正式界面从打包资源加载，不依赖 Vite。

旧 UI 的路径和响应形状通过传输适配保留，业务实现迁移到各个 TypeScript 模块。此适配不转发到 Django，也不暴露任意 SQL、文件路径或命令。

```ts
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
interface CoreRequest {
  protocol: 1;
  id: string;
  method: Method;
  path: string; // 已注册 /api/v1 路径；查询参数经各路由校验
  body?: Json;
}
interface CoreResponse {
  protocol: 1;
  id: string;
  status: number;
  body: Json;
}
interface CoreEvent {
  protocol: 1;
  topic: string;
  request_id: string;
  seq: number;
  type: string;
  data: Json;
}
```

认证凭据由浏览器 HttpOnly Cookie 或 Electron 主进程的会话容器持有。IPC 不允许通过渲染进程传入任意用户/租户覆盖认证上下文。写操作、订阅、下载均检查用户、活跃成员、个人空间所有者及资源所属空间。管理员权限不穿透个人空间。

## 存储和迁移

基线有 31 个业务实体表（29 个知识库实体、2 个设备认证实体），另有 FTS、向量及索引元数据。使用独立 SQL 迁移建立业务表，保留已有标识和关系；不重放旧 Django 历史数据迁移，其中存在删除全部知识数据的不可逆操作。Drizzle 提供类型化表定义，native SQLite 负责 FTS/vec 扩展和必要的事务。

64 位关联标识在存储侧使用 bigint，传输超出安全范围的整数使用十进制字符串；禁止转换为 JavaScript number。JSON 字段的数组/对象/空值保持原义。凭据沿用经过验证的 AES-256-GCM `enc:v1:` 格式（12 字节 nonce、字段名 AAD、尾部认证标签），导入验证后重新加密或保留相同密钥；密钥缺失/错误必须阻止导入并保留原文件。

SQLite WAL、foreign_keys、明确的 busy_timeout；所有写入在核心进程同步事务内协调。解析与评测进程只返回消息，不能建立写连接。事件序号与插入在同一事务完成，唯一约束拒绝重复。任务状态、请求 ID、attempt、步骤、错误和进度持久化。

FTS5 使用可处理中文的检索文本；向量索引按模型签名和维度隔离，通过可重建的 index generation 发布。编辑/启停/移动/删除同步更新索引；重建失败保留业务记录和上一有效索引。过滤知识库和权限后才融合候选与 Rerank，不能截断未过滤候选再导致正确结果丢失。

## 任务与进程

任务状态：queued → running → completed/failed/cancelled/interrupted；取消请求独立持久化。请求在助手消息创建前注册，因此 `request_id` 可立即取消。AbortSignal 传递到真实模型 HTTP 请求和 Python 子进程。

解析、索引等可重做本地阶段从持久步骤恢复；正在进行且结果不确定的付费调用标记 interrupted，待用户明确重试，不盲目重放。重试产生新的 attempt，并关闭前一 attempt 的所有运行中记录。停止/退出只清理本应用记录的子进程，禁止按端口或进程名杀进程。

Python JSON Lines 协议 v1：每条消息带 id、protocol、type；parse 请求只含受控输入/输出路径及解析选项；返回 ParsedDocument 的 text、blocks、tables、images、page/source/bbox、warnings、error。图片必须区分原始 MIME 与输出 MIME并记录 hash，产物必须在受控目录内；TS 校验协议、大小和路径。扫描 PDF 输出真实页图，由已配置视觉模型识别；未配置时显式显示待配置，不宣称 OCR 成功。

## 模型、Agent 和集成

模型适配保留四角色及当前提供商，统一用量/错误/超时与流事件，保留厂商思考能力差异。默认角色由空间配置解析；GLM 摘要、记忆等辅助调用同样遵循思考参数。密钥不回显到 renderer，不进入错误正文、证据或版本库；输入框允许写入新凭据，响应仅含配置状态。

Agent 使用真实工具循环，支持检索、Wiki、图谱、联网搜索、MCP、子任务与既有工具能力；工具允许范围由认证与会话决定。MCP 使用官方 TypeScript SDK，对受控本地测试服务做真实握手/发现/调用。Neo4j、Langfuse、联网搜索是可选外部适配：未配置、不可连接与成功各有明确状态；不伪装成空图/成功。

记忆按用户与空间隔离、遵循开关与用户意图。评测管理、数据集审核版本与恢复由 TS 承载；Python Ragas 仅对显式输入计算分项指标，返回逐样本与聚合依据，失败没有默认 0 分。至少 5 条证据充分的已批准题真实运行。

## 页面映射与验证

当前路由包含登录、知识库列表、文档工作台、Wiki、全局/知识库对话、设置、设备和评测。设置有常规、用户、Neo4j、Langfuse、模型、检索、联网搜索、MCP、系统 9 分区。完整按钮映射由 [UI-BASELINE.md](UI-BASELINE.md) 展开；数据库与语义详见 [DATA-BASELINE.md](DATA-BASELINE.md)，解析格式详见 [PARSER-BASELINE.md](PARSER-BASELINE.md)。

每项业务必须有单元/集成边界检查及真实界面结果。Orca 必须实际 click/fill/upload；API 验证补充结果，不代替操作。Electron IPC、正式资源、安装包独立验证。详见 [TEST-MATRIX.md](TEST-MATRIX.md)。

## 完成门槛

通过 Goal 中全部核心验收、四角色真实调用、数据迁移/重复导入/失败/恢复、Windows x64 隔离安装/升级/卸载，以及相关检查和构建；没有遗留的数据丢失、越权或核心不可用缺陷。可选外部配置和非目标平台缺失明确列未验证，核心缺失不能据此宣布完成。

核查的官方 API：[Electron utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)、[Drizzle SQLite](https://orm.drizzle.team/docs/sqlite/get-started-sqlite)、[sqlite-vec Node](https://alexgarcia.xyz/sqlite-vec/js.html)、[MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)。安装后仍须读取实际类型定义。
