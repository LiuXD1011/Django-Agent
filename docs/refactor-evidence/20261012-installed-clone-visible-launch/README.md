# 恢复后clone正常可见启动准备

仅准备，默认review_only，不启动Windows/应用/核心/GUI/厂商、不读private口令或原资料。Root审[完整138行脚本](reviewed-harness.source.txt)、[短说明](../../desktop-refactor/INSTALLED-CLONE-VISIBLE-LAUNCH.md)、[Fake守卫](prepare-guards.source.txt)和[冻结](freeze.json)后，显式一次执行：

```powershell
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-installed-clone-visible-launch-20261012.py --execute-reviewed --reviewed-script-sha256 76e11e265438494daaa4f99591b4ae777305f41d2b48278c333ec5ed8c532881 --binding-request-sha256 c722f63696436c86401c4d14444ca77a877695ab45331c921ff5b8ac2fee3fb9
```

固定DATA仍是实际已恢复 `…\Marlin 安装验收 20261010\浏览器资料副本 20261012 第1轮`；新启动WORK `…\.clone-normal-visible-launch-20261012-1`。preflight/安装身份/ca9c restore/c722/failed45ef产品断言/PNG3e89与Rootvisual8b3ae都须符合冻结身份；失败或已有新WORK/receipt拒绝重放，不删除绕过。8b Node审计完全不变，仅用尚空before/after-visible-clone owned输出目录。

正常Marlin.exe只有--data-dir，不重复empty smoke，不改GPU或认证，不注入token/改密码。新owned_process启动后保存visible-clone-started.json；私有Job保持7200秒、每5秒输出，Root可用正确的专用QA口令正常GUI登录并复核资料/报告，再用这个窗口托盘退出。不要结束harness session代替tray Quit；标题栏关闭只后台。后置业务/media/key审计/同handle30秒reap及protected25268守卫仍必需；Auth session/profile正常变化允许，不宣称GUI或hidden已通过。

同handle race记录candidate PID/exe/API/即时LastError/WaitAfter/GetExitCode，只有已signaled退出且退出码API可读才忽略；仍活或未知继续拒绝。未来运行收据`visible-clone-started.json/executed-visible-clone.json`与race observations均排除于准备freeze，防止重复03e5混入Root同期实际观察的歧义；03e5/原failed不回写。

[实际准备结果](commands.json)：8/8仅Fake SDK与AST精确差异/default0；没有真正Windows、数据库、复制或业务调用。准备helper消费后归档删除，主临时脚本保留Root执行后清理。此脚本成功state仅`verified_normal_launch_and_exit_only`；正常登录、D02/H及页面真实性由Root单独证据记录。
