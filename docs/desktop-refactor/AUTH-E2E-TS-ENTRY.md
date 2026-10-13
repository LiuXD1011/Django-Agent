# 认证 E2E 的 TypeScript 启动入口

目标是让原 `cross-device-auth.spec.ts` 的跨设备、共享页账号切换、HttpOnly 及刷新恢复断言运行于真实 TypeScript Core + Vue，普通认证检查不再启动 Django。Goal 第二节已授权有限设计后自主实施；本任务不改生产认证、依赖/锁文件、现有服务或主验收文档，不提交。

旧配置在 Playwright `webServer.command` 中先执行 Django migrate/runserver，固定 Python 路径和旧数据目录。新核心已提供 `src/tools/dev-server.ts --data-root --port --ui-origin`；不配置 parser/Ragas 也可完成公开注册、登录、知识库空记录及设备操作。Playwright 1.61.1 已安装类型确认 `webServer.command`、`reuseExistingServer=false` 和进程组 SIGTERM gracefulShutdown；Vite 7 的实际类型提供 `createServer`、`cacheDir`、strictPort 和 proxy。

可选择两个独立 webServer（需要共享随机 dataRoot），或一个仅测试启动 helper 同时管理 Core 子进程和 Vite。选择后者：helper 使用 `mkdtemp` 创建全新空数据/缓存，Core 仅监听127.0.0.1:8180，Vite仅监听127.0.0.1:4180并覆盖现有 `/api`、`/files`、`/health` 三代理。端口先检查占用，strictPort禁止自动换端口或复用；真实 health 必须报告typescript，然后才启动 UI。不修改生产 Vite 配置，不共享既有 Vite cache，不连接8000/5173/8014/5184或复制用户数据。

生命周期只管理 helper 自身和它创建的 Core child，记录公共 PID/启动标识/argv/就绪及退出。SIGTERM关闭 Vite并正常结束自己的 Core，等待实际close后才清理该次临时目录；失败/未知保留诊断，不向原服务发送信号。测试浏览器使用 Playwright 独立 headless contexts，无Orca/native GUI。

当前原 spec 的 Cookie 名仍是 `pkb_access/pkb_refresh`，真实 TypeScript HTTP 使用 `marlin_access/marlin_refresh`。先保持 spec 只读运行确认真实差异，不通过添加旧 Cookie 别名、mock 或弱化 HttpOnly/刷新断言解决；若实际失败需要改 spec，将先向 Root 报告并协调该有限协议迁移。

计划：

- [x] 在真实无Django parservenv环境运行旧入口，保留原stderr与实际退出；导入失败发生在任何旧数据库访问之前。
- [x] 完整核查原 spec/config、dev-server/HTTP/auth与已安装Node/Playwright/Vite类型，冻结原文件SHA。
- [x] 最小迁移配置和仅测试helper，真实跑原三项规格，保留所有失败/skip。
- [ ] 如原Cookie协议断言失败，提供实际失败并等待精确spec归属授权；不改生产HTTP。
- [x] 执行frontend `npm run test:unit`、配置/helper必要类型检查及Vite生产build，结果按各自范围记录。
- [x] 核对生产认证/依赖/原spec保护、独立端口与owned进程退出，检查链接/差异，精确归档删除临时助手。

## 验收边界

这是程序化Chromium认证E2E，不冒充Orca真实鼠标、自然600秒到期、正式Windows IPC、迟到refresh竞态或完整A组通过。原三项包含公开UI注册/登录、两个独立Cookie jars及390px上下文、真实API空库共享/撤销、共享tab账号切换和明确移除access后的refresh恢复。无真实模型/解析/评测调用，原Source3833788必须保持。

## 本轮实际结果

旧入口实际Playwright退出1、业务规格尚未执行。指定Python3.12.2的parservenv没有Django，但旧 `manage.py` 先从bootstrap导入filelock，因此原stderr首先是 `ModuleNotFoundError: filelock`，尚未进入数据库迁移；另同一解释器的独立 `import django` 也真实退出1。两者分别保存，不把先发生的filelock错误改写为Django错误。[旧入口原stderr](../refactor-evidence/20261013-auth-e2e-ts-entry/old-entry-red.stderr.log)、[实际RED](../refactor-evidence/20261013-auth-e2e-ts-entry/old-entry-red.json)、[无Django独立证据](../refactor-evidence/20261013-auth-e2e-ts-entry/no-django-environment.json)。旧配置完整字节已按初始SHA复核留存，新入口完全移除Python/migrate/runserver及旧APP_DATA_DIR。

原spec以全新Core数据目录真实执行3项，实际3FAIL/0PASS：两个Cookie HttpOnly断言寻找旧 `pkb_*` 得到undefined；账号切换案例先遇到创建知识库期待201、实际200。已读当前 `knowledge-routes.ts` 与原 `application-knowledge.test.ts:27–28`，TS明确约定该创建返回200。它们是规格迁移边界，不能据此称生产认证坏了，也不能宣称跨设备后续断言已走完。[原三项实际日志](../refactor-evidence/20261013-auth-e2e-ts-entry/original-spec-on-ts.stdout.log)、[命令终态](../refactor-evidence/20261013-auth-e2e-ts-entry/original-spec-on-ts.json)。原spec仍保持SHA `24add2593d862fa7f1a0462b4323bb72ee28ad6d06ba716be27d71c05c66fc6d`；Cookie名称、两处创建状态与旧Django注释的有限迁移已报告Root，尚未取得spec文件归属授权，保留待办。

首次launcher退出观察有重复SIGTERM：Playwright发给整进程组、helper再发给同组Core，Core以signal退出；原结果保留。现Core child独立进程组，由helper的准确child handle唯一发送SIGTERM；同次独立真实启动/health及关闭观察Core code0/signalnull、helper0，两PID实际不存在、随机data/cache目录已移除。即时Python无SO_REUSEADDR bind观察器在退出后报EADDRINUSE，原观察器失败保留；随后实际ss无监听且4180/8180连接均ECONNREFUSED，不重启重放该次launcher来掩盖结果。[原退出记录](../refactor-evidence/20261013-auth-e2e-ts-entry/original-spec-on-ts.stdout.log)、[修复后正常生命周期](../refactor-evidence/20261013-auth-e2e-ts-entry/launcher-lifecycle.json)。这仅验证Linux测试启动器，不称Windows进程树门禁通过。

frontend `npm run test:unit` 实际361/361、零失败/取消/skip，TAP109384.285407ms；配置/helper的严格checkJs/typecheck退出0。首次三处类型诊断的同名log误被后续覆盖，已明确记录原actual tool结果，不伪称原log字节保留。生产Vite build退出0、日志报告42.16s，原大chunk warning继续存在；命令时间不当作页面延迟。[完整前端](../refactor-evidence/20261013-auth-e2e-ts-entry/frontend-unit.json)、[配置类型](../refactor-evidence/20261013-auth-e2e-ts-entry/config-types.json)、[初次类型失败留记](../refactor-evidence/20261013-auth-e2e-ts-entry/config-types-initial-tool-output.json)、[构建](../refactor-evidence/20261013-auth-e2e-ts-entry/frontend-build.json)。没有改生产auth、依赖/lock或已有Vite配置，也没有Orca/native操作、真实用户/模型配置或付费请求。

完成的是启动入口迁移与有界检查，原三项认证E2E未通过、Goal继续active。私有失败trace只保留在本轮隔离生成的`.cache`目录，公开证据仅绑定SHA/失败输出，不导出其Cookie/header内容。后续Root如授予精确spec迁移，再以相同三项断言运行；不删断言、不加skip、不增加旧Cookie别名或修改生产HTTP来适配旧规格。
