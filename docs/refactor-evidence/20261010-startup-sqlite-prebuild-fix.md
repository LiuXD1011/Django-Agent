# Windows source launcher：锁定 SQLite prebuild 路径修复

2026-10-10，parser_worker。只改 `scripts/desktop/start-desktop.cjs` 的一个必要路径，以及其 `startup.test.cjs` fixture/5 条针对性回归。未修改正式 payload、manifest、依赖、模型、用户数据或 GUI；未运行 NSIS。源码已冻结，正式 stage 必须由 builder 正常 refresh 后重新绑定，不能手改旧清单。

## 根因与范围

[root 正式 payload 只读诊断](20261010-root-source-launcher-payload-diagnostic.json) 显示 19 个 required 项中只有 `core/node_modules/better-sqlite3/build/Release/better_sqlite3.node` 缺失。其余 18 项在完整 25279-file manifest 内。

实际锁定 `better-sqlite3@13.0.3` 的 `lib/binding.js` 优先加载 `prebuilds/win32-x64.node`，专用 `lib/win32-x64.js` 也固定使用该 published N-API 文件。`build/Release/better_sqlite3.node` 是 node-gyp fallback，本项目 Linux 旧 GLIBC 自编译会使用；Windows 正式干净安装正常保留 published prebuild。

真实历史 [payload manifest](20261010-windows-repository-final-clean-payload-manifest.json) 有 `core/node_modules/better-sqlite3/prebuilds/win32-x64.node`，SHA256 `e21e5efd71fba66578e95b62554d9028064a80dafd7221bf8a8ef155de8d240a`。builder 原生 gate 已通过实际包 loader 的 SQLite/FTS/vector 探测；这次不重复制造假 gate 或复制 native 文件到旧位置。

最小修复：[start-desktop.cjs](../../scripts/desktop/start-desktop.cjs:14) requiredPayload 将旧 fallback 路径替换为固定的 Windows x64 published prebuild。没有增加猜测 fallback、降低必要性、跳过全量 SHA 或放宽 native report 条件。内存中仅把该新字符串还原，重算全文件 SHA 正好等于 root 诊断的旧 launcher SHA，证明生产修改确实只有这一处。

## 实际 RED → GREEN

- [Linux RED](20261010-startup-sqlite-fix-red.tap)：新增 5 条实际 launcher fixture 回归，`2 pass / 3 fail`，exit 1。published 布局无法通过 preflight；只有旧 fallback 的 fixture 错误到达 spawn；篡改 prebuild 被错误 required 路径挡住而未达到预期 SHA 校验。
- [Linux GREEN](20261010-startup-sqlite-fix-linux.tap)：同样 5 条加关联 native gate 负例、Electron 全分发校验、POSIX owned group cleanup、官方/非官方 marker 边界，共 `26/26`，exit 0，0 skipped，`3973.041327 ms`。运行 `TMPDIR=/dev/shm node --test --test-name-pattern='Windows SQLite prebuild|formal gate semantics reject rebound SHA: (native-|unknown-format|artifact-only)|Electron full distribution rejects executable-bytes|POSIX cancellation|official build marker' scripts/desktop/startup.test.cjs`。tmpfs 是测试环境选择，不是磁盘 durability 验收。
- [原生 Windows TAP](20261010-startup-sqlite-fix-windows.tap)、[事实/身份 JSON](20261010-startup-sqlite-fix-windows.json)：独立 NTFS owned marker 目录，复制 362 份公开 source inputs（含根 package.json）并逐 SHA 校验；只读复制 pinned Node 22.23.2，不执行正式 stage Node/Python/Electron。外层使用已验证 `windows-job.py` 的私有 Job 运行，`14/14`，exit 0，0 skipped，`10589.6273 ms`。覆盖 5 新例、5 native gate 负例、Job cancel/leader-exit 和 LF/CRLF marker；所有复制 source SHA 未变，own NTFS 树已删除。
- 原生 Job 清理实际事实：取消返回 143、cleanup 103 ms；父进程提前退出返回 7、cleanup 15 ms；两例所属 leader/descendant 都不可再访问，独立 unrelated child 在断言时仍存活。之后只清理该自有 unrelated fixture。
- root 另独立对当前 repository source 运行 5 条 `Windows SQLite prebuild` 回归：`5/5`、exit 0、0 skipped、`677.65963 ms`。这是 root 独立实际工具收据，命令详情在 root transcript；不混算为本 agent 的原生 14 项或重复厂商验证。
- launcher/test 的 `node --check` 均 exit 0。没有 TS 或业务核心改动，未重跑不相关全产品套件。

5 条新例分别证明：锁定真实 published 布局可到受控 Node child；必要 prebuild 缺失被拒；仅旧 node-gyp fallback 被拒；仅 ARM64 文件被拒；prebuild 原 SHA 被篡改时被拒。fixture 的 native/gates JSON 仍为现有 synthetic validator 输入，不能算在 fixture 内真正加载 SQLite或运行 Electron；真实 native probe 是 root 已归档正式 gate 的独立事实。

## 冻结身份与清理

| 文件 | SHA256 |
| --- | --- |
| 旧 launcher（root diagnostic） | `f4409c66da6a78ab721c790bb9e595c12671f80fd53752c5538ae586c2a49d8a` |
| 当前 launcher | `078cee1e42b62b60f4ae0b466b6959f830d79f6dcd2f00bc1b2a8b1668689cb0` |
| 当前 startup.test | `5fd0813855aed55b0ceb27d0c52093355c29b7996c27235e6116587879e2d8af` |
| Windows copied Node | `0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4` |
| 未改 windows-job.py | `8d1ab8c4e54d8dd47715fd3110ee3614c6958ac272db32d30b1bfb7dbf94bd73` |
| Windows TAP | `0252d3d234f5c8fd05addfd68a794a356c47e01b32fb2e85fed60e1be3b09141` |
| Windows facts JSON | `fadc203f653d835f1936d98d86b2e72600a1dfa174eed96102f8a5c2ce06a07a` |

Linux owned fixtures由测试 finally 删除；Windows owned copy及所有子进程由私有 Job/finally 清理，0 paid model calls。执行用 `/tmp/marlin-startup-sqlite-windows-20261010.py` 及两份临时 TAP 在归档核验后删除。另一个已授权 [MCP prep 计划](20261010-local-mcp-parser-worker-plan.md) 与其临时脚本保持未启动，供 root 决定后续时点；它不属于本启动器生产修改。
