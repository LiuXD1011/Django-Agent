# Marlin 桌面重构实施计划

**目标：** 完成由 TypeScript 承载业务、无需 Django 的 Windows x64 桌面应用，并执行 Goal 全部真实验收。

**架构：** Vue 页面共用一个独立 TS 核心；正式 Electron 通过 preload/IPC 连接核心独立Node子进程，Orca 通过 HTTP/SSE 适配连接相同核心。SQLite 单一写入协调，Python 仅解析/OCR/Ragas。

**执行：** 用户已批准连续实施及独立任务委派；不重复阶段批准、不提交、不推送。共享 contracts、数据库迁移、集成和验收由根代理负责。每个独立模块完成后审查规格与实现质量。

## 全局约束

- Windows x64 必须实际验收；macOS/Linux 环境未验证必须明示。
- 当前工作区和实际行为是基线，保留已有改动；旧 Django 完成功能替换和验证后清理。
- 业务/权限不能被删除或模拟；API Key、认证凭据不回显或进入证据。
- 测试数据和安装目录独立；不修改真实密码、撤销真实设备或清除真实密钥。
- 付费结果不确定时不自动重放；只能终止本应用拥有的进程。

## P1 基线、设计与验收资料

- [x] 完整读取 Goal、AGENTS、原桌面入口/依赖、关键认证与数据协议。
- [x] 将 452 个当前源码文件与原始差异备份到工作区外私有目录；SQLite backup + 媒体/密钥/配置副本。
- [x] 原 Django check 与前端 140 项单元测试基线。
- [x] 三份基线形成且已阅读关键范围：105 API / 2 SSE / 69 UI用例，31业务表及解析协议；UI详细用例仍需合并到执行矩阵。
- [ ] 完成版本化协议与黄金资料：事实、旧版冲突、表格计算、相似实体、图像、缺失事实、隔离与修改/删除。

## P2 存储、凭据、任务和第一条真实闭环

1. **核心基础**：新增 `packages/core/package.json`、`tsconfig.json`、`src/contracts.ts`、`src/errors.ts`。精确锁定并安装 better-sqlite3、Drizzle、sqlite-vec、MCP SDK，检查实际类型；`npm run typecheck` 和 `npm run build` 无错误。
2. **数据库与导入**：新增 `src/storage/schema.ts`、`migrations.ts`、`database.ts`、`legacy.ts`、`files.ts`、`credentials.ts`。先写真实 SQLite 关系约束/事务回滚、大整数、错误密钥不覆盖、重复导入和备份恢复测试，观察失败再实现。业务数据迁移逐表计数/关联/媒体 hash，原文件不改变。
3. **任务/事件**：新增 `src/jobs/queue.ts`、`events.ts`、`process.ts`。测试并发事件连续、请求 ID 早停、进程超时取消、重启恢复及付费请求 interrupted。状态更新与事件写入同事务。
4. **认证和模型**：新增 `src/auth`、`src/models`、`src/settings`。验证初次初始化、坏密码、注销/设备撤销、成员及个人空间过滤；厂商真实端点错误与各角色调用/思考选项；凭据留空保留、端点更换不泄露旧凭据。
5. **文档解析**：新增 `workers/document`、TS 解析桥和 chunker。将有价值的纯解析逻辑提取到无 Django 模块，实际解析格式 fixture；扫描 PDF 使用真实 VLM，SVG MIME 错配加入回归。解析进程只返回结构化产物。
6. **闭环**：新增 `src/documents`、`src/retrieval`、`src/chat`。真实上传→正文/分块→FTS/向量→Rerank→流式回答→引用，逐项核对标准答案；错误、取消、编辑和删除之后检索正确。

检查命令：`cd packages/core && npm run typecheck && npm test && npm run build`；测试日志保存证据目录。每一行为的测试具体断言包含实际 DB/文件结果，不能只断言函数被调用。

## P3 全部页面和业务迁移

- [ ] `src/wiki`：页面、目录、内部链接、来源、日志、lint/修复、重新生成/文档变化；读取现有 API 响应形状后迁移。
- [ ] `src/graph`：实际节点关系、实体消歧和来源；Neo4j 驱动真实读写（配置存在时）。
- [ ] `src/agent`、`src/memory`、`src/integrations`：工具循环、子任务、轨迹、意图记忆；官方 MCP 客户端、WebSearch、Langfuse、现有资源/渠道能力。
- [ ] `src/evaluation` + `workers/evaluation`：候选审核/编辑/发布、版本、至少5题、任务取消恢复、报告与真实指标；保留公开数据集、检索/分块评测行为。
- [ ] `src/adapters/router.ts`、`http.ts`、`ipc.ts`：实际核心路由与流订阅；严格方法/路径/范围校验，无 Django 转发。
- [ ] `desktop/main.cjs`、`preload.cjs`、`runtime.cjs`、`ipc.cjs` 及 `packages/core/src/tools/desktop-process.ts`：现有薄Electron壳承接窗口、单实例、托盘、选择/拖入、生命周期和正式IPC；主业务在独立TypeScript核心中。
- [ ] `frontend/src/api`：浏览器和桌面传输共用现有业务 API；流取消和恢复走真实后台。完整读受影响文件再编辑，保留 PWA/远程边界。
- [ ] 逐项比对功能清单，新实现存在且不是空成功；旧页面设计问题按实际证据修复。

检查：核心 `npm run typecheck` 与相关集成测试；`cd frontend && npm run test:unit` 和 `npm run build`，涉及组件的语义检查使用实际安装的Vue/TypeScript接口，Vite构建不冒充语义类型检查；桌面实际IPC/进程测试及Windows打包gate，不调用不存在的子包typecheck/build命令；对齐迁移清单。

## P4 真实界面与性能验收

- [ ] 使用 Orca 的新 TS 核心入口逐页真实点击/输入/上传/引用/下载，按 `TEST-MATRIX.md` 记录全部结果。
- [ ] 标准答案12类问题；至少5条已批准题真实评测；四模型真实业务调用和 token 记录。
- [ ] 旧8类问题回归、解析根记录关闭、单写者事件无丢失；发现问题先定位根因，回归测试和原界面用例双重验证。
- [ ] 1440×900、1024×768、键盘、中文输入、遮挡/滚动/弹窗/按钮对比度。
- [ ] Electron 真窗口实测正式 IPC，与浏览器结果一致；禁止用假 preload 替代。
- [ ] 冷/热启动、页面/list/search/save、上传/排队/阶段/入库、首段/完整回答/停止、评测等待/执行；记录采样条件、数量、时间起止，不伪造 P95。

## P5 Windows 安装与清理交付

- [ ] 新构建脚本只打包 TS 核心、正式前端、必要 Python worker/runtime；不带 Django、用户数据、密钥、开发服务器依赖。
- [ ] 在中文+空格验收目录安装，正常首次启动/登录/闭环，无系统 Python/Node，无 Vite。
- [ ] 升级、重启、异常恢复、关闭/后台/退出、单实例、进程清理，卸载保留数据；保留原正式安装。
- [ ] 验证打包产物和依赖清单；清理已替代旧代码/依赖/脚本/文档并验证全部替代行为。
- [ ] 完整运行授权的类型、单元、集成、E2E、构建检查；最终独立规格与代码审查。
- [ ] 完成最终报告、安装包路径/hash/启动和测试命令；清理临时脚本和测试认证材料。
- [ ] 按 Goal 十条完成标准逐项审计，有核心缺失时保持 active 并继续。
