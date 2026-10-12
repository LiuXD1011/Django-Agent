# 侧栏属性修复的 Windows 包刷新计划

> **For agentic workers:** 使用 executing-plans 按以下检查点执行。Root 明确发出“源码已冻结可构建”前，本计划仅为只读准备；不运行构建、安装或GUI。

**Goal:** 将Root负责的Platform.vue导航属性修复纳入独立Windows x64安装器，并保留旧99ba产物及其完整历史证据。

**Architecture:** 将上一轮已验证Windows staging复制到新builder-owned目录，正式`verify_reusable`通过后用`--refresh --prepare-only`重建源码并重跑全部既有门禁。新目录单独NSIS打包、ASAR审计与安装绑定，旧stage/output及原失败收据不修改。

**Tech Stack:** 正式Python构建脚本、Windows x64 Node22.23.2、Python build host3.13.3/pip25.0.1、payload Python3.13.16、Electron44.7.0、electron-builder26.15.3。

## 固定边界与已核事实

- 本轮产品修改仅由Root负责`frontend/src/views/Platform.vue`的aria-label/title/type/aria-current和必要回归；不改依赖、版本、核心、桌面及构建脚本。本计划不修改产品或主文档/FINAL。
- 旧[5cab来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)有457输入、5额外测试、523本地编译产物。旧[prepare](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-execution.json)实际0/1806.244s，Windows前端361/361、Vite42.97s；旧[package](../refactor-evidence/20261012-web-search-result-integrated-windows-build/package-execution.json)实际0/824.276s。
- 旧安装器`Marlin-Setup-0.6.2-x64.exe`为401841299字节/SHA99baabeeb82dd4af6312356810a91d0a2b51ec1c62726a8de3d917305fe5a8f6。旧[ASAR审计](../refactor-evidence/20261012-web-search-result-integrated-windows-build/asar-audit.json)SHA0fc884…、app.asar SHA895f93…、runtime25304文件，实际stage关键manifest/gates/ASAR已只读核对。安装器本轮只核stat/sidecar与已绑定历史收据，不把它称为再次完整payload审计。
- 桌面package/ASAR metadata版本0.6.2、核心package/capabilities版本0.7.0；frontend metadata仍0.6.2-django。系统页`info.version`展示核心返回版本，不是Electron安装版版本测量；名称中的django不意味着payload含Django。此次不改这些版本。
- 原四模型QA保护25268/FILETIME134361236166333286保持。安装路径仍专用`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`；原数据和已恢复clone不由构建访问。隐藏UnknownVizError及45ef整体失败不能因这次侧栏修复改为通过。

## Task 1：等待Root源码冻结，建立独立复制阶段

**Files/接口：** 复用[正式builder](../../scripts/build_windows.py)的`source_inputs(root)`、`verify_reusable(root,work)`、`walk_files(directory)`、`copy_source(source,destination)`和`guard_workspace(work)`；不改这些函数。

- [ ] Root完成真实属性回归、前端完整单测及build，提供新source-freeze路径与严格64hex SHA。逐项核sourceInputs、additionalReviewedTestInputs、localCompiledOutputs及requiredCompletedChecks的真实成功回执；旧核心/桌面/dependency SHA必须一致，不以旧全套授权变更后的前端。
- [ ] 旧目录只读：`C:\Users\lxd\AppData\Local\Temp\Marlin TS Search Result Final Build 20261012`。新目录固定为`C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Final Build 20261012`；新OUTPUT固定为`C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Installers 20261012`。二者必须不存在，不复用或覆盖旧路径。
- [ ] 全文复读后改写上一67行runner的独立临时副本：`/tmp/marlin-root-web-search-result-windows-build-20261012.py`（当前88f00c…）→`/tmp/marlin-agent-sidebar-a11y-windows-build-20261012.py`。新证据固定`docs/refactor-evidence/20261012-sidebar-a11y-windows-build/`；执行前Root审阅新完整source/hash。保留build-host/Python/Node/Job/冻结/唯一收据守卫，明确prepare是verified-dependency refresh，不伪称npm clean install。
- [ ] 在复制前运行正式`verify_reusable(REPO, OLD_WORK)`：完整payload SHA清单、5锁、Windows Node针、两个Python worker实际source集合及prod包检查全部通过；任何差异拒绝，不重写旧manifest、不绕过native binding。
- [ ] 新目录用正式marker归属；只复制旧builder staging，不复制用户QA或正式安装目录。排除旧`app/release`产物和旧prepared/gates/audit/controlled-gates验证结果，保留原payload/source-manifest及已验证Windows依赖、Python缓存和Chromium。用正式无junction/symlink复制接口，结束后`verify_reusable(REPO, NEW_WORK)`再次通过；旧关键manifest/gates/ASAR及旧产物sidecar前后保持。复制失败留独立失败记录，不能用其部分payload继续。

## Task 2：正式refresh prepare与新NSIS产物

**Files/接口：** [windows-gates.py](../../scripts/desktop/windows-gates.py)、[verify-payload.cjs](../../scripts/desktop/verify-payload.cjs)、[build-python-runtime.py](../../scripts/desktop/build-python-runtime.py)、[windows-job.py](../../scripts/desktop/windows-job.py)、[audit-asar.cjs](../../scripts/desktop/audit-asar.cjs)。已完整读实际实现。

- [ ] 新runner调用以下实际builder CLI，绑定Root新freeze；不得直接对旧WORK运行refresh。

```powershell
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\scripts\build_windows.py --refresh --prepare-only --work-dir "C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Final Build 20261012" --build-node "C:\Users\lxd\AppData\Local\Temp\Marlin Root Build Host 20261010\node-v22.23.2-win-x64\node.exe" --node-cache "C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010\node-cache" --output-dir "C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Installers 20261012"
```

- [ ] 保留Windows前端**完整**unit真实TAP及Vite生产构建、core build与所有正式native gates：24核心路由、6编译runtime原断言、实际SQLite FTS/vec精确大整数及IPC、11格式/Python/Ragas隔离、Electron/NextAuth。不以Linux通过替代，也不放宽最小数量、no-skip、零付费或source_before_after_equal。受控Electron门禁可能显示/聚焦窗口，启动前与Root GUI租约协调。
- [ ] 每阶段私有Job timeout3600秒，完整树清理事实按实际记录；复用系统build-host`C:\Python313\python.exe`，不改为不含pip的installed runtime。Node/Python/Electron下载缓存复用须保持正式SHA/lock检查；禁止Linuxbetter-sqlite3复制到Windows。
- [ ] prepare实际成功、完整树收尾、新prepared-build与新冻结完全一致后，调用正式package-only：

```powershell
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\scripts\build_windows.py --package-only --work-dir "C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Final Build 20261012" --build-node "C:\Users\lxd\AppData\Local\Temp\Marlin Root Build Host 20261010\node-v22.23.2-win-x64\node.exe" --output-dir "C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Installers 20261012"
```

- [ ] 正式electron-builder仅`--win nsis --x64 --publish never`。NSIS前后重新verify_prepared/source；ASAR必须仍为10文件白名单，metadata cleanup正确、每代码字节一致、runtime完整inventory与manifest一致。新EXE名称仍0.6.2，但独立目录/实际新SHA/新freeze区分版本来源；生成新的size、SHA sidecar及导出七份正式报告，不能预填产物hash或把99ba改名当新包。

## Task 3：本地升级与实际侧栏复验交接

- [ ] 新prepare/package/ASAR成功后，独立适配当前399行安装绑定harness`/tmp/marlin-root-search-result-installed-20261012.py`（e48ac4…，已全文读）。只改新STAGE/OUTPUT/evidence/ownedWORK与新请求绑定，保留default review_only、私有NSIS Job及6926同句柄30秒reap、唯一iteration/create-new收据/完整runtime验证。精确进程race拒绝保留；本轮不未经新审阅直接用旧process_preflight绕过曾出现的native_candidate_path_unavailable。
- [ ] 新binding request必须绑定真实新freeze、EXE size/SHA、prepare/package执行SHA、ASAR SHA；root binding helper`/tmp/marlin-root-final-installed-binding-20261012.py`（b6b9bb…，已全文读）只能作为独立改写参考，不运行其旧5cab常量。升级前应用自然退出，采集新的当前完整数据+12业务表/凭据baseline；不能强用历史94文件profile哈希做现在的baseline。
- [ ] Root完整审阅新harness后才执行专用安装升级；按现有正确same-handle退场guard判断所属进程，保留原四模型QA。正常可见clone单独重绑定新installed/restore数据身份与新owned receipt，复用[既有138行正常launcher归档](../refactor-evidence/20261012-installed-clone-visible-launch/reviewed-harness.source.txt)，不要要求历史原harness接受变动的workspace SHA。
- [ ] Root通过正式IPC在1024×768实际核两个导航按钮可访问名称、title/type/aria-current及正确导航；补1440对照后自然关闭/托盘退出、Job0与业务/media/vault后置。不可仅静态扫描minified bundle作为GUI通过；隐藏截屏缺陷仍单独未完成。不重新调用付费模型或Ragas，不提交/发布。

## 目前仍存在的临时脚本

只读调查时实际存在如下脚本；本计划不编辑、执行或清理它们，执行阶段优先使用审阅归档，以免Root随后正常消费删除：

| 绝对路径 | 本轮读到的SHA前缀/用途 |
| --- | --- |
| `/tmp/marlin-root-web-search-result-windows-build-20261012.py` | 88f00c609ab8…，67行build runner；未来独立改写 |
| `/tmp/marlin-root-search-result-installed-20261012.py` | e48ac41306c9…，399行安装binding/upgrade参考 |
| `/tmp/marlin-root-final-installed-binding-20261012.py` | b6b9bb3cf4f5…，旧artifact请求生成参考 |
| `/tmp/marlin-agent-integrated-installed-20261012.py` | 6926f38880fa…，已审reap版本；保留 |
| `/tmp/marlin-agent-cancel-installed-launch-20261012.py` | 8cf04e7bebb3…，旧launcher归档一致；保留 |
| `/tmp/marlin-agent-offline-windows-clone-20261012.py` | d79d502ba816…，旧restore；本次不重跑 |
| `/tmp/marlin-agent-installed-smoke-visible-diagnostic-20261012.py` | d4126f6ccbf9…，旧一次诊断；本次不重放 |

76e11正常clone临时脚本已不存在，使用其既有归档；Root已完成b357正常退出事实保持。这些旧工具不能以保留在/tmp当作新执行授权。当前阶段没有创建新执行runner、source-freeze、installer或安装收据，只有本计划与只读证据。待Root明确“源码已冻结可构建”后在同代理按上述顺序执行，无需重复用户批准。
