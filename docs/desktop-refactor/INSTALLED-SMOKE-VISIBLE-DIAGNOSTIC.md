# 安装版 hidden smoke 截屏诊断准备

最新版5cab/99baabee安装升级已真实完成，原hidden smoke失败收据保持。原程序所属树已正常退出，JSON只有 `ok=false/message=UnknownVizError`，缺少原renderer结果；不能据此断言登录页未挂载，也不能恢复为成功。Root核Electron源码后把UnknownVizError定位到capturePage的CopyFromSurfaceError，底层为何没有可复制surface仍需实测。

本次按Root已经批准的单变量诊断，只准备新review_only harness，Root另行执行一次。同一installed `Marlin.exe --smoke-test --data-dir <全新专有空目录>`，原ASAR、GPU/Node/认证参数、IPC/renderer wait与产品capturePage都不改。新空目录与原failed smoke、retained、clone、25268数据互不重叠；不删除旧收据或重放旧目录。资料restore与这一诊断独立，不在诊断中打开它。

复用d79归档中的安装身份/安全路径与已审b12原生CreateProcess、私有Job、6926同handle30秒收尾。`on_started`来自CreateProcess返回的直接Marlin.exe PID，先拿存活process handle/真实exe/FILETIME；拒绝Python、Node包装或25268。最多10秒枚举该PID的top-level窗口，只选唯一Chrome_WidgetWin_1、无owner、700–4096宽/500–2160高的client主窗；再次核PID、IsWindow与process存活后，仅一次 `ShowWindow(hwnd,SW_SHOWNOACTIVATE=4)`，不SetForegroundWindow/激活/输入。记录PID/HWND、尺寸、前后IsWindowVisible、原生返回与foreground handle；显示动作是诊断，不是业务点击或真实登录验收。

[ShowWindow官方定义](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindow)说明4不激活窗口，返回值表示先前是否可见；原隐藏窗返回0不能算调用失败，须单独IsWindowVisible核验。[EnumWindows](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows)回调BOOL与HWND/LPARAM、[GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid)DWORD/LPDWORD、[GetClientRect](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclientrect)RECT/LONG等实际签名已核。10秒是发现与显示后观察预算；同步ShowWindow本身没有timeout参数，不能宣称OS调用的严格硬上限。外层180秒私有Job和原失败清理仍保留，只对自己的Job/仍挂起bootstrap处理，不按名称kill其他进程。

产品必须继续自行capturePage并产出原smoke JSON/PNG：mounted/pageReady/login、preload protocol1/IPC、nodeExposed=false、TS core0.7.0/http_listener=false、readiness时段/顺序、https://marlin.local/login和PNG结构全部要求保留；工具不制造结果或替换capture。实际成功只证明这个单次被显示的诊断模式，不能直接算默认hidden模式修复、实际GUI登录/D02/H或P95；Root还须查看截图。若仍UnknownVizError，保留新failed收据，不叠GPU参数或自动重试。

新脚本及准备证据位于[独立目录](../refactor-evidence/20261012-installed-smoke-visible-diagnostic/README.md)。准备测试使用Fake SDK，仅验证PID/窗口挑选/回调返回/预算与结果守卫，不调用Windows、应用、core、GUI、原资料或厂商。主脚本保持临时目录供Root全读核SHA，消费后归档删除；d79/e48/产品/主进度docs及旧freeze保持原字节。
