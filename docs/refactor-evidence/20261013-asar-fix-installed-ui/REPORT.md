# Windows 安装版真实 UI 收尾验收

2026-10-13。按用户“选择性跳过一些步骤，快速收尾”的最新范围，完成新安装包的正常登录、主要业务闭环、真正退出及同目录重启、专用 QA 登录清理。以下结果来自实际安装版与真实厂商调用；原 38 组／69 个 UI 编号的完整验收状态继续保留，本报告不宣称全部通过。

## 产物与运行边界

正式安装器为 `C:\Users\lxd\AppData\Local\Temp\Marlin ASAR Fix Installers 20261013 v2\Marlin-Setup-0.6.2-x64.exe`，401,913,207 字节，SHA256 `4edc4d970ccf383b9dd48a6ef38bce1b192e071a1c450a186c0bd63c54abc52e`。[Root 最后核验](root-final-installer-verification.json)实际 SHA／大小命令均退出 0；[正式构建报告](../20261013-asar-bootstrap-windows-build/REPORT.md)保留完整准备／打包结果及实际 ASAR→Electron main→bundled Node→Core／native Job 门禁。

实际程序为 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用\Marlin.exe`，独立资料目录为同验收根下的 `业务验收 20261013`，原 `desktop-profile` 保留；artifact binding 为 `8643e55788d3e958ebdc90edde8af619d150f219d9abca058c8902dd44e562c2`。隔离升级 25,381 个文件与正式产物匹配，安装前后 DB／WAL／SHM／opaque Key 保持，见[安装收据](../20261013-asar-fix-installed-preparation/installed-receipt.json)。UI 操作始终使用该正常程序，页面地址为 `https://marlin.local/…`，未注入认证、调用测试启动入口或连接开发服务器。Source Core／Vite 已按原身份停止，见[来源服务清理](../20261013-source-test-cleanup/REPORT.md)。

## 实际操作与结果

| 页面／行为 | 前置与操作 | 预期及实际结果 | 证据 |
| --- | --- | --- | --- |
| 正常登录、知识库及文档 | slot1 Main 36052／FILETIME 134363572936733190；窗口 HWND 10227418；使用专用 QA 邮箱及私有 stdin 口令正常登录 | 进入知识库，当前空间 2 库／16 文档／10,027 摘录／0 处理中。全流程库 2 文档／7 摘录／13 总块；现行手册及图片均已完成 | [登录后的页面](006-authenticated-app.json)、[文档工作台](010-fresh-workbench.json) |
| 真实检索问答 | 从全流程知识库“发起对话”，输入“安装版收尾验收20261013：根据当前知识库的现行手册，晨星A项目的负责人和预算分别是什么？请附上资料引用。”，点击发送 | 新会话 `0a2c671c-71dd-45a4-87c5-385c491dc7f2`；GLM 回答负责人林青、预算 128,000 元，与自建手册标准答案一致。完成实际 `knowledge_search`／`list_knowledge_docs`，答案显示 5 条引用 | [发送](014-send-factual-question.json)、[初期生成状态](015-reply-observation.json)、[完成答案](016-reply-observation.json)、[截图](016-reply-observation.png) |
| 引用与父子分块 | 展开 5 条引用，点击第一条“查看来源” | 实际跳转到文档 `e1b8ada2-c9af-4c3e-a437-a0ec37972c44`／块 `9af19299-3e9d-4acd-a599-f9bf623dee57`；显示正确“项目与负责人”正文、父块关联与完成解析记录 | [引用](017-expand-citations.json)、[来源片段](019-source-chunk-view.json)、[截图](019-source-chunk-view.png) |
| Wiki 与设置 | 点击 Wiki／晨星A实体；进入账户设置、模型管理和系统信息 | 真实 Wiki 实体内容、采购表格、来源及目录可读；模型页四类各 1 个、4 个凭据已配置；系统显示 TypeScript／SQLite／sqlite-vec／已验证 1024 维 | [Wiki 实体](022-open-wiki-entity.json)、[四类模型](025-models-visible.json)、[系统信息](027-system-information.json) |
| 关闭窗口、真正退出 | 从新截图点击原生窗口关闭按钮；随后通过任务栏隐藏图标打开本应用托盘菜单，读取并实际点击“退出” | 关闭窗口后原 Main 仍存活于后台；实际托盘退出后 Main、bundled Core 及所有捕获成员均正常结束，原 Job 树为 0，未强杀 | [关闭动作](032-click-native-close-button.json)、[真实托盘控件](038-native-menu-current-controls.json)、[实际退出点击](039-click-real-tray-exit.json)、[原 HANDLE 终态](../20261013-asar-fix-installed-preparation/launch-1-terminal.json) |
| 同目录重启及持久化 | slot2 Main 22820／FILETIME 134363584175021276；HWND 17633934；同 exe、资料、profile 正常重开，点击对话 | 自动保留合法 QA 身份；仍是 2 库／16 文档；实际恢复同会话、问题、林青／128,000 答案、5 条引用及 RID `617950a6`。未再次发送问题 | [重开](040-reopened-normal-app.json)、[知识库](041-reopened-session-state.json)、[恢复原问答](043-reopened-chat-history.json) |
| 专用 QA 设备和登录清理 | 设备页逐一撤销复制进来的 5 个旧 QA 网页设备，每次确认并回读“已撤销”；最后通过账户菜单退出登录 | 最后只剩当前专用桌面设备，退出登录后正常回到空输入的登录页；无 logout-all、真实管理员口令修改或其他用户设备操作 | [明确 QA 身份](045-account-and-devices.json)、[初始设备](047-native-qa-device-list.json)、[首个撤销结果](049-confirm-copied-qa-device-one.json)、[其余设备完成](058-confirm-owned-copied-device.json)、[正常退出登录](061-logged-out-normal-login.json) |
| 第二次真正退出 | 重新读取本应用托盘“退出”控件并实际点击 | 同一原 Main 22820、Core Node 6128 及 8 个捕获成员均原 HANDLE wait0／exit0，Jobactive0；没有 shutdown-error，opaque Key 与第一次／升级前相等 | [实际菜单](064-second-tray-exit-item.json)、[退出点击](065-second-real-tray-exit.json)、[原 HANDLE 终态](../20261013-asar-fix-installed-preparation/launch-2-terminal.json) |

Root 已实际查看登录、答案、引用、重启知识库和退出登录截图。上述按钮的 provider 调用通常标注 unverified；业务结论依据随后真实路由／内容／状态及原进程终态，未将单个工具成功替代业务成功。

## 最后只读核对与调用成本

[实际 SQLite 核对](../20261013-asar-fix-installed-preparation/final-sqlite-readonly.json)证明当前会话属于专用 QA、两条消息均完成、助手有 5 条引用且包含正确文档／块／负责人／预算，实际完整 request ID 为 `617950a6-80be-453e-af64-0a20115be125`。model_usage 从复制基线 174 到 180；本次新增 6 条记录均成功，共 6,241 token，重启后没有增加调用。包含检索 Embedding 1 次、Rerank 1 次、Agent 对话 2 次，以及按既有记忆配置执行的关键词／记忆抽取各 1 次。最终 desktop_jobs／task_records 活动数均 0，专用 QA 未撤销设备数 0。

首次只读核对误把页面 2 库／16 文档当作整库总数，因整库含其他空间／临时库的 6 库／18 文档而退出 1，该失败原件保留。随后按实际 Core 当前 tenant／权限／非临时库过滤的[补充核对](../20261013-asar-fix-installed-preparation/final-sqlite-scoped.json)退出 0，正确得到当前页面 2 库／16 文档。两次 SQLite 均 mode=ro／query_only／totalChanges0；没有修改其他空间记录来满足断言。

本条产品轨迹记录 knowledge_search 478ms、list_knowledge_docs 4ms；持久化厂商调用记录 Embedding 292ms、Rerank 139ms、两次 Agent 模型调用 9,297ms／13,214ms。关键词／记忆抽取分别 1,318ms／6,448ms。各耗时的范围不同，不相加冒充端到端时间。本次没有精确采样正文首段或每次增量输出，不给 TTFT／P95 结论；操作 JSON 的 command_elapsed_ms 是测试工具耗时。

四类模型真实验收及 5 条审核通过的真实 Ragas 评测复用[原模型结果](../20261010-windows-model-vendor-regression.json)和[原评测报告](../../desktop-refactor/EVALUATION-CHINESE-QUERY-BROWSER.md)，没有为收尾重复收费评测。此前文本／图片入库、各格式 worker、迁移与备份恢复结果继续按原来源记录；本轮安装版最小复核使用这些真实既有文档，未重复上传全格式。

## 工具限制、清理与未覆盖范围

旧 869 安装包的实际启动 FAIL 及本轮中间构建 FAIL 保留，成功只属于上述新 v2 产物。Orca 的一次过期索引拒绝、任务栏 windowNotFound、Alt+F4 的 F4 不支持，以及原生关闭后 app_not_found 均保留。任务栏操作使用本机 UIAutomation 查找真实可见控件及实际鼠标点击，限定原 Main 身份和 Marlin 的 NotifyItemIcon／退出 MenuItem；未向进程发送退出消息、调用 app.quit 测试入口或强杀。第一次鼠标操作后的 UI 元素已经失效，输出 controlName=null；其 fresh 前置菜单和严格唯一控件匹配、实际坐标及原终态共同记录结果。

两次正常退出及无活动任务确认后，Root 精确删除唯一 mode0600 的 QA 口令文件，未归档其中内容；两个 UI helper 和清理 helper 已按字节归档并删除，见[清理收据](root-consumed-auth-ui-cleanup.json)。资料副本、正常凭据材料、模型配置及 QA 的业务记录保留，既有 Source 的专用 QA 设备也已单独清理。本轮没有提交、推送、发布或改 GitHub 名称。

按最新授权跳过重复全量测试／审计冻结、其他平台交付、可选 Langfuse／Neo4j 部署、全部长尾权限／异常／崩溃／卸载组合、所有尺寸及 DPI／IME 组合。这些继续标记跳过或未验证，不计入通过。安装器标识为 0.6.2、Core 系统页显示 0.7.0，版本展示的一致性整理留作低优先优化；未为此修改来源或再次打包。完整限制、正常运行命令及交付入口见[最终报告](../../desktop-refactor/FINAL-REPORT.md)及[精简清单](../20261013-fast-closeout-checklist/CHECKLIST.md)。
