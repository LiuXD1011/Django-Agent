# 恢复后资料副本的可见启动准备

原d412诊断整体仍exit1/failed：其归档第147行已完成产品smoke/PNG断言，第148行protected held handle仍Wait258，第149行全局候选后置检查失败。真正错误位置是6926归档第188行：候选OpenProcess成功、Wait258后QueryFullProcessImageNameW返回0。原收据未保存该候选PID/LastError/失败后Wait，不能确定13240、25268或其他进程，也不能把“进程终止竞态”写成已观察根因。产品单次显示诊断已实际产出login-ready/IPC/TS0.7/noHTTP/nodefalse及1264×821 PNG，但整体收据不改PASS；默认hidden修复也未证明。

诊断03e5准备freeze通过全目录枚举写出，与Root实际执行重叠，含Root同期的shown-owned-window.json；其“0 Windows/native”仅描述代理准备检查，不能作为那8文件整体的0实际声明。该混合freeze保持，不回写；实际诊断以failed45ef收据和Root视觉8b3ae844补记为准。新launch freeze只列明确准备文件，排除所有未来运行/started/race收据。

Root已批准另一个正常可见启动，不重放d412或empty smoke。复用d79已冻结installed_identity、restore后置、业务/media/vault/native审计、b12直接CreateProcess/privateJob和6926同handle30秒reap。前置绑定c722、actual restore ca9c verified、原diagnostic45efaf完整产品结果/PNG3e89，并由Root显式确认已看该图。只启动同一installed `Marlin.exe --data-dir 浏览器资料副本 20261012 第1轮`，无smoke/GPU/auth参数，无token注入或改密码；口令仍通过正常GUI。

新启动WORK/receipt与旧failed/restore目录不覆盖。为不改原8b Node审计固定输出白名单，before/after审计仅在原owned restore WORK下尚未创建的 `before-visible-clone/after-visible-clone`；它们不是旧执行重放，原after-restore收据不变。新App的日志/Job/lifetime均在新的可见启动WORK。7200秒持有/每5秒进度，Root真实GUI复核后从新窗口托盘退出；关闭窗口只是后台。独立原审计保持所有受保护业务表、媒体/key/其他desktop_meta不变，仅允许正常Auth session与profile变化。脚本自身不宣称GUI登录、D02/H或整个Goal通过。

只补后置进程身份检查的同handle竞态：QueryFullProcessImageNameW或GetProcessTimes返回失败时，先立即取其LastError，再在同一OpenProcess handle读WaitAfter/GetExitCode并保存候选PID、exe basename、API/错误/观测。只有Wait0且GetExitCode可读，才允许忽略这一已退出对象；仍活、WAIT_FAILED/未知/退出码读取失败继续拒绝。不能按名字跳过、放宽权限或忽略无法确认的对象；原protected held guard/安装scope/close保持。通过小型AST只替换两个need和增加一个内层except，原循环/finally/权限守卫不删。

准备仅Fake SDK/默认review_only，不执行实际Windows/Core/GUI/厂商或读取原资料，不修改产品/d79/e48/d412/主docs/原failed。源码、守卫和冻结见[独立交接](../refactor-evidence/20261012-installed-clone-visible-launch/README.md)，Root完整阅读核SHA后再执行。
