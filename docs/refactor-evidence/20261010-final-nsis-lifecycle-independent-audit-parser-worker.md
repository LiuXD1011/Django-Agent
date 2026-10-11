# Final NSIS 与生命周期 handoff 独立审计

日期：2026-10-10；审查者：parser_worker。

结论：正式 NSIS 产物与本轮 frozen_source prepare 绑定一致。生命周期 handoff 有一项已确认的 smoke URL 测试误拒绝，已按 root 授权仅增加精确 `/login` 并冻结。首次生命周期阶段仍缺本轮 code-upgrade 收据，应继续停止在准备状态。本次没有安装、启动 Core、操作 GUI、停止已有进程或发送模型请求。

## 原生 Windows 产物只读核验

全文读取 [NSIS proof](20261010-windows-repository-final-nsis-proof.json)、summary/build-exit、ASAR audit、生命周期计划及最终 547 行 handoff。随后仅运行自有标准库只读审计脚本，命令为：

```text
/mnt/c/Python313/python.exe -I -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-final-artifact-readonly-parser-worker-20261010.py
```

实际目标平台 Windows x64、测试主机 Python 3.13.3，命令 exit 0。没有调用安装器、应用、Core 或官方验证器的任何执行阶段。检查结果：

- 外部 Final Installers EXE 与 `Final Build/app/release` 内部 EXE：大小均为 **401778413 bytes**，完整 SHA 均为 `1a9f6ccec8d154d9ed7019ab8b05416dc038e4c51ee23f4d816ca541268950bc`，另实际逐块比较全部字节相同。
- 输出目录精确 **9 文件**：EXE、其 SHA 文件、7 report sidecars；没有额外文件。SHA 文件的名称/完整哈希正确。
- 7 sidecars 与正式 stage 对应原文件逐字节相同，大小/SHA 与 proof 一致。11 个 repository_evidence 归档的实际大小/SHA 全部一致。
- 实际 ASAR SHA `555b30fca642151d3a8a75629d377a0e561fbf5713a7b6b71bd2b7ec52cfdc1a` 匹配 audit。独立解析真实 ASAR header，提取全部 **10 个**资产；名称/SHA 完全匹配。9 个非 package.json 文件与 staged app 字节相同；package.json 精确匹配 documented cleanup 后的 metadata。
- packaged runtime 的 source-manifest 字节与 staged payload 及 sidecar 相同；runtime 数 25279 与 audit 相同。本次没有再次哈希全部 25279 个实体；`complete_runtime_inventory_matches:true` 是已有官方 ASAR audit 的结论，现核对该结论及报告/manifest 字节绑定。
- prepared `44272b04f54ff0a03f56bbe5ebca502f6267086ac1b862f0e413ff6b45cc1629`、gates `860dba721dd62e74ad76a236c5db5585b43b8d5d89e1de168a52efac7832b8aa`、manifest `0082290f3a4dcd9b6c0d8c067914a05e7b853b26f4f81464198eec24a656d559` 实际匹配；状态 verified、scope frozen_source、paid calls 0。

本轮机器结果不等于 installed 生命周期、GUI、四模型厂商或 Ragas 验收。NSIS proof 本身也是 `candidate_built_verified_pending_product_acceptance`，不是产品最终通过。

## 生命周期合同与已解决误拒绝

原审阅 handoff SHA `a6f1d36e5cfc7220455b2418650a3a037ca80048753269c57303593e3eabe1d9`，计划原 SHA `b0e1e05620106e172622d6b845caa793f19293bcb5d4943d4dda3d84aa43e727` 均在修改前实际复算匹配。没有执行 handoff 的任何 phase，包括 review-only。

| 合同 | 只读判断 |
| --- | --- |
| 默认/范围 | 无 execute flag 在固定参数校验后直接返回 review-only，先于 formal validator、Win32、CIM、数据库及所有子进程；四 phase、stage、installer、安装/数据目录和 PID 均固定，不能从 CLI 扩权。 |
| 新 Final 绑定 | formal_identity 使用 source-bound 官方 verify_prepared，再核 EXE SHA、七 sidecars、ASAR 与 win-unpacked inventory；后续阶段要求前一条 receipt SHA、script SHA、整个 identity 相同。实际本轮 hashes 已复算匹配。 |
| 认证 | 内嵌 Node 只走 installed CoreIpcAdapter saved session→auth/me，必要时正常 refresh，再实际授权 GET 原 KB；真实 user/current device/tenant/KB 检查保留。tenant String 修复合法；无构造 AuthContext、密钥输入或密码重置。 |
| 数据保留 | 停止状态只读 integrity/foreign keys、12 表全部行 SHA、完整 data inventory 与解密材料 SHA；post-upgrade 仅允许真实 refresh 对 device_sessions 的写入，之后固定 retained baseline。卸载/重装对全部保留数据逐项精确比较。 |
| 进程 | 自有 CreateProcessW suspended→private Job assign→resume，等待 ActiveProcesses=0；超时/失败只清理该 Job 或自己尚未 assign 的 child。保护既有 PID 的 handle/image，拒绝系统现有 Marlin 及目标前缀进程，不自动停止它们。此处是结构核对，不宣称这个 handoff 的 Windows Job 实跑通过。 |
| 未知停止 | exclusive WORK、phase attempt 与 receipt，无失败/未知自动 retry 或 resume；下一 phase 需人工确认精确前序 receipt。卸载没有 delete-app-data/updated/_?=/D；重装固定 `/D=` 尾参不走 shell。 |

**确认误拒绝：** handoff 第 404 行原谓词只允许 `https://marlin.local` 与 `/`。当前真实 [root source smoke](20261010-root-source-desktop-smoke.json) 的 `url` 是 `https://marlin.local/login`；`desktop/main.cjs` 读取真实 `location.href`，因此正常认证路由会在进入 saved-auth 前被误拒绝。Root 授权的唯一变更是将精确 `https://marlin.local/login` 加入该集合，没有允许任意 path/HTTP/subdomain。

实际从源 AST 提取该完整 `need()` 第一个参数，使用真实 root smoke JSON 和 URL 篡改重放：[RED](20261010-lifecycle-url-parser-worker-red.json) **10/11、exit 1**；[GREEN](20261010-lifecycle-url-parser-worker-green.json) **11/11、exit 0**。原 origin 和 `/` 保留，八个 HTTP/异域/子域/任意路径/查询/额外路径/javascript/data 负例仍拒绝。完整 [单行 diff](20261010-lifecycle-url-parser-worker-fix.diff) 已保存；逆向删除唯一新增 URL 字节，整份脚本与原 a6f1d36e…完全相同。Python compile 通过，没有生成 PYC。这不是 installed 阶段执行。

最终 handoff：36644 bytes、547 lines，SHA **`20ebcc6f0a4561aaf56ed638f072a033ba0c83dc24b6b083f49f2c0ceed2957f`**。更新后的 [计划](20261010-installed-lifecycle-plan.md) SHA **`17b01acdcbf8e32ac13dc66b8c0073dbad7c61a6eb783f1ae1f0db47d0df11fc`**。旧私有 NTFS 副本须由 root 按新 SHA 原字节更新并审阅，不能继续用旧版本。

## 执行前阻断与清理

本次只检查公开仓库收据是否存在，发现 `docs/refactor-evidence/20261010-installed-code-upgrade.json` **不存在**。第 436–437 行要求该 verified 收据匹配本轮新 EXE SHA、ASAR、12 表和解密材料保留事实，因此目前不能执行 post-upgrade。还需 root 继续完成评分 timeout 分类及独立正式 code-upgrade；本审查没有绕过 hold。

剩余实际身份恢复、HKCU/HKLM、protected handle、offline data baseline、卸载/重装均由显式阶段实际验证；任一失败必须停止并人工调查。机器 mounted/PNG 不证明 GUI 就绪，也不证明 normal tray quit。

自有 artifact 审计临时脚本、AST 回归脚本和原 handoff 临时字节备份在用完后精确删除；最终 handoff 保留供 root 使用。没有删除 stage、用户数据、私有备份、unknown ledger 或其他 agent 文件。
