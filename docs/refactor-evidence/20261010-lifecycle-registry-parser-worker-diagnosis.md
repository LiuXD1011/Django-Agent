# Installed 生命周期注册检查误拒绝：独立诊断与限定修复

日期：2026-10-10；owner：parser_worker。

结论：实际注册键名和检查器一致；错误是检查器向卸载键要求 NSIS 未写入的 `InstallLocation`，再将缺值的 FileNotFoundError 误判成缺键。Root 授权仅修一次性 handoff 的 `check_registry`，真实原生 Windows 只读函数回归由 RED 到 GREEN。没有执行生命周期 phase、Core、应用、安装器/卸载器或 GUI，没有改注册表、产品、正式 stage、WORK、收据、attempt 或私有 NTFS handoff。

## 原生事实及完整合同核对

完整读取原 handoff 中 check_registry、run/attempt 围栏、root 升级脚本 `/tmp/marlin-root-installed-code-upgrade-20261010.py` 和已安装 electron-builder 26.15.3 的 NSIS 注册逻辑。相关契约：

- `NsisTarget.js:157–163`：APP_GUID 与 UNINSTALL_APP_KEY 均来自固定 guid（本 GUID 无反斜杠，不发生替换）。
- `templates/nsis/multiUser.nsh:8–9`：安装键 `Software\<GUID>`，卸载键 `Software\Microsoft\Windows\CurrentVersion\Uninstall\<GUID>`。
- `templates/nsis/include/installer.nsh:104`：仅安装键写 `InstallLocation`；119、122、123 行在卸载键写 DisplayName、UninstallString、QuietUninstallString，没有向卸载键写 InstallLocation。
- `templates/nsis/common.nsh:47–75`：x64 目标在 RunningX64 使用 SetRegView 64；没有凭空推断另一个键或删除 32/64 检查。
- root 升级脚本分别读取安装键 location 和卸载键 command，因此前置 code-upgrade 没有这个错误。

实际 native Windows Python 3.13.3 只读诊断命令 exit 0，保存 [原始受限投影](20261010-lifecycle-registry-parser-worker-readonly.json)。只读取专用两个键、32/64 views、HKCU/HKLM，公开值限 InstallLocation / UninstallString / DisplayName：

| 实际键 / view | 结果 |
| --- | --- |
| HKCU Software\GUID，32 与 64 | 都存在；InstallLocation 精确为专用 `Marlin 安装验收 20261010\应用`。 |
| HKCU Uninstall\GUID，32 与 64 | 都存在；InstallLocation 不存在；UninstallString 精确为该专用目录的 `Uninstall Marlin.exe` 加 `/currentuser`；DisplayName 为 `Marlin 0.6.2`。 |
| HKLM 两键，32 与 64 | 全不存在。 |

因此不是安装键丢失、GUID 改名或 wrong view。原 check_registry 第 202 行对两个键都调用 QueryValueEx(InstallLocation)；在真实卸载键必然抛 FileNotFoundError，第 208 行误转 `owned_registration_missing`。

专用 receipt 实际为 failed / post-upgrade / owned_registration_missing / outcome_requires_manual_review=true，没有 application_probes 或 native_execution，paid=0；attempt 明确 automatic_retry_or_resume=false。仅取得 PID 15700 的查询/同步只读 handle，实际 alive 且 image 与既有 QA 固定路径一致，未停止该进程。

## 授权最小修复与实际 RED → GREEN

唯一产品外修改：`/tmp/marlin-installed-lifecycle-20261010.py::check_registry` 改为 index==0 才读并精确校验 InstallLocation；else 保留两种精确卸载命令。没有新增 DisplayName 要求、没有放宽 key/view/hive，也没有其他 fallback。完整 [差异](20261010-lifecycle-registry-parser-worker-fix.diff) 已归档。

实际以 AST 提取 handoff 的 Refusal/need/check_registry，原生 Windows Python 调用该确切函数，未调用 run/main。两个正常状态病例直接读取真实注册表；八个负例仅改变只读测试投影，不写真实注册表。受控负例明确区分于真实外来安装：

- [RED](20261010-lifecycle-registry-parser-worker-red.json)：10 项中 5 通过、5 失败，exit 1；真实 installed baseline 误拒绝，以及 32 view/卸载命令校验被前置误拒绝掩盖。
- [GREEN](20261010-lifecycle-registry-parser-worker-green.json)：10/10、exit 0；真实 installed baseline 通过。32/64 外来安装路径、32/64 外来卸载命令、外来 quiet command、缺安装键、缺卸载键、HKLM 注册、卸载后残留键均仍按精确错误码拒绝。
- 初次自有回归工具在读取 UTF-8 handoff 时使用 Windows 默认 GBK，发生 UnicodeDecodeError，尚未调用函数。修正工具的显式 encoding=utf-8 后才运行上述正式 RED；该工具错误不计产品 RED 或成功病例。

命令形状：

```text
/mnt/c/Python313/python.exe -I -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-lifecycle-registry-regression-parser-worker-20261010.py red
/mnt/c/Python313/python.exe -I -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-lifecycle-registry-regression-parser-worker-20261010.py green
```

原 handoff SHA `20ebcc6f0a4561aaf56ed638f072a033ba0c83dc24b6b083f49f2c0ceed2957f`；本次交付 registry 修正版 **`b3a33bea1f11e0d4bab9207fd620a0249d7912ecb981ab6100d97000930e6856`**，36687 bytes / 548 lines。逆向替换唯一修改片段后，整份文件字节与原 SHA 完全相同，证明本次修改范围仅此函数。Python compile 通过，无 PYC。

交接该 SHA 与 GREEN 后，root 独立将 WORK 改为 `.lifecycle-20261010-reviewed-2`，用于保留原失败的新 attempt；收尾时当前 handoff SHA 为 **`f736da363dca7aaacda6a9f3134ab1c7efc2a0cd8db5730fab24814a4acf3e9e`**。仅只读逆向该 WORK 单行，完整文件恢复 b3a33bea… SHA，确认 registry 函数及其他代码未变。本审查未编辑、回滚或执行 root 的新 attempt；RED/GREEN 的 source SHA 原样保留 b3 修改前后的历史。

## 历史失败保留与执行边界

原生 Windows 再次只读复算原失败文件，修改/回归后 SHA 仍精确相同：

- post-upgrade.json：`887d44ecf301f6aac547e2189eeee04517717ae544523e608dc7be8fda58bcd0`。
- post-upgrade.attempt.json：`99b8c2c6ef7c4dfe0746fe6550f25b39e1972f4eafc3e219f8ee129b693b0a9a`。

没有删除、覆盖或绕过失败 ledger，也没有改变 WORK 路径。Root 会人工审阅后建立新 attempt 并保留此前失败；本检查不授权自动重放。已成功的 code-upgrade 与本次函数 GREEN 不等于 post-upgrade、卸载保留、重装、再次身份恢复、GUI 或模型验收通过。

既有 [生命周期计划](20261010-installed-lifecycle-plan.md) 保留前一 URL 修正版 20ebcc6f… 的历史 SHA；后续执行须 root 审阅其新 WORK 版 f736da36… 文件并使用对应 SHA，不能用旧 NTFS 副本。没有修改计划或私有副本。

自有只读诊断脚本、回归脚本及修改前临时字节备份用完精确删除；最终 handoff 保留给 root。未触碰其他 agent 文件或真实用户资料。
