# 收起侧栏的按钮名称

2026-10-12 在正式安装版 1024×768 窗口中发现：侧栏收起后，对话与知识库按钮的 UIA 名称为空，账户入口只读作 `O`。[原始安装版快照](../refactor-evidence/20261012-root-native-clone-gui/054-installed-actual-1024-layout.json)及[修复前失败核对](../refactor-evidence/20261012-sidebar-accessible-names/before-installed-1024.json)保留；失败核对退出 1，三项按钮用途检查均为 false，没有重放 GUI 或修改安装包。

原因是窄窗口样式把 `.nav-item span` 和 `.account-copy` 设为 `display: none`，而 [Platform.vue](../../frontend/src/views/Platform.vue) 的桌面按钮此前没有独立 `aria-label`。移动导航已有当前页语义，桌面导航没有。已核查安装的 Vue `runtime-dom.d.ts`：`aria-label`、`title` 接受字符串，`aria-current` 接受 `page` 或 `undefined`。

采用最小属性修复：桌面导航按钮绑定现有 `item.label` 的 `aria-label` 和 `title`，复用 `isActive()` 设置 `aria-current`；账户按钮设置“账户与设置”的名称及提示，导航按钮声明 `type="button"`。保留布局、断点、图标、路由处理和账户菜单。仅加 `title` 会依赖浏览器的名称回退；恢复隐藏文字会改变收起布局，故选择独立可访问名称。

独立登录验收的关键撤销请求结束后已编辑组件，产品改动仅为上述属性。`frontend` 的 [完整单元测试](../refactor-evidence/20261012-sidebar-accessible-names/unit-execution.json)实际退出 0：361/361 通过，0 失败、0 跳过；[Vite 生产构建](../refactor-evidence/20261012-sidebar-accessible-names/build-execution.json)实际退出 0。两项执行前后组件 SHA 均为 `effbfbc36f45764dcd085ee0b64d0eea620358a98936613927d84bfe51f2038f`，差异检查通过。构建保留超过 500 kB 的 chunk 提示，没有放宽限制。113582.559 和 40824.975 毫秒分别是验证耗时，不是产品响应时间。

源码浏览器在专用验收账号正常登录后，已通过 Orca 的[实际页面只读核对](../refactor-evidence/20261012-auth-browser-isolation-real/102-d2-platform-sidebar-accessibility.json)：对话、知识库、账户与设置均具有正确名称与提示，两个导航按钮为 `type="button"`，知识库带 `aria-current="page"`。这仅证明源码页面的 DOM 属性；没有调整该浏览器尺寸，不替代安装版 1024×768 收起侧栏的 UIA 与实际导航复验。

接下来按[独立 Windows 刷新计划](SIDEBAR-A11Y-WINDOWS-REFRESH-PLAN.md)生成新的本地安装包，重跑正式门禁与资源一致性核对；最后在实际收起窗口用 Orca 重新检查三个按钮名称与导航。新安装包复验尚未完成，旧 `99baabeeb82dd4af6312356810a91d0a2b51ec1c62726a8de3d917305fe5a8f6` 安装器及其历史核对结果不改写。[新来源冻结](../refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json) SHA 为 `6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8`，457 源码输入仅此组件改变，5 项额外测试保持，438 项核心编译文件保持；85 项前端产物绑定本次构建，总编译文件仍为 523。新 Vite 资源的内容摘要和文件名变化需绑定本次构建，不能要求旧前端派生产物保持不变。

这是已批准重构 Goal 中的界面缺陷修复，不新增业务功能、不改依赖或版本、不提交或发布。前置依据来自真实安装版 UIA；不新增仅重复属性实现的单元测试。前端测试、实际浏览器/安装版后置检查通过后才更新修复状态；即使该子项通过，J 组的缩放、其他页面及生命周期仍需独立验收。
