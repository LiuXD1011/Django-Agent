# 旧 Django 实现清理

> 执行计划及结果。Root 统一删除旧文件，子代理并行核对依赖、构建边界及文档；不提交、推送或发布。

**Goal:** 完成用户本次要求的旧实现、依赖和启动入口退役，保留现有桌面功能、数据迁移能力、用户资料及许可证。

**Architecture:** Electron、TypeScript Core、Vue 与 SQLite 继续承担正常业务；独立 Python workers 保留解析和评测。旧库导入直接读取 SQLite，由现有 TypeScript 实现负责，不保留 Django 运行入口。

**Tech Stack:** 现有 Node 22、TypeScript、Electron、SQLite、Python workers；不改依赖版本和锁文件，不新增兼容层。

## 范围与步骤

- [x] 完整核对现有 301 项候选、原字节归档及保留源码的静态／动态引用。当前候选 hash 变更 0，新运行入口对候选的依赖 0。Langfuse 开发启动能力已由现有 TypeScript 服务接线，旧暂缓条件不再要求保留 Python 启动器。
- [x] 精确删除 301 项旧业务包、manage.py、旧 requirements、旧桌面依赖锁、Python 启动脚本与旧框架测试；删除 249 个已确认的旧字节码，35 个空目录使用 rmdir 移除。
- [x] 修正根静态前端测试的旧命令／覆盖说明，原断言保持；更新当前文档入口，将旧方案和运维记录明确标为历史。
- [x] 执行核心类型、迁移／认证／凭据／解析桥接、独立 Python workers、桌面／启动器、构建边界及文档的定向检查。
- [x] 删除后核对 Windows 的 483 项构建输入与已交付正式包逐项 SHA 相同；不为不影响产物的旧源码删除重复打包。

用户数据库、WAL／SHM、媒体、.settings、.secrets、.env、缓存、安装目录和备份不在删除范围。保留 workers 全目录、新 TS auth/storage/legacy/import、评测数据注册信息、密码兼容向量、构建锁及许可证。不卸载系统 Python 包，不删除正常业务。

## 证据与历史资料

本次实际执行结果写入 [清理证据目录](../refactor-evidence/20261013-legacy-cleanup/)。原 [301 项候选](../refactor-evidence/20261013-legacy-retirement-prepare/candidates.json)及非运行 `.txt` 归档保留，作为旧数据结构、兼容行为和历史验收依据；这些不属于运行或打包源码。历史直接源码链接通过 [原始来源映射](../refactor-evidence/20261013-legacy-retirement-prepare/HISTORICAL-SOURCE-MAP.md)解引用，原失败收据不修改。

## 实际结果（2026-10-13）

已完成上述清理。9 个旧 Django 包目录均已移除；正常运行与构建使用现有 TypeScript 核心及独立 workers。旧文件逐项匹配原字节归档后删除，详见 [301 项删除收据](../refactor-evidence/20261013-legacy-cleanup/deletion.json)及 [1 项孤立旧字节码收据](../refactor-evidence/20261013-legacy-cleanup/orphan-legacy-cache-cleanup.json)。原有归档不恢复为可运行 Python 文件。

| 检查范围 | 本次实际结果 | 证据 |
| --- | --- | --- |
| 核心 TypeScript 类型检查 | 退出码 0 | [执行记录](../refactor-evidence/20261013-legacy-cleanup/core-execution.json) |
| 认证、凭据、旧库导入、路由、解析桥接及桌面进程 | 65/65 通过 | 同上 |
| 独立文档解析 / 评测 worker | 25/25、7/7 通过 | [worker 与桌面记录](../refactor-evidence/20261013-legacy-cleanup/worker-desktop-startup-receipt.json) |
| 桌面 / 启动器 | 43/43；130 通过、5 项 Windows 原生条件跳过 | 同上 |
| 现有构建边界 / 根静态前端契约 | 6/6、4/4 通过 | [根检查记录](../refactor-evidence/20261013-legacy-cleanup/root-static-build-checks.json) |
| Windows 构建输入 | 483 项路径与 SHA 均匹配已交付正式包，新增 / 删除 / 变更均为 0 | [源码复用核对](../refactor-evidence/20261013-legacy-cleanup/core-source-reuse.json) |
| 最终删除范围、归档、文档链接与差异 | 按清理后工作区核对 | [最终核对](../refactor-evidence/20261013-legacy-cleanup/final-validation.json) |

核心检查在没有 Django 的独立解析 Python 环境中执行。首次检查因验证脚本把 npm 两种配置指向同一空文件而在加载配置阶段退出；修正验证环境后类型与测试均成功，原失败记录保留，没有修改产品代码规避失败。

本次没有重复完整前端套件、Windows 打包、可见窗口验收或付费模型调用。483 项构建输入未变，沿用已交付安装包及其既有 Windows 实测证据；Linux 上的 5 项 Windows 条件跳过不计为本次通过。历史业务矩阵、原失败与未验证范围保持原状态。

本次自有临时脚本已归档为非运行文本并删除。未读取或删除用户数据、密钥，未卸载全局依赖，未暂存、提交、推送或发布。
