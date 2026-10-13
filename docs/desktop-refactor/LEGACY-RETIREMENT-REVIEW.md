# 旧 Django 实现退役只读评审

> 历史身份：本文保留2026-10-12只读评审时点，包括当时的默认认证测试、旧E2E入口和未批准删除结论。其后默认检查及认证E2E已迁移到TS，开发Langfuse opt-in自动启动也已有TS实现；用户本次要求完成清理。当前执行范围、保留核对和结果以[清理说明](LEGACY-CLEANUP.md)为准，本文不构成继续保留旧运行入口的当前指令。原始评审证据不改写。

2026-10-12。依据已完整读取的 [SPEC](SPEC.md) 与 [PLAN](PLAN.md)：旧实现须在替换和验证后清理，不能删除既有能力。本轮只做静态审查；未删除代码、依赖或数据，未运行测试/构建、GUI、服务或模型。Goal active，本文不证明全部替代行为已通过。

正常入口已分离：[根 scripts](../../package.json) 的 local/desktop 指向编译 TS/Node；[正式桌面](../../desktop/runtime.cjs) 只启动核心及独立 Python worker。[builder](../../scripts/build_windows.py) 148–170/198–215 行以明确名单复制 frontend/core/workers，不纳入旧应用；[Python builder](../../scripts/desktop/build-python-runtime.py) 36/85 行拒 Django/DRF/Waitress/Gunicorn/WhiteNoise。匹配到的旧名称属于说明、拒绝旧产物测试及导入表版本字符串，不能按名字一律删除。

| 候选范围 | 退役条件/边界 |
| --- | --- |
| `manage.py`、根 `requirements.txt`、`config/`、旧根 Python `core/`；`personal_knowledge_base/`、`accounts/agent/chat/knowledge/models_config/wiki/` | 新运行与打包无加载依赖；这些是原 Django 应用。仍须先完成相应替代功能/权限验收、提取下列保留项和历史引用处理，当前不批准整树立即删除。根 Python `core/` 与 `packages/core/` 分开。 |
| `scripts/start_local.py/start_desktop.py/local_services.py`，`benchmark_open_rag_runtime.py/bench_langfuse_overhead.py/verify_langfuse_settings.py/test_benchmark_open_rag_runtime.py`；`desktop/requirements-windows.lock` | 旧脚本实际依赖 Django，旧 lock 不在当前 builder 名单；可与旧入口一起退役，不卸载共享系统/测试 Python 包。保留新 `scripts/desktop/`、两份 worker requirements 和 native locks。 |
| 旧应用内测试、根 `tests/` 中导入旧模型的测试 | 逐项迁移有价值的断言/标准答案，不能全删 `tests/`；`test_readme_links.py`、前端静态契约等独立检查另审。 |
| `frontend/playwright.auth.config.ts` | 第15行仍 migrate/runserver Django；先迁移到隔离 TS 认证 E2E，不能把旧 E2E 计作新应用通过，也不删除正常 Vue/Playwright 测试。 |

保留三类兼容能力：

- [TS importer](../../packages/core/src/storage/legacy.ts)、schema、files/backup、graph legacy 及迁移测试仍处理旧 SQLite/`django_migrations` 版本、bigint、媒体与失败回滚；不运行旧 migrations。保留 [CredentialVault](../../packages/core/src/storage/credentials.ts)/双向 AES-GCM 测试、[passwords](../../packages/core/src/auth/passwords.ts) 的 PBKDF2 编码兼容。`packages/core/src/legacy/` 是当前租户/渠道业务，不是待删 Django 服务。
- [auth.test.ts](../../packages/core/test/auth.test.ts) 174–186 行在默认 `npm test:core` 仍实际调用 Python 的 Django hasher；正常运行无 Django与默认检查仍有测试依赖须分开。后续先将已实测双向结果绑定可追溯黄金向量并独立验证新哈希，再移除该解释器要求；不删断言、不加 skip。AES-GCM 的 Python `cryptography` 测试仍需独立环境，和根旧 requirements 的退役分别处理。
- MIT 根/worker 许可证；新 worker 的 DOC/PPT Apache POI 样本、来源和 Apache-2.0；MT19937 算法许可；公共数据 CC-BY-NC-4.0/版本/内容 hash。旧/新 DOC/PPT逐字节 SHA 相同；新 registry 的180题ID、revision、files、corpus OID、两旧 manifest SHA和许可7项均相同。旧手工 `chunking/retrieval` 注释资料尚未证明新副本等价，先保留/归档。

[静态证据](../refactor-evidence/20261012-legacy-retirement-review/audit.json) 记录265候选 tracked文件、312 Python AST/1048旧绝对导入、worker旧业务导入0、当前候选 git status为空；这不撤销基线已有改动的归属。SPEC记载的私有452文件快照本轮未读取或复核，不能据此宣称已可恢复。[174条基线旧源码链接](../refactor-evidence/20261012-legacy-retirement-review/baseline-source-link-impact.json) 须在后续退役迭代有可追溯保留/引用方案，不改冻结失败与历史收据。

保护范围：所有用户 `db.sqlite3/marlin.sqlite3` 及 WAL/SHM、media、`.settings/.secrets/.env`、缓存中已计费向量、旧数据库/图归档、私有快照、现有安装/备份全部不触碰；不运行旧迁移、不 reset/clean/stash。现冻结 [6e37](../refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json) 的989绑定只读核对相同。建议顺序：先移除默认测试与旧E2E入口的 Django 依赖，再固定许可/fixture/历史引用，完成对应替代验收后按明确路径清理，最后执行新核心/前端/桌面与 Windows 检查；当前 Windows 构建冻结期间不改来源。
