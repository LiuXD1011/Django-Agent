# 收起侧栏的按钮名称

2026-10-12 在正式安装版 1024×768 窗口中发现：侧栏收起后，对话与知识库按钮的 UIA 名称为空，账户入口只读作 `O`。[原始安装版快照](../refactor-evidence/20261012-root-native-clone-gui/054-installed-actual-1024-layout.json)及[修复前失败核对](../refactor-evidence/20261012-sidebar-accessible-names/before-installed-1024.json)保留；失败核对退出 1，三项按钮用途检查均为 false，没有重放 GUI 或修改安装包。

原因是窄窗口样式把 `.nav-item span` 和 `.account-copy` 设为 `display: none`，而 [Platform.vue](../../frontend/src/views/Platform.vue) 的桌面按钮此前没有独立 `aria-label`。移动导航已有当前页语义，桌面导航没有。已核查安装的 Vue `runtime-dom.d.ts`：`aria-label`、`title` 接受字符串，`aria-current` 接受 `page` 或 `undefined`。

采用最小属性修复：桌面导航按钮绑定现有 `item.label` 的 `aria-label` 和 `title`，复用 `isActive()` 设置 `aria-current`；账户按钮设置“账户与设置”的名称及提示，导航按钮声明 `type="button"`。保留布局、断点、图标、路由处理和账户菜单。仅加 `title` 会依赖浏览器的名称回退；恢复隐藏文字会改变收起布局，故选择独立可访问名称。

独立登录验收的关键撤销请求结束后已编辑组件，产品改动仅为上述属性。`frontend` 的 [完整单元测试](../refactor-evidence/20261012-sidebar-accessible-names/unit-execution.json)实际退出 0：361/361 通过，0 失败、0 跳过；[Vite 生产构建](../refactor-evidence/20261012-sidebar-accessible-names/build-execution.json)实际退出 0。两项执行前后组件 SHA 均为 `effbfbc36f45764dcd085ee0b64d0eea620358a98936613927d84bfe51f2038f`，差异检查通过。构建保留超过 500 kB 的 chunk 提示，没有放宽限制。113582.559 和 40824.975 毫秒分别是验证耗时，不是产品响应时间。

源码浏览器在专用验收账号正常登录后，已通过 Orca 的[实际页面只读核对](../refactor-evidence/20261012-auth-browser-isolation-real/102-d2-platform-sidebar-accessibility.json)：对话、知识库、账户与设置均具有正确名称与提示，两个导航按钮为 `type="button"`，知识库带 `aria-current="page"`。这仅证明源码页面的 DOM 属性；没有调整该浏览器尺寸，不替代安装版 1024×768 收起侧栏的 UIA 与实际导航复验。

当时计划按[独立 Windows 刷新计划](SIDEBAR-A11Y-WINDOWS-REFRESH-PLAN.md)生成新的本地安装包并核门禁、完整资源和1024侧栏UIA/导航；此计划现已按下述正式收据执行，不重写旧99ba历史。新[来源冻结](../refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json) SHA为 `6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8`，457输入仅此组件改变，5额外测试/438 core产物保持，85前端产物绑定新Vite，总523；不能要求旧前端派生产物不变。

这是已批准重构 Goal 中的界面缺陷修复，不新增业务功能、不改依赖或版本、不提交或发布。前置依据来自真实安装版 UIA；不新增仅重复属性实现的单元测试。前端测试、实际浏览器/安装版后置检查通过后才更新修复状态；即使该子项通过，J 组的缩放、其他页面及生命周期仍需独立验收。

新 Windows 构建目录的[实际复制终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-execution.json)已退出 0，所属进程树收尾通过：81263 个文件、2146851880 字节，809.733 秒。正式 `verify_reusable` 分别核验旧目录和新副本的 payload 与锁文件，旧关键资源及安装器 sidecar 前后保持。[Root 独立来源审查](../refactor-evidence/20261012-sidebar-a11y-root-source-review/review.json)也核对全部冻结输入与已完成检查的日志。目录复制不计为构建成功。

随后[原生 Windows prepare](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-execution.json)实际返回 0、所属树收尾通过，1293.909 秒，执行收据 SHA 为 `ec6c3442b7fae79b4ab1303b9f6af0fffde9169b7c4563247cc3e934cb3faa4c`。真实完整前端为 361/361、失败/取消/跳过为 0，TAP 504302.974 毫秒；Vite 47.66 秒、核心构建及正式五项原生门禁通过，24 核心路由与 6 编译运行测试没有跳过，Python 11 类格式和 Electron/NextAuth 协议检查通过，模型调用为 0。这些耗时属于验证，不是产品延迟。

[实际package](../refactor-evidence/20261012-sidebar-a11y-windows-build/package-execution.json)与所属树收尾均退出0，生成401841335字节安装器，SHA `aabd44bc71a7a36b3d583720f8292b4035efe1c69159740db513931293568556`；[来源绑定](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/artifact-binding.json)将其与6e源、原生门禁、完整runtime及ASAR绑定。fresh readonly baseline后，[唯一隔离升级](../refactor-evidence/20261012-sidebar-a11y-install-preparation/iteration-1/executed-upgrade.json)会话74424实际退出0：NSIS329.421秒、bootstrap/Job退出0，未强制终止；25379安装文件/25304运行资源匹配，94数据文件/12业务表/凭据材料保持，原PID25268同代次在该升级时点仍存活。当时尚未运行本包隐藏或可见验收，后续1024侧栏UIA与导航复验见下节；原隐藏截图失败保持。

其后源码另有[知识库分类修复](KNOWLEDGE-BASE-TYPE-FILTER.md)与[认证测试脱离Django](PBKDF2-COMPATIBILITY-CHECK.md)。本6e包不包含这两项后续变化，继续按历史侧栏来源验收，不称它是全部最新修复的交付包。

## 2026-10-13正式安装版复验

历史6e37/aabd侧栏包已实际正常运行，唯一 visible session53956、PID12324/FILETIME134363313315163659，正常 `Marlin.exe --data-dir` 打开独立资料副本，没有 smoke/GPU/认证注入或开发服务器参数。Root 用 Orca 实际查看1440×900与1024×768截图，收起侧栏“对话”“知识库”“账户与设置”三名称正确；真实点击分别打开既有会话、用户设置并返回知识库，统计2/16/10027/0保持，正常恢复自有QA身份，未输入密码或发送模型请求。实际标题栏关闭后同代次窗口隐藏/进程仍活，核 fresh 托盘菜单属于12324后只点“退出”一次；自有 bootstrap exit0、Job active0、完整所属树退出、reap0.03ms/0强制终止。工具 `app_not_found`/退出1和首次托盘观察超时保留。[真实侧栏与生命周期步骤](SIDEBAR-INSTALLED-GUI-ACCEPTANCE.md)、[48bindings/21链接冻结fd5b](../refactor-evidence/20261013-root-sidebar-native-gui/freeze.json)。

整条严格 launcher 仍是实际 exit1：原收据 SHA `7a3d2ee1664e6c4964d8cc51a7aba34b5a63a3591e63aefd81ebc3678327b293`，自有程序正常退出后因 `protected_process_path_unavailable` 拒绝，`clone_after` 未生成；原收据不改写，正常自有退出不能替代完整保护门禁通过。573636.545ms是人工验收期间程序寿命，0.03ms是bootstrap reap，都不是启动或页面延迟。[原失败收据](../refactor-evidence/20261013-sidebar-clone-launch-preparation/executed-visible-clone.json)、[Root28项证据边界](../refactor-evidence/20261013-root-sidebar-native-gui/root-evidence-review.json)。

独立退出后确认审计 session5782实际exit0/收据da7481598：全部72表已采集，68保护表、保护desktop_meta、25托管文件、24媒体引用和79个已认证凭据字段与本轮基线相等，0活动工作/未决认证；3个auth/meta表摘要有变化，不能写72表全部相等或GUI前后profile全字节不变。原副本本审计期间123文件/79目录exact，readonly快照DB SHA不变，精确自有db/key/WAL/SHM已删。原PID25268不在Toolhelp、OpenProcess87，无法补出其历史退出码/时间/原因，也没有持续存活通过证据；本轮12324同代次句柄Wait0/exit0另支持自有正常退出。独立投影通过不将原strict1改为0。首轮快照清理1、参数守卫1和GBK前置1全部保留。[独立结果与边界](SIDEBAR-POSTCLOSE-AUDIT.md)、[确认收据](../refactor-evidence/20261013-sidebar-postclose-audit/independent-postclose-confirmation.json)、[38bindings/17链接冻结169d](../refactor-evidence/20261013-sidebar-postclose-audit/freeze.json)。

实际6e安装包退出链路的静态审查没有发现按端口或进程名泛化清理；但Runtime 30秒超时fallback仍使用captured child.pid的 `taskkill /T /F`，没有FILETIME pin。没有观察到本轮触发，也不能据此解释原25268消失；必须继续生命周期归属与PID复用审查/修复及实际异常退出、非干扰验收，不把静态路径视为本次因果。[打包链路审查](../refactor-evidence/20261013-sidebar-postclose-audit/packaged-shutdown-static-review.json)。

侧栏缺陷的实际安装版名称及三个窄窗口导航复验已经完成；原99ba失败与源码DOM观察继续按各自来源保留。1440/1024截图经Root实际查看，DPI96，未验证125%/150%、IME或全部页面。严格保护门禁没有整体通过，不把J组或Goal改为PASS。[具体步骤与原始回执](SIDEBAR-INSTALLED-GUI-ACCEPTANCE.md)。

本6e包尚不包含后续B类型筛选、PBKDF2测试脱离Django、TS认证E2E入口或[共享页生产修复](SHARED-TAB-AUTH-FIX.md)；新源码最终冻结/门禁/打包与安装验收仍待进行。

共享页auth生产修复另已补[自然Orca账号交接](SHARED-TAB-ORCA-ACCEPTANCE.md)：同profile两页真实mouse、旧A自动切B、server/cache一致及A私有库不可见，独立临时资源已完整清理、n=1/0模型。此源码浏览器结果不进入历史6e包，不替代安装版认证或侧栏/J整组验收；最新打包仍待。
