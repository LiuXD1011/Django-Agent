# 认证 E2E 的 TypeScript 启动入口

目标是让原 `cross-device-auth.spec.ts` 的跨设备、共享页账号切换、HttpOnly 及刷新恢复断言运行于真实 TypeScript Core + Vue，普通认证检查不再启动 Django。Goal 第二节已授权有限设计后自主实施；本任务不改生产认证、依赖/锁文件、现有服务或主验收文档，不提交。

旧配置在 Playwright `webServer.command` 中先执行 Django migrate/runserver，固定 Python 路径和旧数据目录。新核心已提供 `src/tools/dev-server.ts --data-root --port --ui-origin`；不配置 parser/Ragas 也可完成公开注册、登录、知识库空记录及设备操作。Playwright 1.61.1 已安装类型确认 `webServer.command`、`reuseExistingServer=false` 和进程组 SIGTERM gracefulShutdown；Vite 7 的实际类型提供 `createServer`、`cacheDir`、strictPort 和 proxy。

可选择两个独立 webServer（需要共享随机 dataRoot），或一个仅测试启动 helper 同时管理 Core 子进程和 Vite。选择后者：helper 使用 `mkdtemp` 创建全新空数据/缓存，Core 仅监听127.0.0.1:8180，Vite仅监听127.0.0.1:4180并覆盖现有 `/api`、`/files`、`/health` 三代理。端口先检查占用，strictPort禁止自动换端口或复用；真实 health 必须报告typescript，然后才启动 UI。不构建/修改生产 Vite 配置，不共享既有 Vite cache，不连接8000/5173/8014/5184或复制用户数据。

生命周期只管理 helper 自身和它创建的 Core child，记录公共 PID/启动标识/argv/就绪及退出。SIGTERM关闭 Vite并正常结束自己的 Core，等待实际close后才清理该次临时目录；失败/未知保留诊断，不向原服务发送信号。测试浏览器使用 Playwright 独立 headless contexts，无Orca/native GUI。

当前原 spec 的 Cookie 名仍是 `pkb_access/pkb_refresh`，真实 TypeScript HTTP 使用 `marlin_access/marlin_refresh`。先保持 spec 只读运行确认真实差异，不通过添加旧 Cookie 别名、mock 或弱化 HttpOnly/刷新断言解决；若实际失败需要改 spec，将先向 Root 报告并协调该有限协议迁移。

计划：

- [ ] 在真实无Django parservenv环境运行旧入口，保留原stderr与实际退出；导入失败发生在任何旧数据库访问之前。
- [ ] 完整核查原 spec/config、dev-server/HTTP/auth与已安装Node/Playwright/Vite类型，冻结原文件SHA。
- [ ] 最小迁移配置和仅测试helper，真实跑原三项规格，保留所有失败/skip。
- [ ] 如原Cookie协议断言失败，提供实际失败并等待精确spec归属授权；不改生产HTTP。
- [ ] 执行frontend `npm run test:unit`、配置/helper必要类型检查及Vite生产build，结果按各自范围记录。
- [ ] 核对生产认证/依赖/原spec保护、独立端口与owned进程退出，检查链接/差异，精确归档删除临时助手。

## 验收边界

这是程序化Chromium认证E2E，不冒充Orca真实鼠标、自然600秒到期、正式Windows IPC、迟到refresh竞态或完整A组通过。原三项包含公开UI注册/登录、两个独立Cookie jars及390px上下文、真实API空库共享/撤销、共享tab账号切换和明确移除access后的refresh恢复。无真实模型/解析/评测调用，原Source3833788必须保持。
