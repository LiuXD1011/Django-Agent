# 单次安装版 smoke 可见surface诊断准备

默认review_only，未执行Windows/Marlin/core/GUI/模型。详见[短设计](../../desktop-refactor/INSTALLED-SMOKE-VISIBLE-DIAGNOSTIC.md)、[完整168行脚本](reviewed-harness.source.txt)、[实际准备检查](commands.json)、[守卫源码](prepare-guards.source.txt)与[冻结](freeze.json)。不改旧failed/产品/d79/e48/主docs。

Root完整阅读并核全部SHA后，唯一一次显式Windows命令：

```powershell
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-installed-smoke-visible-diagnostic-20261012.py --execute-reviewed --reviewed-script-sha256 d4126f6ccbf91aaa976a7e33c761e53e3d16cd1e2a1be5e1891aff3dac71f834 --binding-request-sha256 c722f63696436c86401c4d14444ca77a877695ab45331c921ff5b8ac2fee3fb9
```

新空数据固定 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\.smoke-visible-diagnostic-20261012-1\全新空启动数据`，任何目录/receipt已存在拒绝重试。直接CreateProcess的Marlin.exe PID必须与exe/FILETIME和窗口owner一致；只一次ShowWindow(4)，不focus/input、不换GPU/认证参数。10秒为发现/观察预算，不谎称同步Win32调用硬timeout；外层私有Job180秒+原同handle30秒reap保留，只清理所属Job/仍挂起bootstrap。

执行后会生成独立 `shown-owned-window.json` 和 `executed-visible-smoke-diagnostic.json`，它们不在准备freeze里。即使verified_visible_diagnostic_only，也仅证明显示窗口后的产品原capture/ready流程单次成功；默认hidden是否已修、正常GUI登录/D02/H/性能样本不能从它推出。原UnknownVizError始终failed。Root仍须查看新产品截图。主临时脚本保留供Root执行，消费后归档删除；准备guards/validator已按SHA归档删除。

准备检查12/12为Fake SDK：不显示外国PID/25268、owner变动/多窗/错误class/尺寸/子窗/进程已退出拒绝、隐藏窗Show返回0仍可验证可见、UnknownViz/mount-only/node/HTTP/错误计时拒绝及PNG头守卫。PNG fixture仅模拟结构头，不是产品截图；未将它作真实Windows图像或登录通过。实际Win32定义来自[ShowWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindow)、[EnumWindows](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows)、[GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid)和[GetClientRect](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclientrect)，及此前已审Native HWND/PID代码。
