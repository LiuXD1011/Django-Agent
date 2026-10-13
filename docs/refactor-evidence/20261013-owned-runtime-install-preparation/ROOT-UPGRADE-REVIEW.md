# Root 固定隔离升级复核

2026-10-13。根据 Goal 第 2.3、2.4 节对本地构建和隔离安装验收的既有授权，Root 已完整读取当前待审 harness、私有 Job、固定升级 runner、只读实际收据、安装准备报告及其引用的 registry/data guard/inventory/ASAR 工具实现。

复核结论：允许下一步执行一次固定 owned 安装升级。此结论是执行前复核，不是安装成功或整个 Goal 完成的结论。

| 绑定 | SHA-256 |
| --- | --- |
| reviewed-binding.json | `4ebfac55400742bcd68f9ba2311fa9d3db7b889ce62a3478cc97ae54f746c56f` |
| reviewed-harness.source.txt / 精确临时 harness | `d307c0de52548ea1df9150ff6ae466b30ffedea16997d47ec0d6bca7617ddb40` |
| reviewed-private-job.source.txt / 精确临时 Job | `823014d210855849e43f1daf85b52636a439c405e815e0ca551bbe9b273a36c7` |
| reviewed-upgrade-runner.source.txt / 精确临时 runner | `5b9cf61f52dca119439e82ff81ab11550db3486cabddd893cb075f87b47866a3` |
| 实际只读 survey | `2424fd782e1203979bfcc8bf7111fa904322c4805edbad6ff495531d40c7d2cc` |
| artifact-binding.json | `e03d77180601b09cfee12011187e8d62e338e6ade99aeba81c1ef76d2c5b443c` |
| 固定安装器 | `869a0401224675d15d1aa515b2a587a657d4caf704044a8ac641a49ab7f896e9` |

Root 当前 shell 实际 SHA 核对为 exit 0；待执行分支相对已执行只读版的差异另行读取，未把前版实际只读通过视为升级分支已经通过。

执行范围仅为已有 marker 与成功安装收据对应的 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`。独立数据 `验收数据 二次` 应保持完整；在实际启动安装器前重新检查 HKLM/HKCU 两 view 共 8 条注册、无运行的安装版/foreign Marlin、旧 uninstaller SHA 与固定安装器 SHA。任何前置条件变化都应在安装器创建前停止。

执行固定 runner 的一次 `upgrade` 调用：outer private Job 1200 秒，inner 固定 NSIS 整树 900 秒，再等待原 bootstrap HANDLE；仅操作自产 Job。实际返回与 Job 原 HANDLE/FILETIME 终态、所有安装资源以及数据表/文件/凭据哈希结果必须归档；失败不自动重试或重写原收据。

本步骤不启动产品 GUI、不操作模型或真实用户数据、不发布、不提交。现存相关旁实例为 0，历史 PID25268 原退出原因仍未知，不声明其保留通过。安装包绑定旧 468 项源码；随后 sidebar/detail/autostart 修改尚未包含，最终仍需新版构建与验收。

执行依据与原始收据见 [准备报告](REPORT.md)、[只读实际收据](readonly-preflight.json)、[实际只读终态](native-readonly-execution.json)、[具体升级分支差异](upgrade-only-review-refinements.diff)。执行结果由后续实际回执记录。
