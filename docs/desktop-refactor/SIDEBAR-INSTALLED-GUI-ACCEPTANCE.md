# 侧栏修复的正式安装版点击复验

本轮实际运行已升级的 Windows x64 安装版，桌面版本 0.6.2、Core 0.7.0，绑定历史来源 `6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8`。安装器 SHA `aabd44bc71a7a36b3d583720f8292b4035efe1c69159740db513931293568556`，正常入口为安装目录的 `Marlin.exe --data-dir` 验收副本；没有 smoke、GPU、认证注入或开发服务器参数。该包包含侧栏名称修复，尚不包含后续知识库分类和共享标签页认证修复。

启动前[本轮只读基线](../refactor-evidence/20261013-sidebar-clone-launch-preparation/fresh-clone-baseline.json)绑定 72 张当前表、79 个已认证加密字段、24 个媒体引用、116 文件及 79 目录。唯一 visible 启动器重新检查其全部摘要和清单相等后才启动。[实际启动身份](../refactor-evidence/20261013-sidebar-clone-launch-preparation/visible-clone-started.json)为 PID 12324、FILETIME 134363313315163659；Root 后续所有主窗口操作限定 HWND 21828318，并在每次操作前核对进程代次、路径与窗口所有者。没有修改管理员密码，也没有输入密码；应用正常恢复了原验收账号的会话。

| 操作与预期 | 实际观察与证据 |
| --- | --- |
| 正常打开保留的数据副本 | [首次完整快照](../refactor-evidence/20261013-root-sidebar-native-gui/002-state.json)进入知识库，2 库、16 条目、10027 摘录、0 处理中；后续账户页面显示专用 QA 用户 |
| 1440×900 按钮可读 | [尺寸核对](../refactor-evidence/20261013-root-sidebar-native-gui/003-wide-resize.json)和[实际 UIA/截图](../refactor-evidence/20261013-root-sidebar-native-gui/004-wide-state.json)吻合，Root 已查看 PNG；三个入口名称正确 |
| 1024×768 收起侧栏仍有按钮用途 | [尺寸核对](../refactor-evidence/20261013-root-sidebar-native-gui/005-narrow-resize.json)和[实际 UIA/截图](../refactor-evidence/20261013-root-sidebar-native-gui/006-narrow-state.json)吻合；“对话”“知识库”“账户与设置”名称全部存在，Root 已查看 PNG |
| 点击窄侧栏“对话” | [实际点击](../refactor-evidence/20261013-root-sidebar-native-gui/007-narrow-chat-click.json)后，[新状态](../refactor-evidence/20261013-root-sidebar-native-gui/008-narrow-chat-state.json)打开保存的会话 `889d8b97-1948-48f5-a726-47ba367a4430`，显示既有 QA 问答；没有发送新问题 |
| 点击窄侧栏“账户与设置” | [实际点击](../refactor-evidence/20261013-root-sidebar-native-gui/009-narrow-account-click.json)后，[新状态](../refactor-evidence/20261013-root-sidebar-native-gui/010-narrow-account-state.json)进入 `settings?section=user`，显示 `orca-page-qa-20261010@example.invalid`、资料、设备入口和密码弹窗入口 |
| 点击窄侧栏“知识库” | [实际点击](../refactor-evidence/20261013-root-sidebar-native-gui/011-narrow-kb-click.json)后，[新状态](../refactor-evidence/20261013-root-sidebar-native-gui/012-narrow-kb-return.json)返回列表，2/16/10027/0 统计保持 |
| 关闭窗口仍在后台 | 恢复1280×860后点击实际标题栏 X；[同代次原生核对](../refactor-evidence/20261013-root-sidebar-native-gui/016-hidden-state.json)证明 HWND 隐藏、PID 12324 仍活着 |
| 从正确的托盘菜单真正退出 | [普通右键及原生菜单所有者](../refactor-evidence/20261013-root-sidebar-native-gui/020-owned-tray-menu.json)证明菜单 HWND 34605630 属于 PID 12324；[Orca 新菜单快照](../refactor-evidence/20261013-root-sidebar-native-gui/021-actual-tray-menu.json)和 Root 已查看的 PNG 有“打开 Marlin”“退出”。只点击该菜单的“退出”一次，随后自有 Job 全部进程结束 |

Orca 的点击回执标记为未自动断言，导航结论来自点击后的新 URL、页面内容和 Root 实际查看的截图。不能把初始点击回执中的旧 URL 当成导航失败或成功，也没有用 JavaScript 修改路由来代替点击。UIA 首次快照只有区域节点，而同次 PNG 已显示正确页面；下一次完整快照补齐业务节点，这属于观察边界，未重放启动。

关闭窗口与真正退出后，Orca 都因目标已不可见而返回 `app_not_found`、命令退出1；[关闭工具回执](../refactor-evidence/20261013-root-sidebar-native-gui/015-close-window.json)和[退出工具回执](../refactor-evidence/20261013-root-sidebar-native-gui/022-tray-quit-click.json)完整保留。关闭效果由同代次隐藏状态证明，退出效果由独立持有的自有 Job 证明：bootstrap 实际 exit0、active processes0、complete_owned_tree_exited=true、0 强制终止、0 泛化杀进程。首次托盘箭头 Invoke 的5秒观察超时也保留为[工具失败](../refactor-evidence/20261013-root-sidebar-native-gui/018-open-tray.json)；后续只读观察获得实际打开的托盘及最新 runtime ID，然后核对菜单归属，未重复同一 Invoke。

本轮严格 launcher **实际 exit1**，不能称整个启动/保护门禁通过。[不可改写的原回执](../refactor-evidence/20261013-sidebar-clone-launch-preparation/executed-visible-clone.json) SHA `7a3d2ee1664e6c4964d8cc51a7aba34b5a63a3591e63aefd81ebc3678327b293`：已记录自有程序正常退出，随后在退出后审计的前置保护进程查询中报 `protected_process_path_unavailable`，没有 `clone_after`。它没有记录该失败句柄的 wait/exit/error，不能据此断言原 PID25268 正常退出、仍存活或由何种原因结束。原保护进程的末态和副本退出后数据投影将单独只读核查；不重启应用、不修改原门禁来洗掉失败。

[Root 结构化核对](../refactor-evidence/20261013-root-sidebar-native-gui/root-evidence-review.json)的28项检查通过，验证的是上述证据及其结论边界。侧栏名称和三个窄窗口导航复验完成；J组其他页面、125%/150%缩放、中文输入法、单实例、异常恢复及卸载仍需独立验收。当前窗口 DPI96，不能冒充125%/150%结果。573636.545毫秒是这次人工操作期间的完整程序存活区间，0.03毫秒是退出后的 bootstrap reap；两者均不是冷启动或页面延迟。本轮不报告未测量的产品响应时间，不触发模型请求，不标整体Goal完成。
